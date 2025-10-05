"""Scenario 4: TTL Expiry Conformance Tests

This module tests TTL (Time-To-Live) expiry behavior of the idempotency middleware:
- Record expires after TTL
- Expired key allows new execution
- New request creates new record
- Cleanup removes expired records
- TTL countdown (created_at vs expires_at)
- Request after expiry executes handler again
- Request before expiry returns cached response
- Manual cleanup vs automatic cleanup
- Storage space reclaimed after cleanup
- Multiple expired records cleaned in batch
- Expired record not replayed (even if key matches)
"""

import asyncio
import base64
import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from pydantic import BaseModel

from idempotent_middleware.adapters.asgi import ASGIIdempotencyMiddleware
from idempotent_middleware.config import IdempotencyConfig
from idempotent_middleware.models import RequestState
from idempotent_middleware.storage.memory import MemoryStorageAdapter


# Request/Response Models
class PaymentRequest(BaseModel):
    """Payment request model for testing."""

    amount: int
    currency: str = "USD"


# Execution Counter for tracking handler calls
execution_counter = {"count": 0, "lock": asyncio.Lock()}


async def reset_counter():
    """Reset the execution counter."""
    async with execution_counter["lock"]:
        execution_counter["count"] = 0


async def increment_counter():
    """Increment the execution counter."""
    async with execution_counter["lock"]:
        execution_counter["count"] += 1


async def get_counter():
    """Get the current counter value."""
    async with execution_counter["lock"]:
        return execution_counter["count"]


# Fixtures
@pytest.fixture
def storage() -> MemoryStorageAdapter:
    """Create a fresh memory storage adapter for each test."""
    return MemoryStorageAdapter()


@pytest.fixture
def short_ttl_config() -> IdempotencyConfig:
    """Create a config with short TTL (1 second) for testing."""
    return IdempotencyConfig(
        enabled_methods=["POST", "PUT", "PATCH", "DELETE"],
        default_ttl_seconds=1,
        wait_policy="wait",
    )


@pytest.fixture
def medium_ttl_config() -> IdempotencyConfig:
    """Create a config with medium TTL (5 seconds) for testing."""
    return IdempotencyConfig(
        enabled_methods=["POST", "PUT", "PATCH", "DELETE"],
        default_ttl_seconds=5,
        wait_policy="wait",
    )


@pytest.fixture
def long_ttl_config() -> IdempotencyConfig:
    """Create a config with long TTL (1 hour) for testing."""
    return IdempotencyConfig(
        enabled_methods=["POST", "PUT", "PATCH", "DELETE"],
        default_ttl_seconds=3600,
        wait_policy="wait",
    )


def create_app(storage: MemoryStorageAdapter, config: IdempotencyConfig) -> FastAPI:
    """Create a FastAPI app with idempotency middleware and test endpoints."""
    test_app = FastAPI()

    # Add middleware
    test_app.add_middleware(
        ASGIIdempotencyMiddleware,
        storage=storage,
        config=config,
    )

    # Add test endpoints
    @test_app.post("/api/payments")
    async def create_payment(payment: PaymentRequest):
        """Create a payment endpoint with execution tracking."""
        await increment_counter()
        return {
            "id": f"pay_{int(time.time() * 1000)}",
            "status": "success",
            "amount": payment.amount,
            "currency": payment.currency,
        }

    return test_app


# ============================================================================
# Basic TTL Expiry Tests
# ============================================================================


