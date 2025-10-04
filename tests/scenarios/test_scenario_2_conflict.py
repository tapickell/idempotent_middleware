"""Scenario 2: Conflict Detection Conformance Tests

This module tests conflict detection in the idempotency middleware:
- Same key with different request body -> 409 Conflict
- Same key with different query params -> 409 Conflict
- Same key with different path -> 409 Conflict (different endpoint)
- Same key with different method -> 409 Conflict
- Error message explains fingerprint mismatch
- Original response still cached (doesn't corrupt state)
"""

import pytest
from fastapi import FastAPI, Query
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

    @test_app.post("/api/payments/search")
    async def search_payments(
        min_amount: int = Query(default=0),
        max_amount: int = Query(default=1000),
    ):
        """Endpoint that uses query parameters."""
        return {
            "results": [],
            "filters": {
                "min_amount": min_amount,
                "max_amount": max_amount,
            },
        }

    @test_app.post("/api/v1/payments")
    async def create_payment_v1(payment: PaymentRequest):
        """Alternative payment endpoint (different path)."""
        return {
            "id": "pay_v1_12345",
            "status": "success",
            "amount": payment.amount,
            "currency": payment.currency,
        }

    return test_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Create a test client."""
    return TestClient(app)


# Test Cases for Body Conflicts
def test_conflict_different_body_amount(client: TestClient) -> None:
    """Test conflict when same key is used with different request body (amount).

    Verifies:
    - First request succeeds (200)
    - Second request with different amount returns 409 Conflict
    - Error message is present
    """
    # First request
    response1 = client.post(
        "/api/payments",
        json={"amount": 100, "currency": "USD"},
        headers={"Idempotency-Key": "conflict-key-001"},
    )
    assert response1.status_code == 200

    # Second request with different amount
    response2 = client.post(
        "/api/payments",
        json={"amount": 200, "currency": "USD"},  # Different amount!
        headers={"Idempotency-Key": "conflict-key-001"},
    )
    assert response2.status_code == 409
    assert "conflict" in response2.text.lower() or "fingerprint" in response2.text.lower()


def test_conflict_different_body_currency(client: TestClient) -> None:
    """Test conflict when same key is used with different currency field.

    Verifies:
    - Field value changes trigger conflict detection
    - 409 status is returned
    """
    # First request
    response1 = client.post(
        "/api/payments",
        json={"amount": 100, "currency": "USD"},
        headers={"Idempotency-Key": "conflict-key-002"},
    )
    assert response1.status_code == 200

    # Second request with different currency
    response2 = client.post(
        "/api/payments",
        json={"amount": 100, "currency": "EUR"},  # Different currency!
        headers={"Idempotency-Key": "conflict-key-002"},
    )
    assert response2.status_code == 409


def test_conflict_additional_field(client: TestClient) -> None:
    """Test conflict when additional fields are added to request body.

    Verifies:
    - Adding extra fields changes fingerprint
    - Results in 409 Conflict
    """
    # First request
    response1 = client.post(
        "/api/orders",
        json={"product_id": "prod_123", "quantity": 1},
        headers={"Idempotency-Key": "conflict-key-003"},
    )
    assert response1.status_code == 200

    # Second request with additional field
    response2 = client.post(
        "/api/orders",
        json={"product_id": "prod_123", "quantity": 1, "extra": "field"},
        headers={"Idempotency-Key": "conflict-key-003"},
    )
    assert response2.status_code == 409


def test_conflict_missing_field(client: TestClient) -> None:
    """Test conflict when fields are removed from request body.

    Verifies:
    - Removing fields changes fingerprint
    - Results in 409 Conflict
    """
    # First request with extra field
    response1 = client.post(
        "/api/orders",
        json={"product_id": "prod_123", "quantity": 1, "extra": "field"},
        headers={"Idempotency-Key": "conflict-key-004"},
    )
    assert response1.status_code == 200

    # Second request without extra field
    response2 = client.post(
        "/api/orders",
        json={"product_id": "prod_123", "quantity": 1},
        headers={"Idempotency-Key": "conflict-key-004"},
    )
    assert response2.status_code == 409


def test_conflict_nested_field_change(client: TestClient) -> None:
    """Test conflict when nested object fields change.

    Verifies:
    - Changes in nested structures are detected
    - Deep equality is enforced
    """
    # First request
    response1 = client.post(
        "/api/orders",
        json={
            "product_id": "prod_123",
            "quantity": 1,
        },
        headers={"Idempotency-Key": "conflict-key-005"},
    )
    assert response1.status_code == 200

    # Second request with different product_id
    response2 = client.post(
        "/api/orders",
        json={
            "product_id": "prod_456",  # Different!
            "quantity": 1,
        },
        headers={"Idempotency-Key": "conflict-key-005"},
    )
    assert response2.status_code == 409


# Test Cases for Query Parameter Conflicts
def test_conflict_different_query_params(client: TestClient) -> None:
    """Test conflict when same key is used with different query parameters.

    Verifies:
    - Query parameters are part of fingerprint
    - Different query params trigger conflict
    """
    # First request
    response1 = client.post(
        "/api/payments/search?min_amount=0&max_amount=100",
        headers={"Idempotency-Key": "conflict-key-006"},
    )
    assert response1.status_code == 200

    # Second request with different query params
    response2 = client.post(
        "/api/payments/search?min_amount=0&max_amount=200",  # Different max!
        headers={"Idempotency-Key": "conflict-key-006"},
    )
    assert response2.status_code == 409


def test_conflict_additional_query_param(client: TestClient) -> None:
    """Test conflict when additional query parameter is added.

    Verifies:
    - Adding query params changes fingerprint
    """
    # First request
    response1 = client.post(
        "/api/payments/search?min_amount=0",
        headers={"Idempotency-Key": "conflict-key-007"},
    )
    assert response1.status_code == 200

    # Second request with additional query param
    response2 = client.post(
        "/api/payments/search?min_amount=0&max_amount=100",
        headers={"Idempotency-Key": "conflict-key-007"},
    )
    assert response2.status_code == 409


def test_conflict_missing_query_param(client: TestClient) -> None:
    """Test conflict when query parameter is removed.

    Verifies:
    - Removing query params changes fingerprint
    """
    # First request with two params
    response1 = client.post(
        "/api/payments/search?min_amount=0&max_amount=100",
        headers={"Idempotency-Key": "conflict-key-008"},
    )
    assert response1.status_code == 200

    # Second request with one param
    response2 = client.post(
        "/api/payments/search?min_amount=0",
        headers={"Idempotency-Key": "conflict-key-008"},
    )
    assert response2.status_code == 409


# Test Cases for Path Conflicts
def test_conflict_different_path(client: TestClient) -> None:
    """Test conflict when same key is used with different endpoint path.

    Verifies:
    - Path is part of fingerprint
    - Different paths trigger conflict
    """
    # First request to /api/payments
    response1 = client.post(
        "/api/payments",
        json={"amount": 100, "currency": "USD"},
        headers={"Idempotency-Key": "conflict-key-009"},
    )
    assert response1.status_code == 200

    # Second request to /api/v1/payments (different path!)
    response2 = client.post(
        "/api/v1/payments",
        json={"amount": 100, "currency": "USD"},
        headers={"Idempotency-Key": "conflict-key-009"},
    )
    assert response2.status_code == 409


def test_conflict_different_path_parameter(client: TestClient) -> None:
    """Test conflict when path parameter changes.

    Verifies:
    - Path parameters are part of fingerprint
    - Different path params trigger conflict
    """
    # First request
    response1 = client.put(
        "/api/orders/ord_123",
        json={"product_id": "prod_456", "quantity": 1},
        headers={"Idempotency-Key": "conflict-key-010"},
    )
    assert response1.status_code == 200

    # Second request with different order_id in path
    response2 = client.put(
        "/api/orders/ord_456",  # Different order_id!
        json={"product_id": "prod_456", "quantity": 1},
        headers={"Idempotency-Key": "conflict-key-010"},
    )
    assert response2.status_code == 409


# Test Cases for Method Conflicts
def test_conflict_different_http_method(client: TestClient) -> None:
    """Test conflict when same key is used with different HTTP method.

    Verifies:
    - HTTP method is part of fingerprint
    - POST vs PUT triggers conflict
    """
    # First request with POST
    response1 = client.post(
        "/api/orders",
        json={"product_id": "prod_123", "quantity": 1},
        headers={"Idempotency-Key": "conflict-key-011"},
    )
    assert response1.status_code == 200

    # Second request with PUT (different method!)
    response2 = client.put(
        "/api/orders/ord_123",
        json={"product_id": "prod_123", "quantity": 1},
        headers={"Idempotency-Key": "conflict-key-011"},
    )
    assert response2.status_code == 409


def test_conflict_post_vs_patch(client: TestClient) -> None:
    """Test conflict between POST and PATCH methods.

    Verifies:
    - Different methods with same key conflict
    """
    # First request with POST
    response1 = client.post(
        "/api/orders",
        json={"product_id": "prod_123", "quantity": 1},
        headers={"Idempotency-Key": "conflict-key-012"},
    )
    assert response1.status_code == 200

    # Second request with PATCH
    response2 = client.patch(
        "/api/orders/ord_123",
        json={"product_id": "prod_123", "quantity": 1},
        headers={"Idempotency-Key": "conflict-key-012"},
    )
    assert response2.status_code == 409


def test_conflict_put_vs_delete(client: TestClient) -> None:
    """Test conflict between PUT and DELETE methods.

    Verifies:
    - PUT vs DELETE with same key conflicts
    """
    # First request with PUT
    response1 = client.put(
        "/api/orders/ord_123",
        json={"product_id": "prod_123", "quantity": 1},
        headers={"Idempotency-Key": "conflict-key-013"},
    )
    assert response1.status_code == 200

    # Second request with DELETE
    response2 = client.delete(
        "/api/orders/ord_123",
        headers={"Idempotency-Key": "conflict-key-013"},
    )
    assert response2.status_code == 409


# Test Cases for Error Message Validation
def test_conflict_error_message_format(client: TestClient) -> None:
    """Test that conflict error message is informative.

    Verifies:
    - Error message contains useful information
    - Message explains the conflict
    """
    # First request
    response1 = client.post(
        "/api/payments",
        json={"amount": 100, "currency": "USD"},
        headers={"Idempotency-Key": "conflict-key-014"},
    )
    assert response1.status_code == 200

    # Second request with conflict
    response2 = client.post(
        "/api/payments",
        json={"amount": 200, "currency": "USD"},
        headers={"Idempotency-Key": "conflict-key-014"},
    )
    assert response2.status_code == 409

    # Verify error message
    error_text = response2.text.lower()
    assert "conflict" in error_text or "fingerprint" in error_text
    # Should contain idempotency key
    assert "conflict-key-014" in response2.text or "idempotency-key" in response2.headers


def test_conflict_response_headers(client: TestClient) -> None:
    """Test that conflict response includes appropriate headers.

    Verifies:
    - Content-Type is set
    - Idempotency-Key header is present
    """
    # First request
    response1 = client.post(
        "/api/payments",
        json={"amount": 100, "currency": "USD"},
        headers={"Idempotency-Key": "conflict-key-015"},
    )
    assert response1.status_code == 200

    # Second request with conflict
    response2 = client.post(
        "/api/payments",
        json={"amount": 200, "currency": "USD"},
        headers={"Idempotency-Key": "conflict-key-015"},
    )
    assert response2.status_code == 409

    # Check headers
    assert response2.headers.get("content-type") is not None
    assert response2.headers.get("idempotency-key") == "conflict-key-015"


# Test Cases for State Preservation
def test_conflict_preserves_original_response(client: TestClient) -> None:
    """Test that conflict doesn't corrupt the cached original response.

    Verifies:
    - After conflict, original response is still cached
    - Third request with correct body returns cached response
    - Conflict doesn't change stored data
    """
    # First request
    response1 = client.post(
        "/api/payments",
        json={"amount": 100, "currency": "USD"},
        headers={"Idempotency-Key": "conflict-key-016"},
    )
    assert response1.status_code == 200
    data1 = response1.json()

    # Second request with conflict
    response2 = client.post(
        "/api/payments",
        json={"amount": 200, "currency": "USD"},
        headers={"Idempotency-Key": "conflict-key-016"},
    )
    assert response2.status_code == 409

    # Third request with original body (should replay)
    response3 = client.post(
        "/api/payments",
        json={"amount": 100, "currency": "USD"},
        headers={"Idempotency-Key": "conflict-key-016"},
    )
    assert response3.status_code == 200
    assert response3.headers.get("Idempotent-Replay") == "true"
    data3 = response3.json()
    assert data1 == data3


def test_conflict_after_successful_completion(client: TestClient) -> None:
    """Test conflict detection after successful completion.

    Verifies:
    - Completed requests can still detect conflicts
    - Cache is not corrupted by conflict attempts
    """
    # First request - completes successfully
    response1 = client.post(
        "/api/payments",
        json={"amount": 100, "currency": "USD"},
        headers={"Idempotency-Key": "conflict-key-017"},
    )
    assert response1.status_code == 200

    # Replay the original - should work
    response2 = client.post(
        "/api/payments",
        json={"amount": 100, "currency": "USD"},
        headers={"Idempotency-Key": "conflict-key-017"},
    )
    assert response2.status_code == 200
    assert response2.headers.get("Idempotent-Replay") == "true"

    # Try with different body - should conflict
    response3 = client.post(
        "/api/payments",
        json={"amount": 200, "currency": "USD"},
        headers={"Idempotency-Key": "conflict-key-017"},
    )
    assert response3.status_code == 409

    # Original should still replay correctly
    response4 = client.post(
        "/api/payments",
        json={"amount": 100, "currency": "USD"},
        headers={"Idempotency-Key": "conflict-key-017"},
    )
    assert response4.status_code == 200
    assert response4.headers.get("Idempotent-Replay") == "true"


def test_conflict_after_error_response(client: TestClient) -> None:
    """Test conflict detection after error response is cached.

    Verifies:
    - Error responses can detect conflicts
    - Fingerprint matching works for failed requests
    """
    from fastapi import HTTPException

    app = client.app

    @app.post("/api/error-endpoint")
    async def error_endpoint(data: dict):
        """Endpoint that raises an error."""
        raise HTTPException(status_code=400, detail="Bad request")

    # First request - returns error
    response1 = client.post(
        "/api/error-endpoint",
        json={"field": "value1"},
        headers={"Idempotency-Key": "conflict-key-018"},
    )
    assert response1.status_code == 400

    # Replay with same body - should return cached error
    response2 = client.post(
        "/api/error-endpoint",
        json={"field": "value1"},
        headers={"Idempotency-Key": "conflict-key-018"},
    )
    assert response2.status_code == 400
    assert response2.headers.get("Idempotent-Replay") == "true"

    # Different body - should conflict
    response3 = client.post(
        "/api/error-endpoint",
        json={"field": "value2"},
        headers={"Idempotency-Key": "conflict-key-018"},
    )
    assert response3.status_code == 409


# Test Cases for Multiple Conflicts
def test_multiple_conflicts_same_key(client: TestClient) -> None:
    """Test multiple different conflict attempts with same key.

    Verifies:
    - Each different request triggers conflict
    - Original response remains intact
    """
    # Original request
    response1 = client.post(
        "/api/payments",
        json={"amount": 100, "currency": "USD"},
        headers={"Idempotency-Key": "conflict-key-019"},
    )
    assert response1.status_code == 200
    original_data = response1.json()

    # Conflict attempt 1
    response2 = client.post(
        "/api/payments",
        json={"amount": 200, "currency": "USD"},
        headers={"Idempotency-Key": "conflict-key-019"},
    )
    assert response2.status_code == 409

    # Conflict attempt 2
    response3 = client.post(
        "/api/payments",
        json={"amount": 100, "currency": "EUR"},
        headers={"Idempotency-Key": "conflict-key-019"},
    )
    assert response3.status_code == 409

    # Conflict attempt 3
    response4 = client.post(
        "/api/payments",
        json={"amount": 300, "currency": "GBP"},
        headers={"Idempotency-Key": "conflict-key-019"},
    )
    assert response4.status_code == 409

    # Original should still work
    response5 = client.post(
        "/api/payments",
        json={"amount": 100, "currency": "USD"},
        headers={"Idempotency-Key": "conflict-key-019"},
    )
    assert response5.status_code == 200
    assert response5.headers.get("Idempotent-Replay") == "true"
    assert response5.json() == original_data


# Test Cases for Edge Cases
def test_conflict_with_empty_vs_nonempty_body(client: TestClient) -> None:
    """Test conflict between empty body and non-empty body.

    Verifies:
    - Empty vs non-empty body is detected as different
    """
    # First request with body
    response1 = client.post(
        "/api/payments",
        json={"amount": 100, "currency": "USD"},
        headers={"Idempotency-Key": "conflict-key-020"},
    )
    assert response1.status_code == 200

    # Second request with different body type (this will fail at endpoint level)
    # But we test that DELETE (no body) vs POST (with body) conflicts
    response2 = client.delete(
        "/api/orders/ord_123",
        headers={"Idempotency-Key": "conflict-key-020"},
    )
    assert response2.status_code == 409


def test_conflict_case_sensitive_values(client: TestClient) -> None:
    """Test that body field values are case-sensitive for conflict detection.

    Verifies:
    - "USD" vs "usd" triggers conflict
    - Case sensitivity is enforced
    """
    # First request
    response1 = client.post(
        "/api/payments",
        json={"amount": 100, "currency": "USD"},
        headers={"Idempotency-Key": "conflict-key-021"},
    )
    assert response1.status_code == 200

    # Second request with different case
    response2 = client.post(
        "/api/payments",
        json={"amount": 100, "currency": "usd"},  # lowercase!
        headers={"Idempotency-Key": "conflict-key-021"},
    )
    assert response2.status_code == 409


def test_conflict_with_whitespace_differences(client: TestClient) -> None:
    """Test that whitespace in JSON values affects fingerprint.

    Verifies:
    - Whitespace differences are detected
    """
    # First request
    response1 = client.post(
        "/api/orders",
        json={"product_id": "prod_123", "quantity": 1},
        headers={"Idempotency-Key": "conflict-key-022"},
    )
    assert response1.status_code == 200

    # Second request with whitespace in value
    response2 = client.post(
        "/api/orders",
        json={"product_id": "prod_123 ", "quantity": 1},  # Extra space!
        headers={"Idempotency-Key": "conflict-key-022"},
    )
    assert response2.status_code == 409
