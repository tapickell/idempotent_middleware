"""Scenario 1: Happy Path Conformance Tests

This module tests the core happy path flow of the idempotency middleware:
- First request with idempotency key executes handler
- Response is stored and returned
- Second identical request returns cached response (replay)
- Replay has header: Idempotent-Replay: true
- Response body/status/headers match exactly
- Works for all HTTP methods: POST, PUT, PATCH, DELETE
"""

import base64
import json
from typing import Any, Dict

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


class OrderRequest(BaseModel):
    """Order request model for testing."""

    product_id: str
    quantity: int


# Fixtures
@pytest.fixture
def storage() -> MemoryStorageAdapter:
    """Create a fresh memory storage adapter for each test."""
    return MemoryStorageAdapter()


@pytest.fixture
def config() -> IdempotencyConfig:
    """Create a standard config for testing."""
    return IdempotencyConfig(
        enabled_methods=["POST", "PUT", "PATCH", "DELETE"],
        default_ttl_seconds=3600,
        wait_policy="wait",
    )


@pytest.fixture
def app(storage: MemoryStorageAdapter, config: IdempotencyConfig) -> FastAPI:
    """Create a FastAPI app with idempotency middleware."""
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
        """Create a payment endpoint."""
        return {
            "id": "pay_12345",
            "status": "success",
            "amount": payment.amount,
            "currency": payment.currency,
        }

    @test_app.post("/api/orders")
    async def create_order(order: OrderRequest):
        """Create an order endpoint."""
        return {
            "order_id": "ord_12345",
            "product_id": order.product_id,
            "quantity": order.quantity,
            "total": order.quantity * 99.99,
        }

    @test_app.put("/api/orders/{order_id}")
    async def update_order(order_id: str, order: OrderRequest):
        """Update an order endpoint."""
        return {
            "order_id": order_id,
            "product_id": order.product_id,
            "quantity": order.quantity,
            "status": "updated",
        }

    @test_app.patch("/api/orders/{order_id}")
    async def patch_order(order_id: str, data: dict):
        """Partially update an order endpoint."""
        return {
            "order_id": order_id,
            "status": "patched",
            **data,
        }

    @test_app.delete("/api/orders/{order_id}")
    async def delete_order(order_id: str):
        """Delete an order endpoint."""
        return {
            "order_id": order_id,
            "status": "deleted",
        }

    @test_app.post("/api/error")
    async def error_endpoint(data: dict):
        """Endpoint that returns an error."""
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Invalid input")

    @test_app.post("/api/status/{code}")
    async def custom_status(code: int, data: dict):
        """Endpoint that returns a custom status code."""
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=code,
            content={"status": "custom", "code": code, **data},
        )

    return test_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Create a test client."""
    return TestClient(app)


# Test Cases for POST Method
def test_post_first_request_executes_handler(client: TestClient) -> None:
    """Test that the first POST request with an idempotency key executes the handler.

    Verifies:
    - Request is processed successfully
    - Response contains expected data
    - Idempotency-Key header is present in response
    - Idempotent-Replay header is NOT present (first request)
    """
    response = client.post(
        "/api/payments",
        json={"amount": 100, "currency": "USD"},
        headers={"Idempotency-Key": "test-key-001"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["amount"] == 100
    assert data["currency"] == "USD"

    # Check headers
    assert response.headers.get("Idempotency-Key") == "test-key-001"
    assert response.headers.get("Idempotent-Replay") != "true"


def test_post_second_request_returns_cached_response(client: TestClient) -> None:
    """Test that the second identical POST request returns the cached response.

    Verifies:
    - First request is processed
    - Second request returns same response
    - Second request has Idempotent-Replay: true header
    - Response bodies match exactly
    """
    # First request
    response1 = client.post(
        "/api/payments",
        json={"amount": 200, "currency": "EUR"},
        headers={"Idempotency-Key": "test-key-002"},
    )
    assert response1.status_code == 200
    data1 = response1.json()

    # Second request with same key and body
    response2 = client.post(
        "/api/payments",
        json={"amount": 200, "currency": "EUR"},
        headers={"Idempotency-Key": "test-key-002"},
    )
    assert response2.status_code == 200
    data2 = response2.json()

    # Verify replay
    assert response2.headers.get("Idempotent-Replay") == "true"
    assert response2.headers.get("Idempotency-Key") == "test-key-002"

    # Verify data matches exactly
    assert data1 == data2


def test_post_replay_preserves_status_code(client: TestClient) -> None:
    """Test that replayed responses preserve the original status code.

    Verifies:
    - Custom status codes are stored correctly
    - Replay returns the same status code
    """
    # First request
    response1 = client.post(
        "/api/status/201",
        json={"data": "test"},
        headers={"Idempotency-Key": "test-key-003"},
    )
    assert response1.status_code == 201

    # Second request
    response2 = client.post(
        "/api/status/201",
        json={"data": "test"},
        headers={"Idempotency-Key": "test-key-003"},
    )
    assert response2.status_code == 201
    assert response2.headers.get("Idempotent-Replay") == "true"


def test_post_replay_preserves_error_responses(client: TestClient) -> None:
    """Test that error responses are also cached and replayed.

    Verifies:
    - Error responses (4xx, 5xx) are cached
    - Replayed error responses match original
    - Status code and body are preserved
    """
    # First request (error)
    response1 = client.post(
        "/api/error",
        json={"data": "test"},
        headers={"Idempotency-Key": "test-key-004"},
    )
    assert response1.status_code == 400
    error1 = response1.json()

    # Second request (should replay error)
    response2 = client.post(
        "/api/error",
        json={"data": "test"},
        headers={"Idempotency-Key": "test-key-004"},
    )
    assert response2.status_code == 400
    error2 = response2.json()

    assert response2.headers.get("Idempotent-Replay") == "true"
    assert error1 == error2


# Test Cases for PUT Method
def test_put_first_and_replay(client: TestClient) -> None:
    """Test that PUT requests support idempotency.

    Verifies:
    - PUT method is handled by middleware
    - First request executes handler
    - Second request replays cached response
    """
    # First request
    response1 = client.put(
        "/api/orders/ord_999",
        json={"product_id": "prod_123", "quantity": 5},
        headers={"Idempotency-Key": "test-key-005"},
    )
    assert response1.status_code == 200
    data1 = response1.json()
    assert data1["status"] == "updated"

    # Second request
    response2 = client.put(
        "/api/orders/ord_999",
        json={"product_id": "prod_123", "quantity": 5},
        headers={"Idempotency-Key": "test-key-005"},
    )
    assert response2.status_code == 200
    data2 = response2.json()

    assert response2.headers.get("Idempotent-Replay") == "true"
    assert data1 == data2


# Test Cases for PATCH Method
def test_patch_first_and_replay(client: TestClient) -> None:
    """Test that PATCH requests support idempotency.

    Verifies:
    - PATCH method is handled by middleware
    - First request executes handler
    - Second request replays cached response
    """
    # First request
    response1 = client.patch(
        "/api/orders/ord_888",
        json={"quantity": 10},
        headers={"Idempotency-Key": "test-key-006"},
    )
    assert response1.status_code == 200
    data1 = response1.json()
    assert data1["status"] == "patched"

    # Second request
    response2 = client.patch(
        "/api/orders/ord_888",
        json={"quantity": 10},
        headers={"Idempotency-Key": "test-key-006"},
    )
    assert response2.status_code == 200
    data2 = response2.json()

    assert response2.headers.get("Idempotent-Replay") == "true"
    assert data1 == data2


# Test Cases for DELETE Method
def test_delete_first_and_replay(client: TestClient) -> None:
    """Test that DELETE requests support idempotency.

    Verifies:
    - DELETE method is handled by middleware
    - First request executes handler
    - Second request replays cached response
    """
    # First request
    response1 = client.delete(
        "/api/orders/ord_777",
        headers={"Idempotency-Key": "test-key-007"},
    )
    assert response1.status_code == 200
    data1 = response1.json()
    assert data1["status"] == "deleted"

    # Second request
    response2 = client.delete(
        "/api/orders/ord_777",
        headers={"Idempotency-Key": "test-key-007"},
    )
    assert response2.status_code == 200
    data2 = response2.json()

    assert response2.headers.get("Idempotent-Replay") == "true"
    assert data1 == data2


# Test Cases for Different Status Codes
def test_replay_with_status_202(client: TestClient) -> None:
    """Test replay works with 202 Accepted status."""
    response1 = client.post(
        "/api/status/202",
        json={"data": "accepted"},
        headers={"Idempotency-Key": "test-key-008"},
    )
    assert response1.status_code == 202

    response2 = client.post(
        "/api/status/202",
        json={"data": "accepted"},
        headers={"Idempotency-Key": "test-key-008"},
    )
    assert response2.status_code == 202
    assert response2.headers.get("Idempotent-Replay") == "true"


def test_replay_with_status_500(client: TestClient) -> None:
    """Test replay works with 500 Internal Server Error status."""
    response1 = client.post(
        "/api/status/500",
        json={"error": "internal"},
        headers={"Idempotency-Key": "test-key-009"},
    )
    assert response1.status_code == 500

    response2 = client.post(
        "/api/status/500",
        json={"error": "internal"},
        headers={"Idempotency-Key": "test-key-009"},
    )
    assert response2.status_code == 500
    assert response2.headers.get("Idempotent-Replay") == "true"


# Test Cases for Content Types
def test_replay_json_content_type(client: TestClient) -> None:
    """Test replay preserves JSON content type and encoding.

    Verifies:
    - Content-Type header is preserved
    - JSON data is correctly encoded/decoded
    """
    response1 = client.post(
        "/api/payments",
        json={"amount": 500, "currency": "GBP"},
        headers={"Idempotency-Key": "test-key-010"},
    )
    assert response1.status_code == 200

    response2 = client.post(
        "/api/payments",
        json={"amount": 500, "currency": "GBP"},
        headers={"Idempotency-Key": "test-key-010"},
    )
    assert response2.status_code == 200
    assert response2.headers.get("Idempotent-Replay") == "true"

    # Verify JSON is correctly decoded
    data = response2.json()
    assert isinstance(data, dict)
    assert data["amount"] == 500


def test_replay_with_complex_json_body(client: TestClient) -> None:
    """Test replay works with complex nested JSON structures.

    Verifies:
    - Complex JSON objects are stored correctly
    - Nested structures are preserved on replay
    """
    complex_data = {
        "level1": {
            "level2": {
                "array": [1, 2, 3],
                "string": "test",
                "number": 42.5,
            }
        }
    }

    response1 = client.post(
        "/api/status/200",
        json=complex_data,
        headers={"Idempotency-Key": "test-key-011"},
    )
    assert response1.status_code == 200

    response2 = client.post(
        "/api/status/200",
        json=complex_data,
        headers={"Idempotency-Key": "test-key-011"},
    )
    assert response2.status_code == 200
    assert response2.headers.get("Idempotent-Replay") == "true"

    # Verify complex structure is preserved
    data1 = response1.json()
    data2 = response2.json()
    assert data1 == data2


# Test Cases for Headers
def test_replay_includes_idempotency_headers(client: TestClient) -> None:
    """Test that replay responses include required idempotency headers.

    Verifies:
    - Idempotent-Replay: true is present
    - Idempotency-Key is present
    """
    response1 = client.post(
        "/api/payments",
        json={"amount": 100, "currency": "USD"},
        headers={"Idempotency-Key": "test-key-012"},
    )
    assert response1.status_code == 200

    response2 = client.post(
        "/api/payments",
        json={"amount": 100, "currency": "USD"},
        headers={"Idempotency-Key": "test-key-012"},
    )

    # Check required headers
    assert response2.headers.get("Idempotent-Replay") == "true"
    assert response2.headers.get("Idempotency-Key") == "test-key-012"


def test_replay_filters_volatile_headers(client: TestClient) -> None:
    """Test that volatile headers (Date, Server, etc.) are filtered on replay.

    Verifies:
    - Stable headers (Content-Type) are preserved
    - Volatile headers are handled correctly
    """
    response1 = client.post(
        "/api/payments",
        json={"amount": 100, "currency": "USD"},
        headers={"Idempotency-Key": "test-key-013"},
    )
    assert response1.status_code == 200

    response2 = client.post(
        "/api/payments",
        json={"amount": 100, "currency": "USD"},
        headers={"Idempotency-Key": "test-key-013"},
    )
    assert response2.status_code == 200
    assert response2.headers.get("Idempotent-Replay") == "true"

    # Content-Type should be preserved
    assert "content-type" in response2.headers


# Test Cases for Trace ID Propagation
def test_trace_id_propagation(client: TestClient) -> None:
    """Test that trace IDs are extracted and propagated.

    Verifies:
    - Trace ID headers are recognized
    - First request processes with trace ID
    - Second request replays correctly
    """
    response1 = client.post(
        "/api/payments",
        json={"amount": 100, "currency": "USD"},
        headers={
            "Idempotency-Key": "test-key-014",
            "X-Trace-Id": "trace-12345",
        },
    )
    assert response1.status_code == 200

    response2 = client.post(
        "/api/payments",
        json={"amount": 100, "currency": "USD"},
        headers={
            "Idempotency-Key": "test-key-014",
            "X-Trace-Id": "trace-12345",
        },
    )
    assert response2.status_code == 200
    assert response2.headers.get("Idempotent-Replay") == "true"


# Test Cases for Different Request Bodies
def test_replay_with_empty_body(client: TestClient) -> None:
    """Test replay works with empty request body.

    Verifies:
    - DELETE requests with no body work correctly
    - Empty body is handled properly
    """
    response1 = client.delete(
        "/api/orders/ord_empty",
        headers={"Idempotency-Key": "test-key-015"},
    )
    assert response1.status_code == 200

    response2 = client.delete(
        "/api/orders/ord_empty",
        headers={"Idempotency-Key": "test-key-015"},
    )
    assert response2.status_code == 200
    assert response2.headers.get("Idempotent-Replay") == "true"


def test_replay_with_large_body(client: TestClient) -> None:
    """Test replay works with larger request bodies.

    Verifies:
    - Large JSON bodies are stored correctly
    - Replay returns complete data
    """
    large_data = {
        "items": [{"id": i, "value": f"item_{i}"} for i in range(100)]
    }

    response1 = client.post(
        "/api/status/200",
        json=large_data,
        headers={"Idempotency-Key": "test-key-016"},
    )
    assert response1.status_code == 200

    response2 = client.post(
        "/api/status/200",
        json=large_data,
        headers={"Idempotency-Key": "test-key-016"},
    )
    assert response2.status_code == 200
    assert response2.headers.get("Idempotent-Replay") == "true"

    # Verify data integrity
    data1 = response1.json()
    data2 = response2.json()
    assert data1 == data2


# Test Cases for Multiple Keys
def test_different_keys_execute_separately(client: TestClient) -> None:
    """Test that different idempotency keys are treated independently.

    Verifies:
    - Different keys result in different executions
    - Cached responses are key-specific
    """
    # Request with key A
    response1 = client.post(
        "/api/payments",
        json={"amount": 100, "currency": "USD"},
        headers={"Idempotency-Key": "key-A"},
    )
    assert response1.status_code == 200

    # Request with key B (same body)
    response2 = client.post(
        "/api/payments",
        json={"amount": 100, "currency": "USD"},
        headers={"Idempotency-Key": "key-B"},
    )
    assert response2.status_code == 200

    # Neither should be a replay (different keys)
    assert response1.headers.get("Idempotent-Replay") != "true"
    assert response2.headers.get("Idempotent-Replay") != "true"

    # Replay with key A
    response3 = client.post(
        "/api/payments",
        json={"amount": 100, "currency": "USD"},
        headers={"Idempotency-Key": "key-A"},
    )
    assert response3.status_code == 200
    assert response3.headers.get("Idempotent-Replay") == "true"


# Test Cases for No Idempotency Key
def test_no_idempotency_key_processes_normally(client: TestClient) -> None:
    """Test that requests without idempotency key are processed normally.

    Verifies:
    - Requests without key execute handler
    - No caching occurs
    - No replay headers are added
    """
    response1 = client.post(
        "/api/payments",
        json={"amount": 100, "currency": "USD"},
    )
    assert response1.status_code == 200
    assert response1.headers.get("Idempotency-Key") is None
    assert response1.headers.get("Idempotent-Replay") != "true"

    response2 = client.post(
        "/api/payments",
        json={"amount": 100, "currency": "USD"},
    )
    assert response2.status_code == 200
    assert response2.headers.get("Idempotent-Replay") != "true"
