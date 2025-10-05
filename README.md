# Idempotency Middleware for Python

A production-ready idempotency middleware implementation for Python web applications, ensuring safe request retries without duplicate side effects.

[![Tests](https://img.shields.io/badge/tests-545%20passing-brightgreen)](./STATUS.md)
[![Coverage](https://img.shields.io/badge/coverage-98%25-brightgreen)](./STATUS.md)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](./pyproject.toml)
[![Type Checking](https://img.shields.io/badge/mypy-strict-blue)](./pyproject.toml)

## 🎯 What is This?

APIs that perform side effects (charge cards, create orders, send emails) must tolerate client/network retries without duplicating the effect. Idempotency keys let clients safely retry a *logically single* operation.

**This middleware ensures**:
- Side effects execute **at most once** per idempotency key
- Identical responses returned for duplicate requests
- Concurrent duplicates handled without double-execution
- TTL-based storage with automatic cleanup

## ✨ Features

- **Framework Support**: FastAPI/Starlette (ASGI), with pluggable adapter architecture
- **Storage Backends**: In-memory (production-ready for single process), extensible for Redis/SQL
- **Concurrency Control**: Async/await with per-key locking, supports wait/no-wait policies
- **Request Fingerprinting**: SHA-256 based, detects conflicting requests with same key
- **Production Ready**: 545 tests passing, 98%+ coverage, mypy strict mode
- **Observability**: Prometheus metrics, structured logging (structlog)
- **Configurable**: TTL, body size limits, enabled methods, wait policies

## 📦 Installation

```bash
git clone <repository-url>
cd idempotent_middleware
pip install -e .
```

### Dependencies

```bash
# Core
pip install pydantic>=2.6.0 starlette>=0.36.0

# Optional
pip install fastapi>=0.109.0 uvicorn[standard]>=0.27.0  # For FastAPI
pip install prometheus-client>=0.19.0                    # For metrics
pip install structlog>=24.1.0                            # For logging
```

## 🚀 Quick Start

### Basic Usage (FastAPI)

```python
from fastapi import FastAPI
from idempotent_middleware.adapters.asgi import ASGIIdempotencyMiddleware
from idempotent_middleware.storage.memory import MemoryStorageAdapter
from idempotent_middleware.config import IdempotencyConfig

app = FastAPI()

# Configure middleware
storage = MemoryStorageAdapter()
config = IdempotencyConfig(
    enabled_methods=["POST", "PUT", "PATCH", "DELETE"],
    default_ttl_seconds=86400,  # 24 hours
    wait_policy="wait",  # Wait for concurrent duplicates
    max_body_bytes=1048576,  # 1MB limit
)

app.add_middleware(
    ASGIIdempotencyMiddleware,
    storage=storage,
    config=config,
)

@app.post("/api/payments")
async def create_payment(amount: int):
    # Process payment
    return {"status": "success", "id": "payment-123", "amount": amount}
```

### Making Idempotent Requests

```bash
# First request - executes handler
curl -X POST http://localhost:8000/api/payments \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: payment-20240101-001" \
  -d '{"amount": 100}'
# Response: {"status": "success", "id": "payment-123", "amount": 100}

# Duplicate request - returns cached response
curl -X POST http://localhost:8000/api/payments \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: payment-20240101-001" \
  -d '{"amount": 100}'
# Response: {"status": "success", "id": "payment-123", "amount": 100}
# Header: Idempotent-Replay: true

# Conflicting request - different body, same key
curl -X POST http://localhost:8000/api/payments \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: payment-20240101-001" \
  -d '{"amount": 200}'
# Response: 409 Conflict - fingerprint mismatch
```

## 📚 Examples

### Demo Application

Run the included demo app:

```bash
# Start demo server
python demo_app.py

# In another terminal, run automated test suite
bash test_demo.sh
```

The demo includes:
- Payment creation endpoint
- Order management endpoints
- Health check (safe methods)
- 12 automated test scenarios

### Custom Configuration

```python
config = IdempotencyConfig(
    # Which HTTP methods require idempotency
    enabled_methods=["POST", "PUT", "PATCH", "DELETE"],

    # How long to cache responses (seconds)
    default_ttl_seconds=86400,  # 24 hours

    # Concurrent request policy
    wait_policy="wait",  # "wait" or "no-wait"

    # Execution timeout (seconds)
    execution_timeout_seconds=30,

    # Maximum request body size (bytes, 0 = unlimited)
    max_body_bytes=1048576,  # 1MB

    # Headers to include in fingerprint (case-insensitive)
    fingerprint_headers=["content-type", "content-length"],
)
```

### No-Wait Policy

```python
config = IdempotencyConfig(
    wait_policy="no-wait",  # Return 409 immediately for concurrent duplicates
)

# First request (still running)
# Concurrent request gets 409 Conflict with Retry-After header
```

### Storage Adapter

```python
# In-memory (default, production-ready for single process)
from idempotent_middleware.storage.memory import MemoryStorageAdapter
storage = MemoryStorageAdapter()

# Future: Redis (for distributed systems)
# from idempotent_middleware.storage.redis import RedisStorageAdapter
# storage = RedisStorageAdapter(redis_url="redis://localhost:6379")
```

### Error Handling

```python
@app.post("/api/orders")
async def create_order(order_data: dict):
    if not valid_order(order_data):
        # Error responses are also cached!
        raise HTTPException(status_code=400, detail="Invalid order")

    # Process order
    return {"order_id": "ord-123", "status": "confirmed"}

# First request with invalid data → 400 error
# Duplicate request → 400 error (cached, not reprocessed)
```

## 🏗️ Architecture

### Request Flow

```
Client Request
    ↓
Extract Idempotency-Key header
    ↓
Compute request fingerprint (SHA-256)
    ↓
Check storage for existing record
    ↓
┌─────────────┬──────────────┬──────────────┐
│   NEW       │   RUNNING    │  COMPLETED   │
│   (none)    │   (locked)   │   (cached)   │
└─────────────┴──────────────┴──────────────┘
    ↓              ↓               ↓
Acquire lease  Wait/Return    Check fingerprint
Execute handler   409          match → replay
Store result                   mismatch → 409
Release lease
Return response
```

### Components

- **Core Middleware**: Framework-agnostic request/response handling
- **ASGI Adapter**: FastAPI/Starlette integration
- **Storage Layer**: Pluggable persistence (in-memory, Redis, SQL)
- **Fingerprinting**: Deterministic request hashing for conflict detection
- **Concurrency Control**: Per-key async locks with lease tokens

## 🧪 Testing

### Run Tests

```bash
# All tests (545 total)
pytest

# Unit tests only (454 tests)
pytest tests/unit/

# Conformance tests (91 tests)
pytest tests/scenarios/

# With coverage
pytest --cov=src/idempotent_middleware --cov-report=html

# Fast mode (skip slow hypothesis tests)
pytest -m "not hypothesis"
```

### Test Coverage

- **545 tests passing** (100%)
- **98%+ code coverage**
- All 6 spec scenarios validated
- Concurrent execution verified (15 tests)
- TTL/cleanup tested (15 tests)
- Conflict detection tested (22 tests)

## 📊 Performance

**Benchmarks** (in-memory adapter):
- First request: ~100ms (includes handler)
- Replay request: ~2-5ms (cached)
- Fingerprint computation: <1ms
- Lock acquisition: <1ms
- Throughput: >1000 replays/second

**Complexity**:
- Storage lookup: O(1)
- Fingerprint: O(k log k) where k = query params
- Cleanup: O(n) where n = expired records

## 🔒 Security

### Best Practices

1. **Treat idempotency keys as secrets**: Don't log them in plain text
2. **Use strong entropy**: UUIDv4 or ≥120 bits random
3. **Encrypt stored bodies**: For sensitive data (implement custom storage adapter)
4. **Rate limit by key**: Prevent brute force attacks
5. **Validate key format**: Reject malformed keys early

### Key Generation (Client-Side)

```python
import uuid

# Good: UUIDv4
idempotency_key = str(uuid.uuid4())

# Good: Timestamp + random
import secrets
idempotency_key = f"payment-{int(time.time())}-{secrets.token_hex(8)}"

# Bad: Predictable sequence
idempotency_key = f"payment-{counter}"  # ❌ Don't do this
```

## 🔧 Configuration Reference

### IdempotencyConfig

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `enabled_methods` | list[str] | `["POST", "PUT", "PATCH", "DELETE"]` | HTTP methods to make idempotent |
| `default_ttl_seconds` | int | `86400` | How long to cache responses (24 hours) |
| `wait_policy` | str | `"wait"` | `"wait"` or `"no-wait"` for concurrent requests |
| `execution_timeout_seconds` | int | `30` | Max time to wait for running request |
| `max_body_bytes` | int | `1048576` | Max request body size (1MB, 0 = unlimited) |
| `fingerprint_headers` | list[str] | `["content-type", "content-length"]` | Headers included in fingerprint |

### Storage Adapter Interface

Implement `StorageAdapter` protocol for custom backends:

```python
from idempotent_middleware.storage.base import StorageAdapter

class CustomStorageAdapter(StorageAdapter):
    async def get(self, key: str) -> Optional[IdempotencyRecord]:
        """Retrieve record by key"""

    async def put_new_running(
        self, key: str, fingerprint: str, ttl_seconds: int, trace_id: Optional[str] = None
    ) -> LeaseResult:
        """Atomically acquire lease for new request"""

    async def complete(self, lease_token: str, response: StoredResponse) -> None:
        """Mark request as completed with response"""

    async def fail(self, lease_token: str, response: StoredResponse) -> None:
        """Mark request as failed with error response"""

    async def cleanup_expired(self) -> int:
        """Remove expired records, return count"""
```

## 🐛 Troubleshooting

### Common Issues

**Conflict errors (409) on valid retries**
- Check request body is identical (whitespace matters)
- Verify headers included in fingerprint match
- Check query parameter order (auto-normalized)

**Concurrent requests not waiting**
- Verify `wait_policy="wait"` in config
- Check `execution_timeout_seconds` isn't too short

**Storage growing indefinitely**
- Implement cleanup background task
- Or use Redis with built-in TTL

**Performance issues**
- Enable Prometheus metrics to identify bottlenecks
- Consider Redis adapter for distributed deployments
- Check `max_body_bytes` isn't causing large memory usage

### Debug Mode

```python
# Enable detailed logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Or use structlog
import structlog
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
)
```

## 📖 API Reference

See [STATUS.md](./STATUS.md) for detailed implementation status.

### Key Classes

- `IdempotencyConfig`: Configuration model
- `ASGIIdempotencyMiddleware`: FastAPI/Starlette adapter
- `MemoryStorageAdapter`: In-memory storage (production-ready)
- `IdempotencyRecord`: Stored record model
- `StorageAdapter`: Protocol for custom adapters

## 🛣️ Roadmap

### Current Status
- ✅ Core middleware (framework-agnostic)
- ✅ ASGI adapter (FastAPI/Starlette)
- ✅ In-memory storage
- ✅ 545 tests passing
- ✅ Demo application
- ✅ Conformance validated

### Future Enhancements
- [ ] Redis storage adapter
- [ ] SQL storage adapter (PostgreSQL/MySQL)
- [ ] WSGI adapter (Flask/Django)
- [ ] File storage adapter
- [ ] CLI inspector tool
- [ ] API documentation (Sphinx)
- [ ] PyPI package

## 🤝 Contributing

Contributions welcome! Areas for improvement:

1. **Storage Adapters**: Redis, PostgreSQL, MySQL implementations
2. **Framework Adapters**: Flask/Django WSGI support
3. **Documentation**: More examples, tutorials, API docs
4. **Performance**: Benchmarking, optimization
5. **Testing**: Additional edge cases, load testing

## 📄 License

[Your License Here]

## 🙏 Acknowledgments

Built following the idempotency specification and inspired by:
- [Stripe's Idempotent Requests](https://stripe.com/docs/api/idempotent_requests)
- [RFC 7231 - HTTP Idempotency](https://tools.ietf.org/html/rfc7231#section-4.2)
- Various production idempotency implementations

## 📞 Support

- **Issues**: Open an issue on GitHub
- **Documentation**: See [STATUS.md](./STATUS.md) for implementation details
- **Demo**: Run `python demo_app.py` and `bash test_demo.sh`
- **Tests**: Run `pytest` to verify installation

---

**Status**: Production-ready for single-process deployments. For distributed systems, implement Redis or SQL storage adapter following the `StorageAdapter` protocol.
