"""Property-based and concurrency stress tests for MemoryStorageAdapter.

This test suite uses Hypothesis for property-based testing and includes
comprehensive concurrency and race condition tests.
"""

import asyncio
import base64
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from idempotent_middleware.models import RequestState, StoredResponse
from idempotent_middleware.storage.memory import MemoryStorageAdapter

# Strategies
key_strategy = st.text(min_size=1, max_size=255)
fingerprint_strategy = st.text(alphabet="0123456789abcdef", min_size=64, max_size=64)
ttl_strategy = st.integers(min_value=1, max_value=604800)
trace_id_strategy = st.one_of(st.none(), st.text(min_size=1, max_size=100))
status_code_strategy = st.integers(min_value=100, max_value=599)
exec_time_strategy = st.integers(min_value=0, max_value=10000)


@st.composite
def stored_response_strategy(draw):
    """Generate a random StoredResponse."""
    body = draw(st.binary(min_size=0, max_size=1000))
    return StoredResponse(
        status=draw(status_code_strategy),
        headers=draw(
            st.dictionaries(
                st.text(min_size=1, max_size=20),
                st.text(min_size=0, max_size=100),
                min_size=0,
                max_size=10,
            )
        ),
        body_b64=base64.b64encode(body).decode("ascii"),
    )


class TestMemoryStorageProperties:
    """Property-based tests for MemoryStorageAdapter."""

    @pytest.mark.asyncio
    @given(key=key_strategy)
    async def test_get_nonexistent_always_returns_none(self, key: str) -> None:
        """Getting a nonexistent key should always return None."""
        adapter = MemoryStorageAdapter()
        result = await adapter.get(key)
        assert result is None

    @pytest.mark.asyncio
    @given(
        key=key_strategy,
        fingerprint=fingerprint_strategy,
        ttl=ttl_strategy,
        trace_id=trace_id_strategy,
    )
    async def test_put_new_running_creates_record(
        self,
        key: str,
        fingerprint: str,
        ttl: int,
        trace_id: str | None,
    ) -> None:
        """put_new_running should always create a record."""
        adapter = MemoryStorageAdapter()

        result = await adapter.put_new_running(key, fingerprint, ttl, trace_id)

        assert result.success is True
        assert result.lease_token is not None
        assert result.existing_record is None

        # Verify record exists
        record = await adapter.get(key)
        assert record is not None
        assert record.key == key
        assert record.fingerprint == fingerprint
        assert record.state == RequestState.RUNNING
        assert record.trace_id == trace_id

    @pytest.mark.asyncio
    @given(
        key=key_strategy,
        fingerprint=fingerprint_strategy,
        ttl=ttl_strategy,
    )
    async def test_duplicate_put_new_running_fails(
        self,
        key: str,
        fingerprint: str,
        ttl: int,
    ) -> None:
        """Second put_new_running with same key should fail."""
        adapter = MemoryStorageAdapter()

        # First call succeeds
        result1 = await adapter.put_new_running(key, fingerprint, ttl)
        assert result1.success is True

        # Second call fails
        result2 = await adapter.put_new_running(key, fingerprint, ttl)
        assert result2.success is False
        assert result2.existing_record is not None
        assert result2.existing_record.key == key

    @pytest.mark.asyncio
    @given(
        key=key_strategy,
        fingerprint=fingerprint_strategy,
        ttl=ttl_strategy,
        response=stored_response_strategy(),
        exec_time=exec_time_strategy,
    )
    async def test_complete_with_valid_token_succeeds(
        self,
        key: str,
        fingerprint: str,
        ttl: int,
        response: StoredResponse,
        exec_time: int,
    ) -> None:
        """Completing with correct lease token should succeed."""
        adapter = MemoryStorageAdapter()

        # Create record
        result = await adapter.put_new_running(key, fingerprint, ttl)
        assert result.success is True
        lease_token = result.lease_token

        # Complete it
        success = await adapter.complete(key, lease_token, response, exec_time)  # type: ignore[arg-type]
        assert success is True

        # Verify record updated
        record = await adapter.get(key)
        assert record is not None
        assert record.state == RequestState.COMPLETED
        assert record.response == response
        assert record.execution_time_ms == exec_time

    @pytest.mark.asyncio
    @given(
        key=key_strategy,
        fingerprint=fingerprint_strategy,
        ttl=ttl_strategy,
        response=stored_response_strategy(),
    )
    async def test_complete_with_invalid_token_fails(
        self,
        key: str,
        fingerprint: str,
        ttl: int,
        response: StoredResponse,
    ) -> None:
        """Completing with wrong lease token should fail."""
        adapter = MemoryStorageAdapter()

        # Create record
        result = await adapter.put_new_running(key, fingerprint, ttl)
        assert result.success is True

        # Try to complete with different token
        wrong_token = str(uuid4())
        success = await adapter.complete(key, wrong_token, response, 100)
        assert success is False

        # Record should still be RUNNING
        record = await adapter.get(key)
        assert record is not None
        assert record.state == RequestState.RUNNING

    @pytest.mark.asyncio
    @given(
        key=key_strategy,
        fingerprint=fingerprint_strategy,
        ttl=ttl_strategy,
        response=stored_response_strategy(),
        exec_time=exec_time_strategy,
    )
    async def test_fail_with_valid_token_succeeds(
        self,
        key: str,
        fingerprint: str,
        ttl: int,
        response: StoredResponse,
        exec_time: int,
    ) -> None:
        """Failing with correct lease token should succeed."""
        adapter = MemoryStorageAdapter()

        # Create record
        result = await adapter.put_new_running(key, fingerprint, ttl)
        assert result.success is True
        lease_token = result.lease_token

        # Fail it
        success = await adapter.fail(key, lease_token, response, exec_time)  # type: ignore[arg-type]
        assert success is True

        # Verify record updated
        record = await adapter.get(key)
        assert record is not None
        assert record.state == RequestState.FAILED
        assert record.response == response
        assert record.execution_time_ms == exec_time