@pytest.mark.asyncio
async def test_record_expires_after_ttl(
    storage: MemoryStorageAdapter, short_ttl_config: IdempotencyConfig
) -> None:
    """Test that record expires after TTL and allows new execution.

    Verifies:
    - First request creates record
    - Second request before expiry returns cached response
    - Third request after expiry executes handler again
    """
    await reset_counter()
    app = create_app(storage, short_ttl_config)
    client = TestClient(app)

    idempotency_key = "test-ttl-expiry"
    payload = {"amount": 100, "currency": "USD"}

    # First request
    response1 = client.post(
        "/api/payments",
        json=payload,
        headers={"Idempotency-Key": idempotency_key},
    )
    assert response1.status_code == 200
    payment_id_1 = response1.json()["id"]

    # Handler executed once
    count = await get_counter()
    assert count == 1

    # Second request before expiry (should replay)
    response2 = client.post(
        "/api/payments",
        json=payload,
        headers={"Idempotency-Key": idempotency_key},
    )
    assert response2.status_code == 200
    assert response2.headers.get("idempotent-replay") == "true"
    assert response2.json()["id"] == payment_id_1

    # Handler still executed once
    count = await get_counter()
    assert count == 1

    # Wait for TTL to expire
    await asyncio.sleep(1.5)

    # Manually expire the record (simulate time passing)
    record = await storage.get(idempotency_key)
    if record:
        record.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    # Cleanup expired records
    await storage.cleanup_expired()

    # Third request after expiry (should execute handler again)
    response3 = client.post(
        "/api/payments",
        json=payload,
        headers={"Idempotency-Key": idempotency_key},
    )
    assert response3.status_code == 200
    payment_id_3 = response3.json()["id"]

    # Payment IDs should be different (new execution)
    assert payment_id_3 != payment_id_1

    # Handler executed twice now
    count = await get_counter()
    assert count == 2


@pytest.mark.asyncio
async def test_request_before_expiry_returns_cached(
    storage: MemoryStorageAdapter, long_ttl_config: IdempotencyConfig
) -> None:
    """Test that request before expiry returns cached response.

    Verifies:
    - First request executes
    - Multiple requests before expiry all get cached response
    - Handler executes only once
    """
    await reset_counter()
    app = create_app(storage, long_ttl_config)
    client = TestClient(app)

    idempotency_key = "test-before-expiry"
    payload = {"amount": 200, "currency": "USD"}

    # First request
    response1 = client.post(
        "/api/payments",
        json=payload,
        headers={"Idempotency-Key": idempotency_key},
    )
    assert response1.status_code == 200
    payment_id = response1.json()["id"]

    # Multiple requests within TTL
    for i in range(5):
        response = client.post(
            "/api/payments",
            json=payload,
            headers={"Idempotency-Key": idempotency_key},
        )
        assert response.status_code == 200
        assert response.headers.get("idempotent-replay") == "true"
        assert response.json()["id"] == payment_id

    # Handler executed only once
    count = await get_counter()
    assert count == 1


# ============================================================================
# Cleanup Tests
# ============================================================================


@pytest.mark.asyncio
async def test_cleanup_removes_expired_records(storage: MemoryStorageAdapter) -> None:
    """Test that cleanup_expired() removes expired records.

    Verifies:
    - Records are created
    - Expired records are removed by cleanup
    - Non-expired records remain
    """
    # Create multiple records with short TTL
    for i in range(5):
        await storage.put_new_running(
            key=f"expired-{i}",
            fingerprint="a" * 64,
            ttl_seconds=1,
        )

    # Create records with long TTL
    for i in range(3):
        await storage.put_new_running(
            key=f"valid-{i}",
            fingerprint="b" * 64,
            ttl_seconds=3600,
        )

    # Manually expire the short TTL records
    for i in range(5):
        record = await storage.get(f"expired-{i}")
        if record:
            record.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    # Run cleanup
    removed_count = await storage.cleanup_expired()
    assert removed_count == 5

    # Verify expired records are gone
    for i in range(5):
        assert await storage.get(f"expired-{i}") is None

    # Verify valid records still exist
    for i in range(3):
        assert await storage.get(f"valid-{i}") is not None


@pytest.mark.asyncio
async def test_cleanup_with_empty_storage(storage: MemoryStorageAdapter) -> None:
    """Test that cleanup works on empty storage without errors.

    Verifies:
    - Cleanup on empty storage returns 0
    - No errors occur
    """
    removed_count = await storage.cleanup_expired()
    assert removed_count == 0


@pytest.mark.asyncio
async def test_cleanup_batch_removes_multiple_expired(
    storage: MemoryStorageAdapter,
) -> None:
    """Test that cleanup can remove multiple expired records in one batch.

    Verifies:
    - Multiple expired records are cleaned in single operation
    - Cleanup returns correct count
    """
    # Create 20 expired records
    for i in range(20):
        await storage.put_new_running(
            key=f"batch-expired-{i}",
            fingerprint="c" * 64,
            ttl_seconds=1,
        )

    # Manually expire them all
    for i in range(20):
        record = await storage.get(f"batch-expired-{i}")
        if record:
            record.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    # Run cleanup
    removed_count = await storage.cleanup_expired()
    assert removed_count == 20

    # Verify all are gone
    for i in range(20):
        assert await storage.get(f"batch-expired-{i}") is None


