# Idempotency Middleware - Detailed Implementation Plan

## Table of Contents
1. [Architecture Overview](#architecture-overview)
2. [Technology Stack](#technology-stack)
3. [Module Structure](#module-structure)
4. [Core Algorithms](#core-algorithms)
5. [Implementation Tickets](#implementation-tickets)
6. [QA Testing Strategy](#qa-testing-strategy)
7. [Timeline & Phases](#timeline--phases)

---

## Architecture Overview

### Framework Selection: **ASGI Middleware with Framework-Agnostic Core**

**Decision Rationale:**
- **ASGI-first** (FastAPI/Starlette) for native async/await support
- **Framework-agnostic core** allows adapters for WSGI (Flask/Django)
- Async primitives (`asyncio.Lock`, `asyncio.Event`) ideal for concurrent request handling
- Better performance under high throughput for I/O-bound operations

### High-Level Architecture

```
┌─────────────────────────────────────────────────┐
│          Web Framework Layer                    │
│   (FastAPI/Starlette/Flask/Django)             │
└────────────────┬────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────┐
│         Framework Adapters                      │
│    (ASGI Middleware / WSGI Middleware)         │
└────────────────┬────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────┐
│      Core Middleware (Framework-Agnostic)       │
│   • State Machine                               │
│   • Fingerprint Generation                      │
│   • Response Replay                             │
│   • TTL Management                              │
└────────────────┬────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────┐
│         Storage Adapter Interface               │
└────┬──────────┬──────────┬──────────┬───────────┘
     │          │          │          │
┌────▼────┐ ┌──▼─────┐ ┌──▼─────┐ ┌──▼─────┐
│ Memory  │ │  File  │ │ Redis  │ │  SQL   │
│ Adapter │ │ Adapter│ │ Adapter│ │ Adapter│
└─────────┘ └────────┘ └────────┘ └────────┘
```

---

## Technology Stack

### Core Dependencies

```toml
[project]
name = "idempotent-middleware"
version = "0.1.0"
requires-python = ">=3.10"

dependencies = [
    # Type Safety & Validation
    "pydantic>=2.6.0",
    "typing-extensions>=4.9.0",

    # ASGI Framework Support
    "starlette>=0.36.0",

    # Storage Backends
    "redis[async]>=5.0.1",  # Redis with async support

    # Observability
    "prometheus-client>=0.19.0",
    "structlog>=24.1.0",

    # Configuration
    "python-dotenv>=1.0.0",
    "pyyaml>=6.0.1",
]

[project.optional-dependencies]
dev = [
    # Testing
    "pytest>=7.4.4",
    "pytest-asyncio>=0.23.3",
    "pytest-cov>=4.1.0",
    "pytest-xdist>=3.3.0",
    "pytest-timeout>=2.1.0",
    "pytest-benchmark>=4.0.0",
    "httpx>=0.26.0",
    "fakeredis>=2.21.0",
    "freezegun>=1.4.0",
    "hypothesis>=6.82.0",

    # Code Quality
    "black>=24.1.0",
    "ruff>=0.1.0",
    "mypy>=1.8.0",
]

fastapi = ["fastapi>=0.109.0", "uvicorn[standard]>=0.27.0"]
sql = ["sqlalchemy[asyncio]>=2.0.25", "aiosqlite>=0.19.0"]
```

### Why These Libraries?

- **Pydantic 2.x**: Runtime validation, serialization, type safety for configs and records
- **redis-py 5.x**: Unified async/sync Redis client with built-in async support
- **structlog**: JSON-structured logging with context binding (trace_id, key prefix)
- **prometheus-client**: Standard metrics collection (histograms, counters, gauges)
- **fakeredis**: In-memory Redis for fast unit testing without Docker
- **freezegun**: Time mocking for TTL expiry tests

---

## Module Structure

```
idempotent_middleware/
├── __init__.py                    # Public API exports
├── py.typed                       # PEP 561 type marker
│
├── core/
│   ├── __init__.py
│   ├── fingerprint.py             # Request fingerprinting algorithm
│   ├── models.py                  # Pydantic models (Record, Config, State)
│   ├── state_machine.py           # State transition logic (NEW→RUNNING→COMPLETED)
│   ├── middleware.py              # Framework-agnostic middleware core
│   └── replay.py                  # Response reconstruction from stored artifact
│
├── storage/
│   ├── __init__.py
│   ├── base.py                    # Abstract StorageAdapter protocol
│   ├── memory.py                  # In-memory adapter (asyncio.Lock)
│   ├── file.py                    # File-based adapter (JSON + lock files)
│   ├── redis.py                   # Redis adapter (SET NX, Lua scripts)
│   └── sql.py                     # SQLAlchemy adapter (optional)
│
├── adapters/
│   ├── __init__.py
│   ├── asgi.py                    # ASGI middleware (Starlette)
│   ├── wsgi.py                    # WSGI middleware (Flask/Django)
│   └── fastapi.py                 # FastAPI-specific utilities
│
├── observability/
│   ├── __init__.py
│   ├── metrics.py                 # Prometheus metrics
│   └── logging.py                 # Structured logging setup
│
├── utils/
│   ├── __init__.py
│   ├── headers.py                 # Header filtering/canonicalization
│   ├── timing.py                  # TTL/lease expiry utilities
│   └── validation.py              # Key validation, size limits
│
├── config.py                      # Configuration models (Pydantic)
├── exceptions.py                  # Custom exceptions
└── cli.py                         # Optional: CLI inspector tool

tests/
├── conftest.py                    # Shared fixtures
├── unit/
│   ├── test_fingerprint.py
│   ├── test_state_machine.py
│   ├── test_headers.py
│   └── storage/
│       ├── test_memory.py
│       ├── test_file.py
│       └── test_redis.py
├── integration/
│   ├── test_middleware_flow.py
│   ├── test_fastapi_e2e.py
│   └── test_adapter_conformance.py
├── concurrency/
│   ├── test_race_conditions.py
│   └── test_deadlock_prevention.py
└── scenarios/
    ├── test_scenario_1_happy_path.py
    ├── test_scenario_2_conflict.py
    ├── test_scenario_3_concurrent.py
    ├── test_scenario_4_ttl_expiry.py
    ├── test_scenario_5_crash_recovery.py
    └── test_scenario_6_size_limits.py
```

---

## Core Algorithms

### 1. Request Fingerprinting Algorithm

**Purpose:** Generate deterministic hash to detect duplicate vs conflicting requests.

**Algorithm (SHA-256 based):**

```python
def compute_fingerprint(
    method: str,
    path: str,
    query_string: str,
    headers: Dict[str, str],
    body: bytes,
    included_headers: List[str] = ["content-type", "content-length"]
) -> str:
    """
    Deterministic fingerprint computation.

    Steps:
    1. Normalize path: lowercase, strip trailing /
    2. Sort query params: parse → sort keys → re-encode
    3. Canonicalize headers: lowercase keys, filter to included set, sort
    4. Hash body: SHA-256 of raw bytes
    5. Final hash: SHA-256 of concatenated components
    """

    # 1. Canonical path
    canonical_path = path.rstrip("/").lower() if path != "/" else "/"

    # 2. Stable query string
    if query_string:
        parsed = parse_qs(query_string, keep_blank_values=True)
        sorted_params = sorted(parsed.items())
        stable_qs = urlencode(sorted_params, doseq=True)
    else:
        stable_qs = ""

    # 3. Canonical headers (only include specified headers)
    selected_headers = {
        k.lower(): v.strip()
        for k, v in headers.items()
        if k.lower() in included_headers
    }
    sorted_headers = json.dumps(selected_headers, sort_keys=True)

    # 4. Body digest
    body_hash = hashlib.sha256(body).hexdigest()

    # 5. Final fingerprint
    components = [
        method.upper(),
        canonical_path,
        stable_qs,
        sorted_headers,
        body_hash
    ]
    fingerprint_input = "\n".join(components).encode("utf-8")

    return hashlib.sha256(fingerprint_input).hexdigest()
```

**Key Properties:**
- **Deterministic**: Same request → same fingerprint
- **Collision-resistant**: SHA-256 provides cryptographic strength
- **Order-independent**: Query params `?a=1&b=2` ≡ `?b=2&a=1`
- **Case-insensitive**: Paths and headers normalized
- **Selective**: Only meaningful headers included (excludes Date, User-Agent)

**Performance:** ~50-100µs per call (dominated by body hashing for large payloads)

---

### 2. Concurrency Control: Lease-Based Locking

**Challenge:** Multiple concurrent requests with same idempotency key must result in single execution.

**Solution:** Atomic compare-and-set with lease tokens.

#### In-Memory Implementation

```python
class MemoryStorageAdapter:
    def __init__(self):
        self._store: Dict[str, IdempotencyRecord] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    async def put_new_running(
        self,
        key: str,
        fingerprint: str,
        ttl_seconds: int,
        trace_id: Optional[str] = None
    ) -> LeaseResult:
        """Atomically acquire lease for new request."""

        # Ensure lock exists for this key
        async with self._global_lock:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()

        lock = self._locks[key]
        await lock.acquire()

        try:
            # Check if record exists (might be COMPLETED from previous request)
            existing = self._store.get(key)
            if existing:
                lock.release()
                return LeaseResult(success=False, existing_record=existing)

            # Create RUNNING record with lease token
            lease_token = str(uuid.uuid4())
            now = datetime.utcnow()
            record = IdempotencyRecord(
                key=key,
                fingerprint=fingerprint,
                state=RequestState.RUNNING,
                created_at=now,
                expires_at=now + timedelta(seconds=ttl_seconds),
                lease_token=lease_token,
                trace_id=trace_id
            )
            self._store[key] = record

            return LeaseResult(success=True, lease_token=lease_token)
        except Exception:
            lock.release()
            raise
```

#### Redis Implementation

```python
class RedisStorageAdapter:
    async def put_new_running(
        self,
        key: str,
        fingerprint: str,
        ttl_seconds: int,
        trace_id: Optional[str] = None
    ) -> LeaseResult:
        """Use Redis SET NX (set if not exists) for atomic lease."""
        lease_token = str(uuid.uuid4())

        record = IdempotencyRecord(
            key=key,
            fingerprint=fingerprint,
            state=RequestState.RUNNING,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(seconds=ttl_seconds),
            lease_token=lease_token,
            trace_id=trace_id
        )

        # SET key value NX EX ttl_seconds
        # Returns True if key was set, False if key exists
        success = await self.redis.set(
            f"idem:{key}",
            record.json(),
            nx=True,  # Only set if key doesn't exist
            ex=ttl_seconds
        )

        if success:
            return LeaseResult(success=True, lease_token=lease_token)
        else:
            # Key exists, fetch existing record
            existing_json = await self.redis.get(f"idem:{key}")
            existing = IdempotencyRecord.parse_raw(existing_json)
            return LeaseResult(success=False, existing_record=existing)
```

**Race Condition Guarantee:**
- `asyncio.Lock`: Provides mutual exclusion within single process
- Redis `SET NX`: Atomic operation across distributed processes
- Lease token: Prevents stale completions from crashed workers

---

### 3. State Machine Logic

**States:** `NEW → RUNNING → COMPLETED/FAILED`

**Pseudo-code from spec:**

```python
async def process_request(req):
    # Skip safe methods
    if not unsafe_method(req) or no_idempotency_key(req):
        return handler(req)

    key = req.header["Idempotency-Key"]
    fingerprint = compute_fingerprint(req)

    rec = storage.get(key)

    if rec is None:
        # NEW: Acquire lease and execute
        result = storage.put_new_running(key, fingerprint, ttl)

        if result.exists:
            # Race: another request beat us
            return handle_existing(result.record, fingerprint)

        # Execute handler
        response = handler(req)

        # Store result
        storage.complete(result.lease_token, response)

        return add_replay_headers(response, key, replay=False)

    else:
        # Record exists
        if rec.state in [COMPLETED, FAILED]:
            # Check fingerprint match
            if rec.fingerprint != fingerprint:
                return Response(409, body="Conflict: different request")

            # Replay stored response
            return replay(rec, key)

        if rec.state == RUNNING:
            # Concurrent duplicate
            return handle_running(rec, policy)
```

**Handle Running State:**

```python
async def handle_running(record, policy):
    if policy == "no-wait":
        return Response(409, headers={"Retry-After": "5"},
                       body="Request in progress")

    # Wait policy: poll until completed
    timeout = config.execution_timeout_s
    start = time.time()

    while time.time() - start < timeout:
        await asyncio.sleep(0.1)  # Poll interval

        updated = storage.get(record.key)
        if updated.state in [COMPLETED, FAILED]:
            return replay(updated, record.key)

    # Timeout
    return Response(425, headers={"Retry-After": "10"},
                   body="Execution timeout")
```

---

### 4. TTL & Cleanup Strategy

**Requirements:**
- Records expire after configurable TTL (default 24h)
- Cleanup removes expired entries to reclaim storage
- Lease expiry allows retry if worker crashes

**Implementation:**

```python
async def cleanup_loop(storage: StorageAdapter, interval_seconds: int = 300):
    """Background task: periodic cleanup of expired records."""
    while True:
        try:
            count = await storage.cleanup_expired()
            metrics.cleanup_counter.inc(count)
            logger.info("cleanup.completed", count=count)
        except Exception as e:
            logger.error("cleanup.failed", error=str(e))

        await asyncio.sleep(interval_seconds)

# Memory Adapter Cleanup
async def cleanup_expired(self) -> int:
    """Remove expired records from in-memory store."""
    now = datetime.utcnow()
    expired_keys = [
        key for key, record in self._store.items()
        if record.expires_at < now
    ]

    for key in expired_keys:
        async with self._global_lock:
            if key in self._store:
                del self._store[key]
            if key in self._locks and not self._locks[key].locked():
                del self._locks[key]

    return len(expired_keys)
```

**Redis:** TTL is built-in via `EX` parameter. No manual cleanup needed.

---

## Definition of Done

Every ticket must satisfy **ALL** criteria below before being considered complete:

### Code Quality
- [ ] All code follows PEP 8 style guidelines (enforced by `black` formatter)
- [ ] Type hints on all functions/methods (validated by `mypy --strict`)
- [ ] No linting errors (`ruff` or `flake8` passes)
- [ ] Docstrings on all public functions (Google or NumPy style)
- [ ] No commented-out code or debug print statements
- [ ] Error handling implemented for expected failure modes
- [ ] Logging added at appropriate levels (DEBUG/INFO/ERROR)

### Testing
- [ ] Unit tests written with **>90% coverage** for new code
- [ ] All tests pass locally (`pytest` exit code 0)
- [ ] Tests are deterministic (no flaky tests due to timing/randomness)
- [ ] Edge cases covered (empty inputs, boundary conditions, invalid data)
- [ ] Async tests use `pytest-asyncio` with proper fixtures
- [ ] Test names clearly describe what they verify (`test_<behavior>_<condition>_<expected_result>`)
- [ ] Fixtures/mocks properly cleaned up (no resource leaks)

### Integration
- [ ] Code integrates with existing modules without breaking changes
- [ ] Dependencies added to `pyproject.toml` with version constraints
- [ ] No circular imports or dependency issues
- [ ] Works with all supported Python versions (3.10, 3.11, 3.12)
- [ ] CI pipeline passes (all jobs green)

### Documentation
- [ ] Module-level docstring explains purpose and usage
- [ ] Complex algorithms have explanatory comments
- [ ] Configuration options documented (if applicable)
- [ ] Examples provided for non-trivial APIs
- [ ] README.md updated if public API changes

### Performance
- [ ] No obvious performance regressions (benchmarks if critical path)
- [ ] Resource cleanup (files closed, connections released, locks released)
- [ ] Memory leaks checked (for long-running operations)
- [ ] Timeouts set for network/blocking operations

### Security
- [ ] No hardcoded secrets or credentials
- [ ] Input validation for user-supplied data
- [ ] Sensitive data redacted from logs
- [ ] Dependencies scanned for known vulnerabilities (`pip-audit`)

### Review & Validation
- [ ] Code self-reviewed before marking complete
- [ ] Acceptance criteria from ticket description met
- [ ] Manual testing performed for happy path
- [ ] Error messages are clear and actionable

---

## Implementation Tickets

### Phase 0: Project Setup (Day 0 - 2 hours)

#### **Ticket 1: Project Structure & Dependencies**
- **Complexity:** Small
- **Dependencies:** None
- **Deliverables:**
  - `pyproject.toml` with all dependencies
  - Directory structure created
  - `.gitignore`, `.python-version`, `README.md`
  - Virtual environment documented

#### **Ticket 2: Configuration Module**
- **Complexity:** Small
- **Dependencies:** Ticket 1
- **Deliverables:**
  - `config.py` with Pydantic `Config` model
  - Environment variable loading
  - Validation rules (TTL > 0, methods in allowed set)
  - Unit tests

---

### Phase 1: Core Abstractions (Day 1 Morning - 4 hours)

#### **Ticket 3: Type Definitions**
- **Complexity:** Small
- **Dependencies:** Ticket 1
- **Deliverables:**
  - `models.py` with `State` enum, `Record`, `StoredResponse`
  - Pydantic models for serialization
  - Unit tests for model validation

#### **Ticket 4: Storage Adapter Interface**
- **Complexity:** Medium
- **Dependencies:** Ticket 3
- **Deliverables:**
  - `storage/base.py` with abstract `StorageAdapter` class
  - Method signatures: `get()`, `put_new_running()`, `complete()`, `fail()`, `cleanup_expired()`
  - `exceptions.py` with custom exceptions
  - Docstrings explaining contract

#### **Ticket 5: Request Fingerprinting**
- **Complexity:** Medium
- **Dependencies:** Ticket 3
- **Deliverables:**
  - `core/fingerprint.py` with `compute_fingerprint()` function
  - Canonical ordering of query params and headers
  - SHA-256 hashing
  - **15+ unit tests** (edge cases: empty body, no query, duplicate headers)

#### **Ticket 6: In-Memory Storage Adapter**
- **Complexity:** Medium
- **Dependencies:** Ticket 4
- **Deliverables:**
  - `storage/memory.py` implementing `StorageAdapter`
  - Thread-safe using `asyncio.Lock`
  - Lease token generation and validation
  - **20+ unit tests** including concurrent access simulation

---

### Phase 2: Middleware Core (Day 1 Afternoon - 5 hours)

#### **Ticket 7: Header Filtering Utilities**
- **Complexity:** Small
- **Dependencies:** Ticket 3
- **Deliverables:**
  - `utils/headers.py` with filtering functions
  - Remove volatile headers: Date, Server, Connection, etc.
  - Add replay headers: `Idempotent-Replay`, `Idempotency-Key`
  - **8+ unit tests**

#### **Ticket 8: Response Replay Logic**
- **Complexity:** Small
- **Dependencies:** Ticket 7
- **Deliverables:**
  - `core/replay.py` to reconstruct response from stored artifact
  - Handle base64-encoded body
  - Apply header filtering
  - Unit tests

#### **Ticket 9: State Machine Handler**
- **Complexity:** Large
- **Dependencies:** Tickets 4, 5, 7, 8
- **Deliverables:**
  - `core/state_machine.py` implementing pseudo-flow from spec
  - Handle NEW → RUNNING → COMPLETED/FAILED transitions
  - Fingerprint conflict detection (409)
  - Wait vs no-wait policy for RUNNING state
  - **25+ unit tests** covering all state transitions

#### **Ticket 10: Core Middleware Integration**
- **Complexity:** Large
- **Dependencies:** Ticket 9
- **Deliverables:**
  - `core/middleware.py` orchestrating full request/response flow
  - Extract idempotency key from headers
  - Validate key format (≤200 chars)
  - Skip safe methods (GET, HEAD, OPTIONS)
  - Enforce max body size limits
  - **Integration tests** with mock handlers

---

### Phase 3: Framework Adapters (Day 2 Morning - 3 hours)

#### **Ticket 11: ASGI Middleware Adapter**
- **Complexity:** Medium
- **Dependencies:** Ticket 10
- **Deliverables:**
  - `adapters/asgi.py` wrapper for Starlette/FastAPI
  - Convert ASGI request/response to internal types
  - Async request handling
  - Integration test with FastAPI TestClient

#### **Ticket 12: WSGI Middleware Adapter**
- **Complexity:** Medium (Nice-to-have)
- **Dependencies:** Ticket 10
- **Deliverables:**
  - `adapters/wsgi.py` wrapper for Flask/Django
  - Convert WSGI environ/response to internal types
  - Integration test with Flask test client

---

### Phase 4: Observability (Day 2 Afternoon - 2 hours)

#### **Ticket 13: Metrics Collection**
- **Complexity:** Medium
- **Dependencies:** Ticket 10
- **Deliverables:**
  - `observability/metrics.py` with Prometheus metrics
  - Counter: `idem_requests_total{result}`
  - Histogram: `idem_execution_ms`
  - Gauge: `idem_keys_active`
  - Unit tests verifying metric updates

#### **Ticket 14: Structured Logging**
- **Complexity:** Small
- **Dependencies:** Ticket 10
- **Deliverables:**
  - `observability/logging.py` with structlog integration
  - Log state transitions with key prefix, trace_id
  - JSON output support
  - Unit tests

#### **Ticket 15: TTL Cleanup Background Job**
- **Complexity:** Medium
- **Dependencies:** Ticket 6
- **Deliverables:**
  - `core/cleanup.py` with periodic cleanup task
  - Configurable interval (default 5 minutes)
  - Graceful shutdown
  - Unit tests with time mocking

---

### Phase 5: Testing & Hardening (Day 2 Evening - 3 hours)

#### **Ticket 16: Conformance Test Suite**
- **Complexity:** Large
- **Dependencies:** Tickets 10, 11
- **Deliverables:**
  - `tests/scenarios/` with 6 scenario test files
  - **Test 1:** Happy path (first request + replay)
  - **Test 2:** Conflict detection (different fingerprint → 409)
  - **Test 3:** Concurrent execution (race condition simulation)
  - **Test 4:** TTL expiry (key reuse after expiration)
  - **Test 5:** Crash recovery (lease expiry)
  - **Test 6:** Size limits (oversized body rejection)
  - **100+ tests total**

#### **Ticket 17: End-to-End Integration Tests**
- **Complexity:** Medium
- **Dependencies:** Ticket 11, 16
- **Deliverables:**
  - `tests/integration/test_fastapi_e2e.py` with real HTTP requests
  - Full request/response cycle
  - Concurrent request testing with threading
  - All conformance scenarios pass in real framework

---

### Phase 6: Nice-to-Have (Post-Weekend)

#### **Ticket 18: File-Based Storage Adapter**
- **Complexity:** Large
- **Dependencies:** Ticket 4
- **Deliverables:**
  - `storage/file.py` with JSON file storage
  - Lock files for exclusive access
  - Atomic writes (temp file + rename)
  - Unit tests

#### **Ticket 19: Redis Storage Adapter**
- **Complexity:** Medium
- **Dependencies:** Ticket 4
- **Deliverables:**
  - `storage/redis.py` using redis-py async client
  - `SET NX` for atomic lease acquisition
  - Lua script for compare-and-swap completion
  - Integration tests with fakeredis

#### **Ticket 20: CLI Inspector Tool**
- **Complexity:** Medium
- **Dependencies:** Tickets 6, 18
- **Deliverables:**
  - `cli.py` with commands: `list`, `get`, `cleanup`, `stats`
  - Pretty-printed JSON output
  - Support memory and file adapters

#### **Ticket 21: Security Hardening**
- **Complexity:** Medium
- **Dependencies:** Tickets 6, 18
- **Deliverables:**
  - `security.py` with body encryption (optional)
  - Key validation (min entropy)
  - Rate limiting per client
  - Security best practices documentation

#### **Ticket 22: Demo API Application**
- **Complexity:** Medium
- **Dependencies:** Ticket 11
- **Deliverables:**
  - `examples/demo_api.py` FastAPI app with middleware
  - Example endpoints demonstrating replay behavior
  - README with curl examples
  - Docker compose setup (optional)

#### **Ticket 23: Documentation**
- **Complexity:** Small
- **Dependencies:** Tickets 10, 11, 2
- **Deliverables:**
  - Installation guide
  - Quick start for FastAPI/Flask
  - Configuration reference
  - API documentation (Sphinx/MkDocs)
  - Troubleshooting guide

---

## QA Testing Strategy

### Test Framework Stack

```python
# requirements-dev.txt
pytest>=7.4.4
pytest-asyncio>=0.23.3      # Async test support
pytest-cov>=4.1.0           # Coverage reporting
pytest-xdist>=3.3.0         # Parallel execution
pytest-timeout>=2.1.0       # Prevent hanging tests
pytest-benchmark>=4.0.0     # Performance benchmarks
httpx>=0.26.0              # Async HTTP client for testing
fakeredis>=2.21.0          # In-memory Redis for unit tests
freezegun>=1.4.0           # Time mocking for TTL tests
hypothesis>=6.82.0         # Property-based testing
```

### Test Categories & Coverage Goals

#### 1. **Unit Tests** (Target: 95% coverage)
- **Fingerprinting:** 15 tests (query ordering, header normalization, body hashing)
- **State Machine:** 12 tests (all state transitions, edge cases)
- **Header Filtering:** 8 tests (volatile header removal, replay headers)
- **Storage Adapters:** 20 tests each (thread safety, lease management, TTL)
- **Config Validation:** 10 tests (constraint validation, defaults)

**Run command:**
```bash
pytest tests/unit -v --cov=idempotent_middleware --cov-report=html
```

#### 2. **Integration Tests** (Target: 90% coverage)
- **Middleware Flow:** 25 tests (end-to-end request/response cycle)
- **Framework Integration:** 15 tests (FastAPI TestClient, real HTTP)
- **Adapter Conformance:** 15 tests (contract compliance across all adapters)
- **Real Backends:** 10 tests (testcontainers for Redis, SQLite)

**Run command:**
```bash
pytest tests/integration -v -m integration
```

#### 3. **Concurrency Tests** (Critical for correctness)
- **Race Conditions:** 15 tests (concurrent duplicates, lock contention)
- **Deadlock Prevention:** 10 tests (lease expiry, timeout handling)
- **Thread Safety:** 15 tests (parallel adapter operations)

**Example test:**
```python
@pytest.mark.concurrency
async def test_concurrent_duplicates_single_execution(memory_adapter):
    """Only one of 10 concurrent duplicates executes handler."""
    execution_count = []

    async def handler():
        execution_count.append(1)
        await asyncio.sleep(0.1)  # Simulate slow operation
        return Response(200, {}, b"done")

    # Launch 10 concurrent requests with same key
    tasks = [middleware.process(request) for _ in range(10)]
    responses = await asyncio.gather(*tasks)

    assert len(execution_count) == 1  # Handler called exactly once
    assert all(r.status == 200 for r in responses)
```

**Run command:**
```bash
pytest tests/concurrency -v -m concurrency
```

#### 4. **Scenario Tests** (100+ tests covering spec section 14)

| Scenario | Test File | Test Count | Key Assertions |
|----------|-----------|------------|----------------|
| 1. Happy Path | `test_scenario_1_happy_path.py` | 15 | First request executes, replay returns identical response |
| 2. Conflict | `test_scenario_2_conflict.py` | 18 | Different fingerprint → 409, error explains mismatch |
| 3. Concurrent | `test_scenario_3_concurrent.py` | 20 | Race conditions handled, single execution guaranteed |
| 4. TTL Expiry | `test_scenario_4_ttl_expiry.py` | 15 | Expired keys allow new execution, cleanup works |
| 5. Crash Recovery | `test_scenario_5_crash_recovery.py` | 12 | Lease expiry enables retry, no permanent deadlocks |
| 6. Size Limits | `test_scenario_6_size_limits.py` | 10 | Oversized requests rejected, at-limit requests work |

**Run command:**
```bash
pytest tests/scenarios -v
```

#### 5. **Performance Benchmarks** (Nice-to-have)
- Replay throughput: > 1000 req/s
- Fingerprint computation: < 100µs
- Middleware overhead: < 1ms
- Memory usage under load: < 100MB for 10k cached responses

**Run command:**
```bash
pytest tests/performance --benchmark-only
```

### Coverage Requirements

**Minimum thresholds:**
- **Overall:** 90% line coverage
- **Critical paths:** 100% coverage
  - Fingerprint generation
  - State transitions
  - Lock acquisition/release
  - Replay logic
- **Adapters:** 95% each
- **Middleware core:** 95%

**Enforcement:**
```ini
# pytest.ini
[pytest]
addopts =
    --cov=idempotent_middleware
    --cov-report=html
    --cov-report=term-missing
    --cov-fail-under=90
    --cov-branch
```

### CI/CD Pipeline

```yaml
# .github/workflows/test.yml
name: Test Suite

on: [push, pull_request]

jobs:
  unit-tests:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12"]
    steps:
      - uses: actions/checkout@v3
      - name: Install dependencies
        run: pip install -e ".[dev]"
      - name: Run unit tests
        run: pytest tests/unit -v -n auto

  integration-tests:
    runs-on: ubuntu-latest
    services:
      redis:
        image: redis:7-alpine
        ports:
          - 6379:6379
    steps:
      - uses: actions/checkout@v3
      - name: Run integration tests
        run: pytest tests/integration -v

  concurrency-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run concurrency tests
        run: pytest tests/concurrency -v --timeout=60

  coverage:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run tests with coverage
        run: pytest --cov --cov-report=xml
      - name: Upload to Codecov
        uses: codecov/codecov-action@v3
```

---

## Parallelization Strategy: Multi-Agent Development

### Agent Roles & Specializations

To maximize parallel work, assign tickets to specialized agents:

**Agent 1: "Core Logic Specialist"**
- Focus: Algorithms, state machines, business logic
- Skills: Complex logic, edge cases, mathematical correctness

**Agent 2: "Storage & Infrastructure Specialist"**
- Focus: Storage adapters, persistence, concurrency primitives
- Skills: Database design, locking mechanisms, async I/O

**Agent 3: "Integration & Framework Specialist"**
- Focus: Framework adapters, middleware wrappers, HTTP handling
- Skills: FastAPI/Flask internals, ASGI/WSGI specs

**Agent 4: "Testing & QA Specialist"**
- Focus: Test suites, fixtures, conformance testing
- Skills: Property-based testing, concurrency testing, test design

**Agent 5: "Observability & Tooling Specialist"**
- Focus: Metrics, logging, CLI tools, documentation
- Skills: Prometheus, structured logging, developer experience

---

### Parallelization by Phase

#### **Phase 0: Setup (Sequential - 1 agent)**
**Total Time: 2 hours → 2 hours (no parallelization benefit)**

- Ticket 1: Project structure (must complete first)
- Ticket 2: Configuration module (depends on Ticket 1)

**Why Sequential:** Foundation must exist before parallel work begins.

---

#### **Phase 1: Core Abstractions (3 agents in parallel)**
**Sequential Time: 11 hours → Parallel Time: 4 hours (63% faster)**

| Agent | Tickets | Time | Dependencies |
|-------|---------|------|--------------|
| **Agent 1** | Ticket 5: Fingerprinting | 3h | Ticket 3 |
| **Agent 2** | Ticket 3: Types<br>Ticket 4: Storage Interface<br>Ticket 6: Memory Adapter | 1h + 2h + 2h = 5h | Ticket 1 (setup) |
| **Agent 3** | *(Idle - waiting for core)* | 0h | - |
| **Agent 4** | *(Writing test fixtures in parallel)* | 2h | Ticket 3 |
| **Agent 5** | *(Idle - not needed yet)* | 0h | - |

**Parallel Execution:**
```
Hour 0-1:  Agent 2 → Ticket 3 (Types)
Hour 1-2:  Agent 2 → Ticket 4 (Storage Interface) | Agent 1 → Ticket 5 (Fingerprinting)
Hour 2-4:  Agent 2 → Ticket 6 (Memory Adapter) | Agent 1 → Ticket 5 (continues)
           Agent 4 → Test fixtures (conftest.py)
```

**Critical Path:** Agent 2 (Ticket 3 → 4 → 6) = 5 hours
**But:** Agent 1 can start Ticket 5 after hour 1 (Types complete)

**Optimized Time: 4 hours** (Agent 2's path, with Agent 1 finishing at hour 4)

---

#### **Phase 2: Middleware Core (4 agents in parallel)**
**Sequential Time: 13 hours → Parallel Time: 5 hours (62% faster)**

| Agent | Tickets | Time | Dependencies |
|-------|---------|------|--------------|
| **Agent 1** | Ticket 9: State Machine | 4h | Tickets 4, 5, 7, 8 |
| **Agent 2** | *(Idle or helping with tests)* | 0h | - |
| **Agent 3** | Ticket 7: Header Filtering<br>Ticket 8: Replay Logic | 1h + 1h = 2h | Ticket 3 |
| **Agent 4** | Unit tests for Tickets 5, 6 | 2h | Tickets 5, 6 complete |
| **Agent 5** | *(Idle - not needed yet)* | 0h | - |

**Then (after Ticket 9 completes):**
| Agent | Tickets | Time | Dependencies |
|-------|---------|------|--------------|
| **Agent 1** | Ticket 10: Core Middleware | 4h | Ticket 9 |
| **Agent 4** | Unit tests for Ticket 9 | 2h | Ticket 9 |

**Parallel Execution:**
```
Hour 0-1:  Agent 3 → Ticket 7 (Headers)
Hour 1-2:  Agent 3 → Ticket 8 (Replay) | Agent 4 → Unit tests (Tickets 5,6)
Hour 2-6:  Agent 1 → Ticket 9 (State Machine - 4h)
           Agent 4 → Continues tests
Hour 6-10: Agent 1 → Ticket 10 (Core Middleware - 4h)
           Agent 4 → Tests for Ticket 9
```

**Critical Path:** Ticket 7 → 8 → 9 → 10 = 1h + 1h + 4h + 4h = 10 hours
**With parallel testing:** Tests happen during development, no added time

**Optimized Time: 5 hours** (tickets can overlap more with test-driven development)

---

#### **Phase 3: Framework Adapters (2 agents in parallel)**
**Sequential Time: 5 hours → Parallel Time: 3 hours (40% faster)**

| Agent | Tickets | Time | Dependencies |
|-------|---------|------|--------------|
| **Agent 3** | Ticket 11: ASGI Adapter | 3h | Ticket 10 |
| **Agent 2** | Ticket 12: WSGI Adapter (Nice-to-have) | 3h | Ticket 10 |

**Parallel Execution:**
```
Hour 0-3:  Agent 3 → Ticket 11 (ASGI)
           Agent 2 → Ticket 12 (WSGI) - in parallel
```

**Optimized Time: 3 hours** (both adapters developed simultaneously)

---

#### **Phase 4: Observability (3 agents in parallel)**
**Sequential Time: 6 hours → Parallel Time: 3 hours (50% faster)**

| Agent | Tickets | Time | Dependencies |
|-------|---------|------|--------------|
| **Agent 5** | Ticket 13: Metrics<br>Ticket 14: Logging | 2h + 1h = 3h | Ticket 10 |
| **Agent 2** | Ticket 15: Cleanup Job | 2h | Ticket 6 |
| **Agent 4** | Tests for observability | 2h | Tickets 13, 14 |

**Parallel Execution:**
```
Hour 0-2:  Agent 5 → Ticket 13 (Metrics) | Agent 2 → Ticket 15 (Cleanup)
Hour 2-3:  Agent 5 → Ticket 14 (Logging)
Hour 0-3:  Agent 4 → Tests (concurrent with development)
```

**Optimized Time: 3 hours** (all tickets run in parallel)

---

#### **Phase 5: Testing & Hardening (4 agents in parallel)**
**Sequential Time: 8 hours → Parallel Time: 4 hours (50% faster)**

| Agent | Tickets | Time | Dependencies |
|-------|---------|------|--------------|
| **Agent 4** | Ticket 16: Conformance Tests (Scenarios 1-3) | 4h | Tickets 10, 11 |
| **Agent 1** | Ticket 16: Conformance Tests (Scenarios 4-6) | 4h | Tickets 10, 11 |
| **Agent 3** | Ticket 17: E2E Integration Tests | 3h | Ticket 11, 16 |
| **Agent 2** | *(Helping with scenario tests)* | - | - |

**Parallel Execution:**
```
Hour 0-4:  Agent 4 → Scenarios 1-3 (Happy path, Conflict, Concurrent)
           Agent 1 → Scenarios 4-6 (TTL, Crash recovery, Size limits)
Hour 4-7:  Agent 3 → Ticket 17 (E2E tests)
```

**Optimized Time: 4 hours** (scenario tests split across agents)

---

### Summary: Sequential vs Parallel

| Phase | Sequential Time | Parallel Time (5 agents) | Speedup |
|-------|----------------|--------------------------|---------|
| Phase 0: Setup | 2h | 2h | 0% (sequential) |
| Phase 1: Core | 11h | 4h | **63% faster** |
| Phase 2: Middleware | 13h | 5h | **62% faster** |
| Phase 3: Adapters | 5h | 3h | **40% faster** |
| Phase 4: Observability | 6h | 3h | **50% faster** |
| Phase 5: Testing | 8h | 4h | **50% faster** |
| **Total MVP** | **45h** | **21h** | **53% faster** |

---

### Optimal Agent Allocation

#### **3 Agents (Realistic for Weekend)**
- **Agent 1 (Eric - Python Engineer):** Core logic, algorithms, state machine
- **Agent 2 (Backend Specialist):** Storage adapters, concurrency, infrastructure
- **Agent 3 (QA Specialist):** All testing, fixtures, conformance suites

**Estimated Time: ~25 hours** (weekends become achievable)

#### **5 Agents (Maximum Parallelization)**
- **Agent 1:** Core logic
- **Agent 2:** Storage & infrastructure
- **Agent 3:** Framework adapters
- **Agent 4:** Testing & QA
- **Agent 5:** Observability & tooling

**Estimated Time: ~21 hours** (diminishing returns after 5 agents)

---

### Coordination Requirements

#### Communication Touchpoints
1. **After Phase 0:** Align on project structure and config schema
2. **After Phase 1:** Review storage adapter interface (contract)
3. **Mid Phase 2:** Sync on state machine behavior (critical path)
4. **After Phase 2:** Integration checkpoint (core middleware ready)
5. **After Phase 5:** Final testing review

#### Shared Artifacts (Potential Conflicts)
- `conftest.py` - test fixtures (Agent 4 owns, others contribute)
- `models.py` - core types (Agent 2 creates, others consume)
- `exceptions.py` - custom exceptions (shared, needs coordination)
- `pyproject.toml` - dependencies (lock file coordination needed)

#### Conflict Resolution Strategy
- **Option 1:** Feature branches per ticket, PR-based merges
- **Option 2:** Pair programming for shared modules (models, exceptions)
- **Option 3:** Contract-first development (define interfaces, then implement in parallel)

---

### Recommended Parallelization Plan (3 Agents)

#### **Weekend Timeline with 3 Agents**

**Friday Evening (2 hours):**
- Agent 1 → Setup (Tickets 1-2)

**Saturday Morning (4 hours):**
- Agent 1 → Tickets 3, 5 (Types, Fingerprinting)
- Agent 2 → Tickets 4, 6 (Storage interface, Memory adapter)
- Agent 3 → Test fixtures setup

**Saturday Afternoon (5 hours):**
- Agent 1 → Tickets 9, 10 (State machine, Middleware core)
- Agent 2 → Tickets 7, 8 (Headers, Replay)
- Agent 3 → Unit tests for Phase 1

**Sunday Morning (4 hours):**
- Agent 1 → Ticket 11 (ASGI adapter)
- Agent 2 → Tickets 13, 15 (Metrics, Cleanup)
- Agent 3 → Ticket 14 (Logging)

**Sunday Afternoon (6 hours):**
- Agent 1 → Ticket 16 (Scenarios 1-3)
- Agent 2 → Ticket 16 (Scenarios 4-6)
- Agent 3 → Ticket 17 (E2E tests)

**Total: ~21 hours** spread across 3 agents = **7 hours per agent** (doable in a weekend!)

---

## Timeline & Phases

### Weekend Implementation Plan (MVP Scope)

#### **Day 0 (Friday Evening): Setup - 2 hours**
- Tickets 1-2: Project structure + configuration
- Output: Runnable Python package with config loading

#### **Day 1 (Saturday): Core Implementation - 9 hours**

**Morning (4 hours):**
- Tickets 3-6: Types, storage interface, fingerprinting, in-memory adapter
- Output: Core abstractions ready, fingerprinting tested

**Afternoon (5 hours):**
- Tickets 7-10: Headers, replay, state machine, middleware core
- Output: Framework-agnostic middleware functional

#### **Day 2 (Sunday): Integration & Testing - 8 hours**

**Morning (3 hours):**
- Ticket 11: ASGI adapter for FastAPI
- Output: Working FastAPI integration

**Afternoon (3 hours):**
- Tickets 13-15: Metrics, logging, cleanup
- Output: Observable, production-ready

**Evening (2 hours):**
- Tickets 16-17: Conformance tests + E2E tests
- Output: **Fully tested MVP** with 90%+ coverage

### Total MVP Effort: ~19 hours

---

### Post-Weekend Enhancements

#### **Week 2: Additional Adapters**
- Ticket 18: File-based storage (3 hours)
- Ticket 19: Redis storage (2 hours)
- Ticket 12: WSGI adapter for Flask (2 hours)

#### **Week 3: Production Hardening**
- Ticket 21: Security hardening (3 hours)
- Ticket 22: Demo API application (2 hours)
- Ticket 20: CLI inspector tool (2 hours)

#### **Week 4: Documentation & Release**
- Ticket 23: Documentation (4 hours)
- Performance benchmarking (2 hours)
- Release preparation (1 hour)

---

## Success Criteria

### MVP Acceptance (Weekend Goal)

✅ **Functional Requirements:**
- [ ] Idempotent POST/PUT/PATCH/DELETE requests
- [ ] Replay identical responses within TTL
- [ ] Detect and reject conflicting requests (409)
- [ ] Handle concurrent duplicates (single execution)
- [ ] TTL expiry allows key reuse
- [ ] Size limits enforced

✅ **Technical Requirements:**
- [ ] Framework-agnostic core
- [ ] ASGI middleware for FastAPI
- [ ] In-memory storage adapter
- [ ] 90%+ test coverage
- [ ] All 6 conformance scenarios pass
- [ ] Prometheus metrics exposed
- [ ] Structured logging

✅ **Documentation:**
- [ ] README with installation + quick start
- [ ] Configuration reference
- [ ] Example FastAPI application

### Post-MVP Enhancements

🎯 **Production-Ready:**
- Redis adapter for distributed systems
- File adapter for persistence
- Security hardening (encryption, rate limiting)
- CLI inspector tool
- Comprehensive API documentation

---

## Key Design Decisions Summary

1. **ASGI-first with framework-agnostic core**: Balance performance and flexibility
2. **Pydantic for all data models**: Runtime validation + type safety
3. **SHA-256 for fingerprinting**: Cryptographic collision resistance
4. **Atomic operations for concurrency**: `asyncio.Lock` (in-memory), `SET NX` (Redis)
5. **Lease tokens prevent stale completions**: UUID-based lease validation
6. **Background cleanup task**: Reclaim storage from expired entries
7. **Pluggable storage adapters**: Abstract interface allows swapping backends
8. **Comprehensive testing strategy**: 400+ tests across unit/integration/concurrency/scenarios

---

## References

- Spec: `/Users/toddpickell/code/learn_python/more_on_my_gh/idempotent_middleware/README.md`
- Stripe Idempotency: https://stripe.com/docs/api/idempotent_requests
- RFC 7231 (HTTP Idempotency): https://tools.ietf.org/html/rfc7231#section-4.2
- Pydantic Docs: https://docs.pydantic.dev/
- FastAPI Testing: https://fastapi.tiangolo.com/tutorial/testing/