class TestMemoryStorageConcurrency:
    """Concurrency and race condition tests for MemoryStorageAdapter."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    @settings(deadline=5000)
    @given(
        key=key_strategy,
        fingerprint=fingerprint_strategy,
        num_concurrent=st.integers(min_value=2, max_value=20),
    )
    async def test_concurrent_put_only_one_succeeds(
        self,
        key: str,
        fingerprint: str,
        num_concurrent: int,
    ) -> None:
        """Concurrent put_new_running calls should only let one succeed."""
        adapter = MemoryStorageAdapter()

        # Launch concurrent attempts
        tasks = [adapter.put_new_running(key, fingerprint, 3600) for _ in range(num_concurrent)]

        results = await asyncio.gather(*tasks)

        # Exactly one should succeed
        successes = [r for r in results if r.success]
        failures = [r for r in results if not r.success]

        assert len(successes) == 1
        assert len(failures) == num_concurrent - 1

        # All failures should reference the same record
        successful_token = successes[0].lease_token
        for failure in failures:
            assert failure.existing_record is not None
            assert failure.existing_record.lease_token == successful_token

    @pytest.mark.asyncio
    @pytest.mark.slow
    @settings(deadline=5000)
    @given(
        num_keys=st.integers(min_value=2, max_value=20),
        fingerprint=fingerprint_strategy,
    )
    async def test_concurrent_put_different_keys_all_succeed(
        self,
        num_keys: int,
        fingerprint: str,
    ) -> None:
        """Concurrent put_new_running on different keys should all succeed."""
        adapter = MemoryStorageAdapter()

        # Launch concurrent attempts with different keys
        tasks = [adapter.put_new_running(f"key-{i}", fingerprint, 3600) for i in range(num_keys)]

        results = await asyncio.gather(*tasks)

        # All should succeed
        assert all(r.success for r in results)

        # All should have unique lease tokens
        tokens = {r.lease_token for r in results}
        assert len(tokens) == num_keys

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_concurrent_complete_with_stale_tokens(self) -> None:
        """Multiple complete attempts should only let the valid token succeed."""
        adapter = MemoryStorageAdapter()

        # Create record
        result = await adapter.put_new_running("test-key", "a" * 64, 3600)
        valid_token = result.lease_token

        # Generate stale tokens
        stale_tokens = [str(uuid4()) for _ in range(5)]

        # Create test response
        response = StoredResponse(
            status=200,
            headers={},
            body_b64=base64.b64encode(b"test").decode("ascii"),
        )

        # Try to complete with all tokens concurrently
        all_tokens = [valid_token] + stale_tokens  # type: ignore[list-item]
        tasks = [adapter.complete("test-key", token, response, 100) for token in all_tokens]

        results = await asyncio.gather(*tasks)

        # Only one should succeed (the valid token)
        successes = [r for r in results if r]
        assert len(successes) == 1

    @pytest.mark.asyncio
    @pytest.mark.slow
    @settings(deadline=10000)
    @given(
        num_operations=st.integers(min_value=10, max_value=50),
        fingerprint=fingerprint_strategy,
    )
    async def test_mixed_concurrent_operations(
        self,
        num_operations: int,
        fingerprint: str,
    ) -> None:
        """Mixed concurrent operations should maintain consistency."""
        adapter = MemoryStorageAdapter()

        async def random_operation(i: int) -> str:
            """Perform a random operation."""
            key = f"key-{i % 5}"  # Use 5 different keys

            # Try to create
            result = await adapter.put_new_running(key, fingerprint, 3600)

            if result.success:
                # We got the lease, complete or fail randomly
                response = StoredResponse(
                    status=200,
                    headers={},
                    body_b64=base64.b64encode(f"result-{i}".encode()).decode("ascii"),
                )

                if i % 2 == 0:
                    await adapter.complete(key, result.lease_token, response, 100)  # type: ignore[arg-type]
                    return f"complete-{key}"
                else:
                    await adapter.fail(key, result.lease_token, response, 100)  # type: ignore[arg-type]
                    return f"fail-{key}"
            else:
                # Someone else has it, just try to get
                await adapter.get(key)
                return f"get-{key}"

        # Run all operations concurrently
        tasks = [random_operation(i) for i in range(num_operations)]
        await asyncio.gather(*tasks)

        # Verify all records are in valid state
        for i in range(5):
            key = f"key-{i}"
            record = await adapter.get(key)
            if record is not None:
                # Should be in COMPLETED or FAILED state (not RUNNING)
                assert record.state in {RequestState.COMPLETED, RequestState.FAILED}

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_cleanup_during_concurrent_operations(self) -> None:
        """Cleanup should work safely during concurrent operations."""
        adapter = MemoryStorageAdapter()

        # Create some expired records
        for i in range(5):
            result = await adapter.put_new_running(f"expired-{i}", "a" * 64, 1)
            response = StoredResponse(
                status=200,
                headers={},
                body_b64=base64.b64encode(b"test").decode("ascii"),
            )
            await adapter.complete(f"expired-{i}", result.lease_token, response, 100)  # type: ignore[arg-type]

            # Manually set expiry to past
            record = await adapter.get(f"expired-{i}")
            if record:
                record.expires_at = datetime.now(UTC) - timedelta(hours=1)

        # Create some active records
        active_tasks = [adapter.put_new_running(f"active-{i}", "b" * 64, 3600) for i in range(5)]
        await asyncio.gather(*active_tasks)

        # Run cleanup concurrently with more operations
        async def cleanup_loop() -> int:
            total = 0
            for _ in range(3):
                count = await adapter.cleanup_expired()
                total += count
                await asyncio.sleep(0.01)
            return total

        async def create_more() -> None:
            for i in range(5):
                await adapter.put_new_running(f"new-{i}", "c" * 64, 3600)
                await asyncio.sleep(0.01)

        cleanup_task = asyncio.create_task(cleanup_loop())
        create_task = asyncio.create_task(create_more())

        await asyncio.gather(cleanup_task, create_task)

        # Verify active records still exist
        for i in range(5):
            record = await adapter.get(f"active-{i}")
            assert record is not None


class TestMemoryStorageStressTests:
    """Stress tests for MemoryStorageAdapter."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_high_volume_sequential_operations(self) -> None:
        """Test handling large number of sequential operations."""
        adapter = MemoryStorageAdapter()
        num_operations = 1000

        response = StoredResponse(
            status=200,
            headers={},
            body_b64=base64.b64encode(b"test").decode("ascii"),
        )

        for i in range(num_operations):
            key = f"key-{i}"
            result = await adapter.put_new_running(key, "a" * 64, 3600)
            assert result.success is True
            await adapter.complete(key, result.lease_token, response, 100)  # type: ignore[arg-type]

        # Verify all records exist
        for i in range(num_operations):
            record = await adapter.get(f"key-{i}")
            assert record is not None
            assert record.state == RequestState.COMPLETED

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_high_volume_concurrent_operations(self) -> None:
        """Test handling large number of concurrent operations."""
        adapter = MemoryStorageAdapter()
        num_operations = 100

        response = StoredResponse(
            status=200,
            headers={},
            body_b64=base64.b64encode(b"test").decode("ascii"),
        )

        async def create_and_complete(i: int) -> None:
            key = f"key-{i}"
            result = await adapter.put_new_running(key, "a" * 64, 3600)
            if result.success:
                await adapter.complete(key, result.lease_token, response, 100)  # type: ignore[arg-type]

        tasks = [create_and_complete(i) for i in range(num_operations)]
        await asyncio.gather(*tasks)

        # Count completed records
        completed = 0
        for i in range(num_operations):
            record = await adapter.get(f"key-{i}")
            if record and record.state == RequestState.COMPLETED:
                completed += 1

        # All should be completed
        assert completed == num_operations

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_cleanup_performance_with_many_records(self) -> None:
        """Test cleanup performance with many records."""
        adapter = MemoryStorageAdapter()
        num_records = 1000

        # Create many records
        response = StoredResponse(
            status=200,
            headers={},
            body_b64=base64.b64encode(b"test").decode("ascii"),
        )

        for i in range(num_records):
            result = await adapter.put_new_running(f"key-{i}", "a" * 64, 1)
            await adapter.complete(f"key-{i}", result.lease_token, response, 100)  # type: ignore[arg-type]

            # Make half of them expired
            if i % 2 == 0:
                record = await adapter.get(f"key-{i}")
                if record:
                    record.expires_at = datetime.now(UTC) - timedelta(hours=1)

        # Cleanup should handle many records efficiently
        count = await adapter.cleanup_expired()

        # Should have removed roughly half
        assert count >= num_records // 2 - 10
        assert count <= num_records // 2 + 10

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_lock_cleanup_under_load(self) -> None:
        """Test that locks are cleaned up properly under load."""
        adapter = MemoryStorageAdapter()

        # Create and complete many operations
        for i in range(100):
            key = f"key-{i}"
            result = await adapter.put_new_running(key, "a" * 64, 1)
            response = StoredResponse(
                status=200,
                headers={},
                body_b64=base64.b64encode(b"test").decode("ascii"),
            )
            await adapter.complete(key, result.lease_token, response, 100)  # type: ignore[arg-type]

            # Manually expire
            record = await adapter.get(key)
            if record:
                record.expires_at = datetime.now(UTC) - timedelta(hours=1)

        # Cleanup should remove both records and locks
        count = await adapter.cleanup_expired()
        assert count > 0

        # Locks should be cleaned up (internal state check)
        # Only held locks should remain
        unheld_locks = sum(1 for lock in adapter._locks.values() if not lock.locked())

        # Should have cleaned up most locks
        assert unheld_locks < 10