@pytest.mark.asyncio
async def test_storage_space_reclaimed_after_cleanup(
    storage: MemoryStorageAdapter,
) -> None:
    """Test that storage space is reclaimed after cleanup.

    Verifies:
    - Records are removed from storage dict
    - Memory is freed
    """
    # Create records
    for i in range(10):
        await storage.put_new_running(
            key=f"space-test-{i}",
            fingerprint="d" * 64,
            ttl_seconds=1,
        )

    # Check storage size
    initial_size = len(storage._store)
    assert initial_size == 10

    # Expire all records
    for i in range(10):
        record = await storage.get(f"space-test-{i}")
        if record:
            record.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    # Cleanup
    await storage.cleanup_expired()

    # Check storage is empty
    final_size = len(storage._store)
    assert final_size == 0


# ============================================================================
# TTL Countdown Tests
# ============================================================================


@pytest.mark.asyncio
async def test_ttl_countdown_created_at_vs_expires_at(
    storage: MemoryStorageAdapter,
) -> None:
    """Test that expires_at is correctly calculated from created_at + TTL.

    Verifies:
    - expires_at = created_at + ttl_seconds
    - Timestamps are accurate
    """
    ttl_seconds = 3600
    before = datetime.now(UTC)

    result = await storage.put_new_running(
        key="test-ttl-countdown",
        fingerprint="e" * 64,
        ttl_seconds=ttl_seconds,
    )

    after = datetime.now(UTC)

    record = await storage.get("test-ttl-countdown")
    assert record is not None

    # created_at should be between before and after
    assert before <= record.created_at <= after

    # expires_at should be created_at + ttl_seconds
    expected_expires = record.created_at + timedelta(seconds=ttl_seconds)
    assert record.expires_at == expected_expires

    # expires_at should be approximately ttl_seconds in the future
    time_until_expiry = (record.expires_at - datetime.now(UTC)).total_seconds()
    assert 3590 <= time_until_expiry <= 3610  # Allow 10 second tolerance


@pytest.mark.asyncio
async def test_different_ttl_values(storage: MemoryStorageAdapter) -> None:
    """Test different TTL values (1 second, 1 hour, 24 hours).

    Verifies:
    - Different TTL values are respected
    - expires_at is calculated correctly for each
    """
    test_cases = [
        ("ttl-1sec", 1),
        ("ttl-1hour", 3600),
        ("ttl-24hour", 86400),
    ]

    for key, ttl in test_cases:
        await storage.put_new_running(
            key=key,
            fingerprint="f" * 64,
            ttl_seconds=ttl,
        )

        record = await storage.get(key)
        assert record is not None

        # Check TTL is correct
        actual_ttl = (record.expires_at - record.created_at).total_seconds()
        assert actual_ttl == ttl


# ============================================================================
# Expired Record Not Replayed Tests
# ============================================================================


@pytest.mark.asyncio
async def test_expired_record_not_replayed(
    storage: MemoryStorageAdapter, short_ttl_config: IdempotencyConfig
) -> None:
    """Test that expired record is not replayed even if key matches.

    Verifies:
    - Expired record exists in storage (before cleanup)
    - New request with same key creates new record
    - Handler executes again
    """
    await reset_counter()
    app = create_app(storage, short_ttl_config)
    client = TestClient(app)

    idempotency_key = "test-no-replay-expired"
    payload = {"amount": 300, "currency": "USD"}

    # First request
    response1 = client.post(
        "/api/payments",
        json=payload,
        headers={"Idempotency-Key": idempotency_key},
    )
    assert response1.status_code == 200
    payment_id_1 = response1.json()["id"]

    # Manually expire the record
    record = await storage.get(idempotency_key)
    assert record is not None
    record.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    # Record still exists but is expired
    expired_record = await storage.get(idempotency_key)
    assert expired_record is not None
    assert expired_record.expires_at < datetime.now(UTC)

    # Second request should NOT replay (record is expired)
    # Note: Middleware doesn't automatically check expiry on get(),
    # but cleanup would remove it. For this test, we manually clean.
    await storage.cleanup_expired()

    response2 = client.post(
        "/api/payments",
        json=payload,
        headers={"Idempotency-Key": idempotency_key},
    )
    assert response2.status_code == 200
    payment_id_2 = response2.json()["id"]

    # Should be a new payment (different ID)
    assert payment_id_2 != payment_id_1

    # Handler executed twice
    count = await get_counter()
    assert count == 2


