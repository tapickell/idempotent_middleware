"""Scenario 5: Crash Recovery Conformance Tests

This module tests the middleware's behavior when handlers crash or fail to complete,
leaving records in RUNNING state. Tests cover:

1. Records stuck in RUNNING state after simulated crash
2. Lease token management and expiration
3. Retry ability after lease expiry via cleanup
4. Orphaned RUNNING record cleanup
5. Multiple crashes on same key
6. Concurrent requests during RUNNING state
7. Wait/no-wait policies during stuck RUNNING state
8. Recovery mechanisms

Key behaviors tested:
- RUNNING records can be cleaned up when expired
- Lease tokens expire after TTL
- New requests can retry after cleanup
- Old lease tokens are invalid after cleanup
- Cleanup removes expired RUNNING records
- No permanent deadlocks occur
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from idempotent_middleware.config import IdempotencyConfig
from idempotent_middleware.models import IdempotencyRecord, RequestState, StoredResponse
from idempotent_middleware.storage.memory import MemoryStorageAdapter


# Fixtures
@pytest.fixture
def storage() -> MemoryStorageAdapter:
    """Create a fresh memory storage adapter for each test."""
    return MemoryStorageAdapter()


@pytest.fixture
def config() -> IdempotencyConfig:
    """Create a default config for testing."""
    return IdempotencyConfig(
        enabled_methods=["POST", "PUT", "PATCH", "DELETE"],
        default_ttl_seconds=86400,
        wait_policy="wait",
        execution_timeout_seconds=30,
    )


class TestBasicCrashScenarios:
    """Test basic crash and recovery scenarios at the storage level."""

    @pytest.mark.asyncio
    async def test_handler_crashes_record_stuck_in_running(self, storage: MemoryStorageAdapter) -> None:
        """Test that a crashed handler leaves record in RUNNING state.

        Scenario:
        1. Put new running record (simulating handler start)
        2. Don't call complete/fail (simulating crash)
        3. Record remains in RUNNING state
        4. Lease token is still set
        """
        fingerprint = "a" * 64

        # Acquire lease (simulating handler start)
        result = await storage.put_new_running(
            key="crash-test-1",
            fingerprint=fingerprint,
            ttl_seconds=86400,
        )

        assert result.success is True
        assert result.lease_token is not None

        # Handler crashes here (we don't call complete/fail)

        # Check that record is stuck in RUNNING state
        record = await storage.get("crash-test-1")
        assert record is not None
        assert record.state == RequestState.RUNNING
        assert record.lease_token is not None
        assert record.response is None

    @pytest.mark.asyncio
    async def test_lease_token_preserved_after_simulated_crash(self, storage: MemoryStorageAdapter) -> None:
        """Test that lease token is preserved in crashed RUNNING record.

        The lease token identifies which process holds the execution lease.
        After a simulated crash, the token remains in the record.
        """
        fingerprint = "b" * 64

        # Acquire lease
        result = await storage.put_new_running(
            key="crash-test-2",
            fingerprint=fingerprint,
            ttl_seconds=86400,
        )

        captured_token = result.lease_token

        # Simulate crash (no complete/fail call)

        # Verify lease token still exists
        record = await storage.get("crash-test-2")
        assert record is not None
        assert record.lease_token == captured_token

    @pytest.mark.asyncio
    async def test_concurrent_request_blocked_by_running_record(self, storage: MemoryStorageAdapter) -> None:
        """Test that concurrent request cannot acquire lease while RUNNING record exists.

        Scenario:
        1. First request acquires lease (RUNNING)
        2. First request crashes (stays RUNNING)
        3. Second request cannot acquire lease
        """
        fingerprint = "c" * 64

        # First request acquires lease
        result1 = await storage.put_new_running(
            key="concurrent-test",
            fingerprint=fingerprint,
            ttl_seconds=86400,
        )

        assert result1.success is True

        # First request crashes (no complete/fail)

        # Second request tries to acquire lease
        result2 = await storage.put_new_running(
            key="concurrent-test",
            fingerprint=fingerprint,
            ttl_seconds=86400,
        )

        # Should fail because record already exists
        assert result2.success is False
        assert result2.existing_record is not None
        assert result2.existing_record.state == RequestState.RUNNING


class TestLeaseExpiryAndRetry:
    """Test lease expiration and retry mechanisms."""

    @pytest.mark.asyncio
    async def test_expired_lease_removed_by_cleanup(self, storage: MemoryStorageAdapter) -> None:
        """Test that expired lease allows new request to retry after cleanup.

        Scenario:
        1. Create RUNNING record with short expiry
        2. Wait for lease to expire
        3. Cleanup removes expired record
        4. New request can acquire lease and execute
        """
        fingerprint = "d" * 64
        now = datetime.utcnow()

        # Manually create a RUNNING record with already-expired time
        record = IdempotencyRecord(
            key="expired-lease-test",
            fingerprint=fingerprint,
            state=RequestState.RUNNING,
            response=None,
            created_at=now - timedelta(seconds=10),
            expires_at=now - timedelta(seconds=5),  # Already expired
            lease_token="old-expired-token",
        )

        storage._store["expired-lease-test"] = record

        # Clean up expired records
        removed = await storage.cleanup_expired()
        assert removed == 1

        # Verify record is gone
        record_after = await storage.get("expired-lease-test")
        assert record_after is None

        # New request can now acquire lease
        result = await storage.put_new_running("expired-lease-test", fingerprint, ttl_seconds=86400)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_new_request_acquires_new_lease_after_cleanup(self, storage: MemoryStorageAdapter) -> None:
        """Test that new request acquires fresh lease token after expiry cleanup.

        The new lease token should be different from the old one.
        """
        old_token = "old-token-12345"
        fingerprint = "e" * 64
        now = datetime.utcnow()

        # Create expired record
        record = IdempotencyRecord(
            key="new-lease-test",
            fingerprint=fingerprint,
            state=RequestState.RUNNING,
            response=None,
            created_at=now - timedelta(seconds=10),
            expires_at=now - timedelta(seconds=5),  # Already expired
            lease_token=old_token,
        )

        storage._store["new-lease-test"] = record

        # Clean up expired record
        await storage.cleanup_expired()

        # New request acquires new lease
        result = await storage.put_new_running("new-lease-test", fingerprint, ttl_seconds=86400)

        assert result.success is True
        assert result.lease_token is not None
        assert result.lease_token != old_token

    @pytest.mark.asyncio
    async def test_old_lease_token_cannot_complete_after_cleanup(self, storage: MemoryStorageAdapter) -> None:
        """Test that old lease token cannot be used after record is cleaned up.

        Even if the old token is known, it should not allow completing
        the request after the record has been cleaned up.
        """
        fingerprint = "f" * 64
        now = datetime.utcnow()
        old_token = "expired-token-99999"

        # Create record with expired lease
        record = IdempotencyRecord(
            key="invalid-token-test",
            fingerprint=fingerprint,
            state=RequestState.RUNNING,
            response=None,
            created_at=now - timedelta(seconds=10),
            expires_at=now - timedelta(seconds=5),
            lease_token=old_token,
        )
        storage._store["invalid-token-test"] = record

        # Cleanup removes the record
        await storage.cleanup_expired()

        # Try to complete with old token (should fail)
        response = StoredResponse(
            status=200,
            headers={"content-type": "application/json"},
            body_b64="eyJzdGF0dXMiOiAic3VjY2VzcyJ9",
        )

        success = await storage.complete("invalid-token-test", old_token, response, execution_time_ms=100)

        # Should fail because record no longer exists
        assert success is False


class TestMultipleCrashes:
    """Test multiple crashes on the same idempotency key."""

    @pytest.mark.asyncio
    async def test_multiple_crashes_with_cleanup_between_attempts(self, storage: MemoryStorageAdapter) -> None:
        """Test multiple crashes on the same key with cleanup between attempts.

        Scenario:
        1. First request acquires lease and crashes
        2. Cleanup removes expired record
        3. Second request acquires lease and crashes
        4. Cleanup removes expired record
        5. Third request acquires lease and succeeds
        """
        fingerprint = "1" * 64
        now = datetime.utcnow()

        # First crash
        result1 = await storage.put_new_running("multi-crash-test", fingerprint, ttl_seconds=1)
        assert result1.success is True
        token1 = result1.lease_token

        # Simulate time passing and expiry
        record1 = await storage.get("multi-crash-test")
        assert record1 is not None
        record1.expires_at = now - timedelta(seconds=1)  # Make it expired
        storage._store["multi-crash-test"] = record1

        # Cleanup
        removed1 = await storage.cleanup_expired()
        assert removed1 == 1

        # Second crash
        result2 = await storage.put_new_running("multi-crash-test", fingerprint, ttl_seconds=1)
        assert result2.success is True
        token2 = result2.lease_token
        assert token2 != token1  # Different token

        # Simulate time passing and expiry
        record2 = await storage.get("multi-crash-test")
        assert record2 is not None
        record2.expires_at = now - timedelta(seconds=1)
        storage._store["multi-crash-test"] = record2

        # Cleanup
        removed2 = await storage.cleanup_expired()
        assert removed2 == 1

        # Third attempt succeeds
        result3 = await storage.put_new_running("multi-crash-test", fingerprint, ttl_seconds=86400)
        assert result3.success is True
        token3 = result3.lease_token
        assert token3 != token2  # Different token

        # Complete successfully
        response = StoredResponse(status=200, headers={}, body_b64="e30=")
        success = await storage.complete("multi-crash-test", token3, response, execution_time_ms=100)
        assert success is True

        # Verify completed state
        final_record = await storage.get("multi-crash-test")
        assert final_record is not None
        assert final_record.state == RequestState.COMPLETED

    @pytest.mark.asyncio
    async def test_retry_after_cleanup_requires_same_fingerprint(self, storage: MemoryStorageAdapter) -> None:
        """Test that retry after cleanup with same fingerprint works.

        After a crash and cleanup, the same request can retry.
        """
        fingerprint = "2" * 64
        now = datetime.utcnow()

        # Create crashed and expired record
        record = IdempotencyRecord(
            key="fingerprint-test",
            fingerprint=fingerprint,
            state=RequestState.RUNNING,
            response=None,
            created_at=now - timedelta(seconds=10),
            expires_at=now - timedelta(seconds=5),  # Expired
            lease_token="old-token",
        )
        storage._store["fingerprint-test"] = record

        # Cleanup expired
        await storage.cleanup_expired()

        # Retry with same fingerprint should work
        result = await storage.put_new_running("fingerprint-test", fingerprint, ttl_seconds=86400)
        assert result.success is True


class TestOrphanedRecordCleanup:
    """Test cleanup of orphaned RUNNING records."""

    @pytest.mark.asyncio
    async def test_cleanup_removes_only_expired_records(self, storage: MemoryStorageAdapter) -> None:
        """Test that cleanup removes only expired records, not active ones."""
        now = datetime.utcnow()

        # Create multiple records with different states and expiry
        records = [
            IdempotencyRecord(
                key="expired-running",
                fingerprint="a" * 64,
                state=RequestState.RUNNING,
                response=None,
                created_at=now - timedelta(seconds=20),
                expires_at=now - timedelta(seconds=10),  # Expired
                lease_token="token-1",
            ),
            IdempotencyRecord(
                key="active-running",
                fingerprint="b" * 64,
                state=RequestState.RUNNING,
                response=None,
                created_at=now,
                expires_at=now + timedelta(seconds=86400),  # Not expired
                lease_token="token-2",
            ),
            IdempotencyRecord(
                key="expired-completed",
                fingerprint="c" * 64,
                state=RequestState.COMPLETED,
                response=StoredResponse(status=200, headers={}, body_b64="e30="),
                created_at=now - timedelta(seconds=20),
                expires_at=now - timedelta(seconds=10),  # Expired
                lease_token=None,
            ),
        ]

        for record in records:
            storage._store[record.key] = record

        # Run cleanup
        removed = await storage.cleanup_expired()

        # Should remove 2 expired records
        assert removed == 2

        # Verify which records remain
        assert await storage.get("expired-running") is None
        assert await storage.get("active-running") is not None
        assert await storage.get("expired-completed") is None

    @pytest.mark.asyncio
    async def test_cleanup_releases_locks_for_expired_records(self, storage: MemoryStorageAdapter) -> None:
        """Test that cleanup releases locks for expired records."""
        now = datetime.utcnow()
        key = "lock-cleanup-test"

        # Create expired record
        record = IdempotencyRecord(
            key=key,
            fingerprint="d" * 64,
            state=RequestState.RUNNING,
            response=None,
            created_at=now - timedelta(seconds=10),
            expires_at=now - timedelta(seconds=5),
            lease_token="lock-token",
        )
        storage._store[key] = record

        # Manually create a lock (simulating it being held)
        storage._locks[key] = asyncio.Lock()

        # Run cleanup
        removed = await storage.cleanup_expired()
        assert removed == 1

        # Lock should be removed too (since it's not held)
        assert key not in storage._locks

    @pytest.mark.asyncio
    async def test_bulk_cleanup_of_orphaned_records(self, storage: MemoryStorageAdapter) -> None:
        """Test cleanup of many orphaned RUNNING records at once."""
        now = datetime.utcnow()

        # Create many expired RUNNING records
        for i in range(10):
            record = IdempotencyRecord(
                key=f"orphaned-{i}",
                fingerprint="e" * 64,
                state=RequestState.RUNNING,
                response=None,
                created_at=now - timedelta(seconds=20),
                expires_at=now - timedelta(seconds=10),
                lease_token=f"token-{i}",
            )
            storage._store[record.key] = record

        # Cleanup should remove all 10
        removed = await storage.cleanup_expired()
        assert removed == 10

        # All should be gone
        for i in range(10):
            assert await storage.get(f"orphaned-{i}") is None


class TestConcurrentRequestsDuringRunning:
    """Test concurrent requests when a record is in RUNNING state."""

    @pytest.mark.asyncio
    async def test_concurrent_request_blocked_by_running_record(self, storage: MemoryStorageAdapter) -> None:
        """Test that concurrent request cannot acquire lease while RUNNING record exists.

        This tests the wait_policy behavior at the storage level.
        """
        fingerprint = "f" * 64

        # First request acquires lease
        result1 = await storage.put_new_running(
            key="concurrent-block-test",
            fingerprint=fingerprint,
            ttl_seconds=86400,
        )

        assert result1.success is True

        # Second concurrent request tries to acquire lease
        result2 = await storage.put_new_running(
            key="concurrent-block-test",
            fingerprint=fingerprint,
            ttl_seconds=86400,
        )

        # Should fail because record exists and is RUNNING
        assert result2.success is False
        assert result2.existing_record is not None
        assert result2.existing_record.state == RequestState.RUNNING

    @pytest.mark.asyncio
    async def test_concurrent_request_succeeds_after_completion(self, storage: MemoryStorageAdapter) -> None:
        """Test that concurrent request gets cached response after first completes."""
        fingerprint = "1" * 64

        # First request acquires lease
        result1 = await storage.put_new_running(
            key="concurrent-complete-test",
            fingerprint=fingerprint,
            ttl_seconds=86400,
        )

        assert result1.success is True

        # First request completes
        response = StoredResponse(status=200, headers={}, body_b64="eyJzdGF0dXMiOiAic3VjY2VzcyJ9")
        success = await storage.complete("concurrent-complete-test", result1.lease_token, response, execution_time_ms=100)
        assert success is True

        # Second request tries to acquire lease
        result2 = await storage.put_new_running(
            key="concurrent-complete-test",
            fingerprint=fingerprint,
            ttl_seconds=86400,
        )

        # Should fail but get COMPLETED record
        assert result2.success is False
        assert result2.existing_record is not None
        assert result2.existing_record.state == RequestState.COMPLETED
        assert result2.existing_record.response is not None


class TestLeaseConfiguration:
    """Test lease duration and timeout configuration."""

    @pytest.mark.asyncio
    async def test_lease_duration_matches_ttl(self, storage: MemoryStorageAdapter) -> None:
        """Test that lease duration matches the configured TTL.

        The lease should be valid for the entire TTL period.
        """
        fingerprint = "2" * 64
        ttl_seconds = 3600

        # Create record
        result = await storage.put_new_running(
            key="lease-duration-test",
            fingerprint=fingerprint,
            ttl_seconds=ttl_seconds,
        )

        assert result.success is True

        # Check record expiry
        record = await storage.get("lease-duration-test")
        assert record is not None

        # Expiry should be approximately now + TTL
        now = datetime.utcnow()
        expected_expiry = now + timedelta(seconds=ttl_seconds)
        time_diff = abs((record.expires_at - expected_expiry).total_seconds())
        assert time_diff < 5  # Within 5 seconds

    @pytest.mark.asyncio
    async def test_short_ttl_enables_quick_recovery(self, storage: MemoryStorageAdapter) -> None:
        """Test that short TTL enables quick recovery from crashes.

        With a short TTL, crashed records expire quickly and can be retried.
        """
        short_ttl = 2  # 2 seconds
        fingerprint = "3" * 64

        # Create crashed record with short TTL
        result = await storage.put_new_running(
            key="quick-recovery-test",
            fingerprint=fingerprint,
            ttl_seconds=short_ttl,
        )

        # Simulate crash (no complete/fail)

        # Make it expired by manipulating the record
        record = await storage.get("quick-recovery-test")
        assert record is not None
        now = datetime.utcnow()
        record.expires_at = now - timedelta(seconds=1)  # Make it expired
        storage._store["quick-recovery-test"] = record

        # Cleanup
        removed = await storage.cleanup_expired()
        assert removed == 1

        # Can now retry
        result2 = await storage.put_new_running("quick-recovery-test", fingerprint, ttl_seconds=86400)
        assert result2.success is True


class TestRecoveryAfterCleanup:
    """Test that system recovers properly after cleanup."""

    @pytest.mark.asyncio
    async def test_normal_operation_after_cleanup(self, storage: MemoryStorageAdapter) -> None:
        """Test that normal operations work after cleaning up crashed records.

        After cleanup, the system should function normally for new requests.
        """
        fingerprint = "4" * 64
        now = datetime.utcnow()

        # Create and cleanup crashed record
        record = IdempotencyRecord(
            key="recovery-test",
            fingerprint=fingerprint,
            state=RequestState.RUNNING,
            response=None,
            created_at=now - timedelta(seconds=10),
            expires_at=now - timedelta(seconds=5),
            lease_token="crashed-token",
        )
        storage._store["recovery-test"] = record

        await storage.cleanup_expired()

        # New request should work normally
        result = await storage.put_new_running("recovery-test", fingerprint, ttl_seconds=86400)
        assert result.success is True
        assert result.lease_token is not None

        # Complete the request
        response = StoredResponse(status=200, headers={}, body_b64="e30=")
        success = await storage.complete("recovery-test", result.lease_token, response, execution_time_ms=100)
        assert success is True

        # Verify completed state
        final_record = await storage.get("recovery-test")
        assert final_record is not None
        assert final_record.state == RequestState.COMPLETED

    @pytest.mark.asyncio
    async def test_no_permanent_deadlocks(self, storage: MemoryStorageAdapter) -> None:
        """Test that cleanup prevents permanent deadlocks.

        Even if many requests crash, cleanup ensures no permanent deadlocks.
        """
        now = datetime.utcnow()
        fingerprint = "5" * 64

        # Create multiple crashed records
        for i in range(5):
            record = IdempotencyRecord(
                key=f"deadlock-test-{i}",
                fingerprint=fingerprint,
                state=RequestState.RUNNING,
                response=None,
                created_at=now - timedelta(seconds=10),
                expires_at=now - timedelta(seconds=5),
                lease_token=f"crashed-token-{i}",
            )
            storage._store[f"deadlock-test-{i}"] = record

        # Cleanup should remove all
        removed = await storage.cleanup_expired()
        assert removed == 5

        # All should be retryable
        for i in range(5):
            result = await storage.put_new_running(f"deadlock-test-{i}", fingerprint, ttl_seconds=86400)
            assert result.success is True
