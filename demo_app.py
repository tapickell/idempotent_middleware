"""Demo FastAPI application with idempotency middleware.

This application demonstrates the idempotency middleware in action.
Run with: python demo_app.py
Then test with: bash test_demo.sh
"""

import time
from datetime import UTC, datetime
from typing import Optional

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from idempotent_middleware.adapters.asgi import ASGIIdempotencyMiddleware
from idempotent_middleware.config import IdempotencyConfig
from idempotent_middleware.storage.memory import MemoryStorageAdapter

# Create FastAPI app
app = FastAPI(
    title="Idempotency Middleware Demo",
    description="Demo API showing idempotent request handling",
    version="0.1.0",
)

# Configure middleware
storage = MemoryStorageAdapter()
config = IdempotencyConfig(
    enabled_methods=["POST", "PUT", "PATCH", "DELETE"],
    default_ttl_seconds=86400,  # 24 hours
    wait_policy="wait",  # Wait for concurrent duplicates to complete
)

app.add_middleware(
    ASGIIdempotencyMiddleware,
    storage=storage,
    config=config,
)


# Request/Response Models
class PaymentRequest(BaseModel):
    amount: int
    currency: str = "USD"
    description: Optional[str] = None


class PaymentResponse(BaseModel):
    id: str
    status: str
    amount: int
    currency: str
    created_at: str


class OrderRequest(BaseModel):
    product_id: str
    quantity: int
    customer_email: str


class OrderResponse(BaseModel):
    order_id: str
    status: str
    product_id: str
    quantity: int
    total: float
    created_at: str


# Endpoints
@app.get("/")
async def root():
    """Root endpoint - returns API info."""
    return {
        "name": "Idempotency Middleware Demo",
        "version": "0.1.0",
        "endpoints": {
            "POST /api/payments": "Create idempotent payment",
            "POST /api/orders": "Create idempotent order",
            "GET /api/status": "Health check (safe method, no idempotency)",
        },
        "usage": "Include 'Idempotency-Key' header in POST/PUT/PATCH/DELETE requests",
    }


@app.get("/api/status")
async def get_status():
    """Health check endpoint - safe method bypasses idempotency middleware."""
    return {
        "status": "ok",
        "timestamp": datetime.now(UTC).isoformat(),
        "message": "Safe methods bypass idempotency middleware",
    }


@app.post("/api/payments", response_model=PaymentResponse)
async def create_payment(
    payment: PaymentRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """Create a payment (idempotent).

    This endpoint simulates payment processing. With an Idempotency-Key header,
    repeated requests return the same response without processing duplicate payments.
    """
    # Simulate processing time
    time.sleep(0.1)

    # Simulate payment processing
    payment_id = f"pay_{int(time.time() * 1000)}"

    return PaymentResponse(
        id=payment_id,
        status="success",
        amount=payment.amount,
        currency=payment.currency,
        created_at=datetime.now(UTC).isoformat(),
    )


@app.post("/api/orders", response_model=OrderResponse)
async def create_order(
    order: OrderRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """Create an order (idempotent).

    This endpoint simulates order creation. With an Idempotency-Key header,
    repeated requests return the same response without creating duplicate orders.
    """
    # Simulate processing time
    time.sleep(0.1)

    # Simulate order processing
    order_id = f"ord_{int(time.time() * 1000)}"
    total = order.quantity * 99.99  # $99.99 per item

    return OrderResponse(
        order_id=order_id,
        status="confirmed",
        product_id=order.product_id,
        quantity=order.quantity,
        total=total,
        created_at=datetime.now(UTC).isoformat(),
    )


@app.put("/api/orders/{order_id}")
async def update_order(
    order_id: str,
    order: OrderRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """Update an order (idempotent).

    PUT requests are also idempotent with the middleware.
    """
    time.sleep(0.1)

    return {
        "order_id": order_id,
        "status": "updated",
        "product_id": order.product_id,
        "quantity": order.quantity,
        "updated_at": datetime.now(UTC).isoformat(),
    }


@app.delete("/api/orders/{order_id}")
async def cancel_order(
    order_id: str,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """Cancel an order (idempotent).

    DELETE requests are also idempotent with the middleware.
    """
    time.sleep(0.1)

    return {
        "order_id": order_id,
        "status": "cancelled",
        "cancelled_at": datetime.now(UTC).isoformat(),
    }


if __name__ == "__main__":
    print("=" * 60)
    print("Idempotency Middleware Demo Server")
    print("=" * 60)
    print("\nStarting server at http://localhost:8000")
    print("\nTry these commands:")
    print("  curl http://localhost:8000")
    print("  bash test_demo.sh")
    print("\nPress Ctrl+C to stop")
    print("=" * 60)
    print()

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