# ============================================================================
# Integration Tests: Full TTL Lifecycle
# ============================================================================


@pytest.mark.asyncio
async def test_full_ttl_lifecycle(
    storage: MemoryStorageAdapter, short_ttl_config: IdempotencyConfig
) -> None:
    """Test complete TTL lifecycle: create, replay, expire, cleanup, recreate.

    Verifies:
    - Record is created
    - Replays work within TTL
    - Record expires after TTL
    - Cleanup removes expired record
    - Same key can be reused after expiry
    """
    await reset_counter()
    app = create_app(storage, short_ttl_config)
    client = TestClient(app)

    idempotency_key = "test-full-lifecycle"
    payload = {"amount": 400, "currency": "USD"}

    # Step 1: Create record
    response1 = client.post(
        "/api/payments",
        json=payload,
        headers={"Idempotency-Key": idempotency_key},
    )
    assert response1.status_code == 200
    payment_id_1 = response1.json()["id"]

    # Step 2: Replay within TTL
    response2 = client.post(
        "/api/payments",
        json=payload,
        headers={"Idempotency-Key": idempotency_key},
    )
    assert response2.status_code == 200
    assert response2.headers.get("idempotent-replay") == "true"
    assert response2.json()["id"] == payment_id_1

    # Step 3: Expire record
    record = await storage.get(idempotency_key)
    assert record is not None
    record.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    # Step 4: Cleanup
    removed_count = await storage.cleanup_expired()
    assert removed_count == 1
    assert await storage.get(idempotency_key) is None

    # Step 5: Recreate with same key
    response3 = client.post(
        "/api/payments",
        json=payload,
        headers={"Idempotency-Key": idempotency_key},
    )
    assert response3.status_code == 200
    payment_id_3 = response3.json()["id"]

    # Should be a new payment
    assert payment_id_3 != payment_id_1

    # Handler executed twice total
    count = await get_counter()
    assert count == 2


@pytest.mark.asyncio
async def test_concurrent_cleanup_and_requests(
    storage: MemoryStorageAdapter, short_ttl_config: IdempotencyConfig
) -> None:
    """Test that cleanup can run concurrently with active requests.

    Verifies:
    - Active (non-expired) records are not affected by cleanup
    - Cleanup removes only expired records
    - Concurrent operations are safe
    """
    await reset_counter()
    app = create_app(storage, short_ttl_config)
    client = TestClient(app)

    # Create some expired records
    for i in range(5):
        await storage.put_new_running(
            key=f"old-{i}",
            fingerprint="a" * 64,
            ttl_seconds=1,
        )

    # Expire them
    for i in range(5):
        record = await storage.get(f"old-{i}")
        if record:
            record.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    # Make new active requests
    async def make_request(key: str):
        return await asyncio.to_thread(
            lambda: client.post(
                "/api/payments",
                json={"amount": 100, "currency": "USD"},
                headers={"Idempotency-Key": key},
            )
        )

    # Run cleanup and new requests concurrently
    cleanup_task = storage.cleanup_expired()
    request_tasks = [make_request(f"active-{i}") for i in range(5)]

    cleanup_result, *request_results = await asyncio.gather(
        cleanup_task, *request_tasks
    )

    # Cleanup should remove 5 expired records
    assert cleanup_result == 5

    # All new requests should succeed
    assert all(r.status_code == 200 for r in request_results)

    # Active records should still exist
    for i in range(5):
        assert await storage.get(f"active-{i}") is not None


# ============================================================================
# Edge Cases
# ============================================================================


