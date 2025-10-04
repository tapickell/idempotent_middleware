"""Scenario 3: Concurrent Execution Conformance Tests

This module tests concurrent execution behavior of the idempotency middleware:
- Multiple simultaneous requests with same idempotency key
- Only ONE handler execution occurs (race condition handling)
- All requests get the same response
- Test with asyncio.gather for concurrency
- Test with both "wait" and "no-wait" policies
- Verify lock acquisition/release
- Test race conditions at NEW -> RUNNING transition
- Test concurrent requests to different keys (should not block)
- Test handler failures (all see same error)
- Test mixed arrival times (during RUNNING, after COMPLETED)
"""

import asyncio
import base64
import json
import time
from typing import Any

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from pydantic import BaseModel

from idempotent_middleware.adapters.asgi import ASGIIdempotencyMiddleware
from idempotent_middleware.config import IdempotencyConfig
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
def wait_config() -> IdempotencyConfig:
    """Create a config with wait policy."""
    return IdempotencyConfig(
        enabled_methods=["POST", "PUT", "PATCH", "DELETE"],
        default_ttl_seconds=3600,
        wait_policy="wait",
        execution_timeout_seconds=30,
    )


@pytest.fixture
def no_wait_config() -> IdempotencyConfig:
    """Create a config with no-wait policy."""
    return IdempotencyConfig(
        enabled_methods=["POST", "PUT", "PATCH", "DELETE"],
        default_ttl_seconds=3600,
        wait_policy="no-wait",
        execution_timeout_seconds=30,
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
        # Simulate processing time
        await asyncio.sleep(0.2)
        return {
            "id": "pay_12345",
            "status": "success",
            "amount": payment.amount,
            "currency": payment.currency,
        }

    @test_app.post("/api/fast-payment")
    async def fast_payment(payment: PaymentRequest):
        """Fast payment endpoint without sleep."""
        await increment_counter()
        return {
            "id": "pay_fast",
            "status": "success",
            "amount": payment.amount,
        }

    @test_app.post("/api/slow-payment")
    async def slow_payment(payment: PaymentRequest):
        """Slow payment endpoint."""
        await increment_counter()
        await asyncio.sleep(1.0)
        return {
            "id": "pay_slow",
            "status": "success",
            "amount": payment.amount,
        }

    @test_app.post("/api/error-payment")
    async def error_payment(payment: PaymentRequest):
        """Payment endpoint that always fails."""
        await increment_counter()
        await asyncio.sleep(0.2)
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Payment processing failed")

    return test_app


# ============================================================================
# Basic Concurrent Request Tests (Wait Policy)
# ============================================================================


@pytest.mark.asyncio
async def test_two_concurrent_requests_same_key_wait_policy(
    storage: MemoryStorageAdapter, wait_config: IdempotencyConfig
) -> None:
    """Test that 2 concurrent requests with same key execute handler only once (wait policy).

    Verifies:
    - Both requests succeed
    - Handler executes exactly once
    - Both responses are identical
    - Second request waits for first to complete
    """
    await reset_counter()
    app = create_app(storage, wait_config)
    client = TestClient(app)

    idempotency_key = "test-concurrent-2"
    payload = {"amount": 100, "currency": "USD"}

    # Make 2 concurrent requests
    async def make_request():
        return client.post(
            "/api/payments",
            json=payload,
            headers={"Idempotency-Key": idempotency_key},
        )

    results = await asyncio.gather(
        asyncio.to_thread(make_request),
        asyncio.to_thread(make_request),
    )

    # Both requests should succeed
    assert results[0].status_code == 200
    assert results[1].status_code == 200

    # Both should have same response
    response1 = results[0].json()
    response2 = results[1].json()
    assert response1 == response2

    # Handler should execute exactly once
    count = await get_counter()
    assert count == 1

    # One should be original, one should be replay
    replay_headers_count = sum(
        1 for r in results if r.headers.get("idempotent-replayed") == "true"
    )
    assert replay_headers_count == 1


@pytest.mark.asyncio
async def test_ten_concurrent_requests_same_key_wait_policy(
    storage: MemoryStorageAdapter, wait_config: IdempotencyConfig
) -> None:
    """Test that 10 concurrent requests with same key execute handler only once.

    Verifies:
    - All 10 requests succeed
    - Handler executes exactly once
    - All responses are identical
    - Race condition is properly handled
    """
    await reset_counter()
    app = create_app(storage, wait_config)
    client = TestClient(app)

    idempotency_key = "test-concurrent-10"
    payload = {"amount": 250, "currency": "USD"}

    # Make 10 concurrent requests
    async def make_request():
        return client.post(
            "/api/payments",
            json=payload,
            headers={"Idempotency-Key": idempotency_key},
        )

    tasks = [asyncio.to_thread(make_request) for _ in range(10)]
    results = await asyncio.gather(*tasks)

    # All requests should succeed
    assert all(r.status_code == 200 for r in results)

    # All should have identical response
    first_response = results[0].json()
    assert all(r.json() == first_response for r in results)

    # Handler should execute exactly once
    count = await get_counter()
    assert count == 1

    # Exactly 9 should be replays, 1 should be original
    replay_count = sum(
        1 for r in results if r.headers.get("idempotent-replayed") == "true"
    )
    assert replay_count == 9


@pytest.mark.asyncio
async def test_hundred_concurrent_requests_same_key_wait_policy(
    storage: MemoryStorageAdapter, wait_config: IdempotencyConfig
) -> None:
    """Test that 100 concurrent requests with same key execute handler only once (stress test).

    Verifies:
    - All 100 requests succeed
    - Handler executes exactly once
    - All responses are identical
    - System handles heavy concurrency load
    """
    await reset_counter()
    app = create_app(storage, wait_config)
    client = TestClient(app)

    idempotency_key = "test-concurrent-100"
    payload = {"amount": 500, "currency": "USD"}

    # Make 100 concurrent requests
    async def make_request():
        return client.post(
            "/api/fast-payment",
            json=payload,
            headers={"Idempotency-Key": idempotency_key},
        )

    tasks = [asyncio.to_thread(make_request) for _ in range(100)]
    results = await asyncio.gather(*tasks)

    # All requests should succeed
    assert all(r.status_code == 200 for r in results)

    # All should have identical response
    first_response = results[0].json()
    assert all(r.json() == first_response for r in results)

    # Handler should execute exactly once
    count = await get_counter()
    assert count == 1

    # Exactly 99 should be replays
    replay_count = sum(
        1 for r in results if r.headers.get("idempotent-replayed") == "true"
    )
    assert replay_count == 99


# ============================================================================
# No-Wait Policy Tests
# ============================================================================


@pytest.mark.asyncio
async def test_two_concurrent_requests_same_key_no_wait_policy(
    storage: MemoryStorageAdapter, no_wait_config: IdempotencyConfig
) -> None:
    """Test that 2 concurrent requests with same key and no-wait policy return 409.

    Verifies:
    - First request succeeds
    - Second request gets 409 Conflict
    - Handler executes exactly once
    - 409 response includes retry-after header
    """
    await reset_counter()
    app = create_app(storage, no_wait_config)
    client = TestClient(app)

    idempotency_key = "test-nowait-2"
    payload = {"amount": 100, "currency": "USD"}

    # Make 2 concurrent requests
    async def make_request():
        return client.post(
            "/api/payments",
            json=payload,
            headers={"Idempotency-Key": idempotency_key},
        )

    results = await asyncio.gather(
        asyncio.to_thread(make_request),
        asyncio.to_thread(make_request),
    )

    # One should succeed (200), one should get 409
    status_codes = sorted([r.status_code for r in results])
    assert status_codes == [200, 409]

    # Handler should execute exactly once
    count = await get_counter()
    assert count == 1

    # The 409 response should have retry-after header
    conflict_response = next(r for r in results if r.status_code == 409)
    assert "retry-after" in conflict_response.headers


@pytest.mark.asyncio
async def test_ten_concurrent_requests_same_key_no_wait_policy(
    storage: MemoryStorageAdapter, no_wait_config: IdempotencyConfig
) -> None:
    """Test that 10 concurrent requests with no-wait policy return mix of 200 and 409.

    Verifies:
    - Exactly one request succeeds (200)
    - Other requests get 409 Conflict
    - Handler executes exactly once
    """
    await reset_counter()
    app = create_app(storage, no_wait_config)
    client = TestClient(app)

    idempotency_key = "test-nowait-10"
    payload = {"amount": 250, "currency": "USD"}

    # Make 10 concurrent requests
    async def make_request():
        return client.post(
            "/api/payments",
            json=payload,
            headers={"Idempotency-Key": idempotency_key},
        )

    tasks = [asyncio.to_thread(make_request) for _ in range(10)]
    results = await asyncio.gather(*tasks)

    # Count status codes
    success_count = sum(1 for r in results if r.status_code == 200)
    conflict_count = sum(1 for r in results if r.status_code == 409)

    # Exactly 1 should succeed, rest should get 409
    assert success_count == 1
    assert conflict_count == 9

    # Handler should execute exactly once
    count = await get_counter()
    assert count == 1


@pytest.mark.asyncio
async def test_no_wait_second_request_after_completion(
    storage: MemoryStorageAdapter, no_wait_config: IdempotencyConfig
) -> None:
    """Test that no-wait policy still replays after completion.

    Verifies:
    - First request completes successfully
    - Second request (after completion) gets replayed response
    - No 409 conflict after completion
    """
    await reset_counter()
    app = create_app(storage, no_wait_config)
    client = TestClient(app)

    idempotency_key = "test-nowait-replay"
    payload = {"amount": 100, "currency": "USD"}

    # First request
    response1 = client.post(
        "/api/fast-payment",
        json=payload,
        headers={"Idempotency-Key": idempotency_key},
    )
    assert response1.status_code == 200

    # Second request after completion
    response2 = client.post(
        "/api/fast-payment",
        json=payload,
        headers={"Idempotency-Key": idempotency_key},
    )
    assert response2.status_code == 200
    assert response2.headers.get("idempotent-replayed") == "true"
    assert response1.json() == response2.json()

    # Handler should execute exactly once
    count = await get_counter()
    assert count == 1


# ============================================================================
# Different Keys Tests (Should Not Block)
# ============================================================================


@pytest.mark.asyncio
async def test_concurrent_requests_different_keys_all_execute(
    storage: MemoryStorageAdapter, wait_config: IdempotencyConfig
) -> None:
    """Test that concurrent requests with different keys all execute independently.

    Verifies:
    - All requests succeed
    - Handler executes for each unique key
    - No blocking between different keys
    """
    await reset_counter()
    app = create_app(storage, wait_config)
    client = TestClient(app)

    payload = {"amount": 100, "currency": "USD"}

    # Make 10 concurrent requests with different keys
    async def make_request(key: str):
        return client.post(
            "/api/payments",
            json=payload,
            headers={"Idempotency-Key": key},
        )

    tasks = [asyncio.to_thread(make_request, f"key-{i}") for i in range(10)]
    results = await asyncio.gather(*tasks)

    # All requests should succeed
    assert all(r.status_code == 200 for r in results)

    # Handler should execute 10 times (once per key)
    count = await get_counter()
    assert count == 10

    # None should be replays
    replay_count = sum(
        1 for r in results if r.headers.get("idempotent-replayed") == "true"
    )
    assert replay_count == 0


@pytest.mark.asyncio
async def test_mixed_concurrent_same_and_different_keys(
    storage: MemoryStorageAdapter, wait_config: IdempotencyConfig
) -> None:
    """Test mixed concurrent requests: some same key, some different keys.

    Verifies:
    - Requests with same key deduplicate
    - Requests with different keys execute independently
    - No cross-contamination between keys
    """
    await reset_counter()
    app = create_app(storage, wait_config)
    client = TestClient(app)

    payload = {"amount": 100, "currency": "USD"}

    # Make 20 requests: 10 with key-A, 10 with key-B
    async def make_request(key: str):
        return client.post(
            "/api/payments",
            json=payload,
            headers={"Idempotency-Key": key},
        )

    tasks = []
    for _ in range(10):
        tasks.append(asyncio.to_thread(make_request, "key-A"))
    for _ in range(10):
        tasks.append(asyncio.to_thread(make_request, "key-B"))

    results = await asyncio.gather(*tasks)

    # All requests should succeed
    assert all(r.status_code == 200 for r in results)

    # Handler should execute exactly 2 times (once per unique key)
    count = await get_counter()
    assert count == 2

    # 18 should be replays (9 for key-A, 9 for key-B)
    replay_count = sum(
        1 for r in results if r.headers.get("idempotent-replayed") == "true"
    )
    assert replay_count == 18


# ============================================================================
# Handler Failure Tests
# ============================================================================


@pytest.mark.asyncio
async def test_concurrent_requests_handler_fails_all_see_error(
    storage: MemoryStorageAdapter, wait_config: IdempotencyConfig
) -> None:
    """Test that when handler fails, all concurrent requests see the same error.

    Verifies:
    - Handler executes once and fails
    - All requests get same error response (400)
    - Error response is cached and replayed
    """
    await reset_counter()
    app = create_app(storage, wait_config)
    client = TestClient(app)

    idempotency_key = "test-error-concurrent"
    payload = {"amount": 100, "currency": "USD"}

    # Make 5 concurrent requests to error endpoint
    async def make_request():
        return client.post(
            "/api/error-payment",
            json=payload,
            headers={"Idempotency-Key": idempotency_key},
        )

    tasks = [asyncio.to_thread(make_request) for _ in range(5)]
    results = await asyncio.gather(*tasks)

    # All requests should get 400 error
    assert all(r.status_code == 400 for r in results)

    # All should have same error response
    first_response = results[0].json()
    assert all(r.json() == first_response for r in results)

    # Handler should execute exactly once
    count = await get_counter()
    assert count == 1

    # 4 should be replays
    replay_count = sum(
        1 for r in results if r.headers.get("idempotent-replayed") == "true"
    )
    assert replay_count == 4


# ============================================================================
# Mixed Arrival Times Tests
# ============================================================================


@pytest.mark.asyncio
async def test_mixed_arrival_some_during_running_some_after_completed(
    storage: MemoryStorageAdapter, wait_config: IdempotencyConfig
) -> None:
    """Test mixed arrival: some requests during RUNNING, some after COMPLETED.

    Verifies:
    - First batch arrives while handler is running
    - Second batch arrives after completion
    - All requests get same response
    - Handler executes exactly once
    """
    await reset_counter()
    app = create_app(storage, wait_config)
    client = TestClient(app)

    idempotency_key = "test-mixed-arrival"
    payload = {"amount": 500, "currency": "USD"}

    async def make_request():
        return client.post(
            "/api/payments",
            json=payload,
            headers={"Idempotency-Key": idempotency_key},
        )

    # First batch: 5 concurrent requests
    batch1_tasks = [asyncio.to_thread(make_request) for _ in range(5)]
    batch1_results = await asyncio.gather(*batch1_tasks)

    # Wait a bit to ensure completion
    await asyncio.sleep(0.5)

    # Second batch: 5 more requests (should hit COMPLETED state)
    batch2_tasks = [asyncio.to_thread(make_request) for _ in range(5)]
    batch2_results = await asyncio.gather(*batch2_tasks)

    all_results = batch1_results + batch2_results

    # All should succeed
    assert all(r.status_code == 200 for r in all_results)

    # All should have same response
    first_response = all_results[0].json()
    assert all(r.json() == first_response for r in all_results)

    # Handler should execute exactly once
    count = await get_counter()
    assert count == 1

    # 9 should be replays
    replay_count = sum(
        1 for r in all_results if r.headers.get("idempotent-replayed") == "true"
    )
    assert replay_count == 9


@pytest.mark.asyncio
async def test_staggered_arrival_times(
    storage: MemoryStorageAdapter, wait_config: IdempotencyConfig
) -> None:
    """Test staggered arrival times with delays between requests.

    Verifies:
    - Requests arrive at different times
    - All still deduplicate correctly
    - Handler executes exactly once
    """
    await reset_counter()
    app = create_app(storage, wait_config)
    client = TestClient(app)

    idempotency_key = "test-staggered"
    payload = {"amount": 300, "currency": "USD"}

    results = []

    # First request
    result1 = await asyncio.to_thread(
        lambda: client.post(
            "/api/slow-payment",
            json=payload,
            headers={"Idempotency-Key": idempotency_key},
        )
    )
    results.append(result1)

    # Second request after 0.2s (during execution)
    await asyncio.sleep(0.2)
    result2 = await asyncio.to_thread(
        lambda: client.post(
            "/api/slow-payment",
            json=payload,
            headers={"Idempotency-Key": idempotency_key},
        )
    )
    results.append(result2)

    # Third request after another 0.5s (might be after completion)
    await asyncio.sleep(0.5)
    result3 = await asyncio.to_thread(
        lambda: client.post(
            "/api/slow-payment",
            json=payload,
            headers={"Idempotency-Key": idempotency_key},
        )
    )
    results.append(result3)

    # All should succeed
    assert all(r.status_code == 200 for r in results)

    # All should have same response
    first_response = results[0].json()
    assert all(r.json() == first_response for r in results)

    # Handler should execute exactly once
    count = await get_counter()
    assert count == 1

    # At least 2 should be replays
    replay_count = sum(
        1 for r in results if r.headers.get("idempotent-replayed") == "true"
    )
    assert replay_count >= 2


# ============================================================================
# Lock Verification Tests
# ============================================================================


@pytest.mark.asyncio
async def test_lock_released_after_completion(
    storage: MemoryStorageAdapter, wait_config: IdempotencyConfig
) -> None:
    """Test that lock is released after request completes.

    Verifies:
    - Lock is acquired during execution
    - Lock is released after completion
    - Subsequent requests can proceed without waiting
    """
    await reset_counter()
    app = create_app(storage, wait_config)
    client = TestClient(app)

    idempotency_key = "test-lock-release"
    payload = {"amount": 100, "currency": "USD"}

    # First request
    response1 = client.post(
        "/api/fast-payment",
        json=payload,
        headers={"Idempotency-Key": idempotency_key},
    )
    assert response1.status_code == 200

    # Verify lock is released (by checking storage internals)
    assert idempotency_key in storage._locks
    lock = storage._locks[idempotency_key]
    assert not lock.locked()

    # Second request should not block
    response2 = client.post(
        "/api/fast-payment",
        json=payload,
        headers={"Idempotency-Key": idempotency_key},
    )
    assert response2.status_code == 200
    assert response2.headers.get("idempotent-replayed") == "true"


@pytest.mark.asyncio
async def test_lock_released_after_failure(
    storage: MemoryStorageAdapter, wait_config: IdempotencyConfig
) -> None:
    """Test that lock is released even when handler fails.

    Verifies:
    - Lock is released after handler exception
    - Subsequent requests get cached error response
    """
    await reset_counter()
    app = create_app(storage, wait_config)
    client = TestClient(app)

    idempotency_key = "test-lock-release-error"
    payload = {"amount": 100, "currency": "USD"}

    # First request (will fail)
    response1 = client.post(
        "/api/error-payment",
        json=payload,
        headers={"Idempotency-Key": idempotency_key},
    )
    assert response1.status_code == 400

    # Verify lock is released
    assert idempotency_key in storage._locks
    lock = storage._locks[idempotency_key]
    assert not lock.locked()

    # Second request should replay error
    response2 = client.post(
        "/api/error-payment",
        json=payload,
        headers={"Idempotency-Key": idempotency_key},
    )
    assert response2.status_code == 400
    assert response2.headers.get("idempotent-replayed") == "true"


# ============================================================================
# Race Condition Tests
# ============================================================================


@pytest.mark.asyncio
async def test_race_condition_at_new_to_running_transition(
    storage: MemoryStorageAdapter, wait_config: IdempotencyConfig
) -> None:
    """Test race condition handling at NEW -> RUNNING transition.

    Verifies:
    - Multiple requests race to create record
    - Only one wins the race
    - Losers wait and get same response
    - No duplicate execution
    """
    await reset_counter()
    app = create_app(storage, wait_config)
    client = TestClient(app)

    idempotency_key = "test-race-condition"
    payload = {"amount": 777, "currency": "USD"}

    # Launch many concurrent requests to maximize race condition likelihood
    async def make_request():
        return client.post(
            "/api/payments",
            json=payload,
            headers={"Idempotency-Key": idempotency_key},
        )

    tasks = [asyncio.to_thread(make_request) for _ in range(20)]
    results = await asyncio.gather(*tasks)

    # All should succeed
    assert all(r.status_code == 200 for r in results)

    # All should have identical response
    first_response = results[0].json()
    assert all(r.json() == first_response for r in results)

    # Handler should execute exactly once (race condition properly handled)
    count = await get_counter()
    assert count == 1


@pytest.mark.asyncio
async def test_race_condition_with_no_wait_policy(
    storage: MemoryStorageAdapter, no_wait_config: IdempotencyConfig
) -> None:
    """Test race condition with no-wait policy returns 409 for losers.

    Verifies:
    - Multiple requests race to create record
    - One wins and executes
    - Losers get 409 Conflict immediately
    """
    await reset_counter()
    app = create_app(storage, no_wait_config)
    client = TestClient(app)

    idempotency_key = "test-race-nowait"
    payload = {"amount": 888, "currency": "USD"}

    # Launch many concurrent requests
    async def make_request():
        return client.post(
            "/api/payments",
            json=payload,
            headers={"Idempotency-Key": idempotency_key},
        )

    tasks = [asyncio.to_thread(make_request) for _ in range(20)]
    results = await asyncio.gather(*tasks)

    # Count outcomes
    success_count = sum(1 for r in results if r.status_code == 200)
    conflict_count = sum(1 for r in results if r.status_code == 409)

    # Exactly 1 should succeed, rest should get 409
    assert success_count == 1
    assert conflict_count == 19

    # Handler should execute exactly once
    count = await get_counter()
    assert count == 1