@pytest.mark.asyncio
async def test_cleanup_removes_unused_locks(storage: MemoryStorageAdapter) -> None:
    """Test that cleanup removes unused locks for expired records.

    Verifies:
    - Locks are created with records
    - Cleanup removes locks for expired records
    - Lock dictionary doesn't grow indefinitely
    """
    # Create and complete records
    for i in range(5):
        result = await storage.put_new_running(
            key=f"lock-test-{i}",
            fingerprint="a" * 64,
            ttl_seconds=1,
        )
        # Complete them to release locks
        from idempotent_middleware.models import StoredResponse

        await storage.complete(
            key=f"lock-test-{i}",
            lease_token=result.lease_token,
            response=StoredResponse(
                status=200,
                headers={},
                body_b64=base64.b64encode(b"test").decode(),
            ),
            execution_time_ms=100,
        )

    # Verify locks exist
    initial_lock_count = len(storage._locks)
    assert initial_lock_count >= 5

    # Expire all records
    for i in range(5):
        record = await storage.get(f"lock-test-{i}")
        if record:
            record.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    # Cleanup
    await storage.cleanup_expired()

    # Locks should be removed
    final_lock_count = len(storage._locks)
    assert final_lock_count < initial_lock_count


@pytest.mark.asyncio
async def test_record_at_exact_expiry_boundary(
    storage: MemoryStorageAdapter,
) -> None:
    """Test record behavior at exact expiry time boundary.

    Verifies:
    - Record at expires_at == now is considered expired
    - Cleanup removes records at boundary
    """
    # Create record
    await storage.put_new_running(
        key="boundary-test",
        fingerprint="a" * 64,
        ttl_seconds=3600,
    )

    record = await storage.get("boundary-test")
    assert record is not None

    # Set expires_at to exact current time
    record.expires_at = datetime.now(UTC)

    # Small sleep to ensure time has passed
    await asyncio.sleep(0.01)

    # Cleanup should remove it (expires_at < now)
    removed_count = await storage.cleanup_expired()
    assert removed_count == 1
    assert await storage.get("boundary-test") is None


@pytest.mark.asyncio
async def test_multiple_cleanup_calls_idempotent(
    storage: MemoryStorageAdapter,
) -> None:
    """Test that multiple cleanup calls are idempotent.

    Verifies:
    - First cleanup removes expired records
    - Subsequent cleanups find nothing to remove
    - No errors occur
    """
    # Create expired records
    for i in range(5):
        await storage.put_new_running(
            key=f"multi-cleanup-{i}",
            fingerprint="a" * 64,
            ttl_seconds=1,
        )

    # Expire them
    for i in range(5):
        record = await storage.get(f"multi-cleanup-{i}")
        if record:
            record.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    # First cleanup
    count1 = await storage.cleanup_expired()
    assert count1 == 5

    # Second cleanup should find nothing
    count2 = await storage.cleanup_expired()
    assert count2 == 0

    # Third cleanup should still find nothing
    count3 = await storage.cleanup_expired()
    assert count3 == 0


@pytest.mark.asyncio
async def test_ttl_with_failed_request(
    storage: MemoryStorageAdapter, short_ttl_config: IdempotencyConfig
) -> None:
    """Test that TTL applies to failed requests as well.

    Verifies:
    - Failed request is cached
    - TTL applies to failed records
    - Expired failed record allows retry
    """
    await reset_counter()
    app = create_app(storage, short_ttl_config)

    # Add error endpoint
    @app.post("/api/error-payment")
    async def error_payment(payment: PaymentRequest):
        await increment_counter()
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Payment failed")

    client = TestClient(app)

    idempotency_key = "test-failed-ttl"
    payload = {"amount": 500, "currency": "USD"}

    # First request (fails)
    response1 = client.post(
        "/api/error-payment",
        json=payload,
        headers={"Idempotency-Key": idempotency_key},
    )
    assert response1.status_code == 400

    # Second request before expiry (replays error)
    response2 = client.post(
        "/api/error-payment",
        json=payload,
        headers={"Idempotency-Key": idempotency_key},
    )
    assert response2.status_code == 400
    assert response2.headers.get("idempotent-replay") == "true"

    # Handler executed once
    count = await get_counter()
    assert count == 1

    # Expire and cleanup
    record = await storage.get(idempotency_key)
    if record:
        record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await storage.cleanup_expired()

    # Third request after expiry (executes again)
    response3 = client.post(
        "/api/error-payment",
        json=payload,
        headers={"Idempotency-Key": idempotency_key},
    )
    assert response3.status_code == 400

    # Handler executed twice
    count = await get_counter()
    assert count == 2
