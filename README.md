# Idempotency Key Middleware

## 1) Context
APIs that perform side effects (charge card, create order, send email) must tolerate client/network retries without duplicating the effect. Idempotency keys let clients safely retry a *logically single* operation.

## 2) Problem
Given repeated requests with the same **Idempotency-Key**, ensure the backend:
- Executes the side effect **at most once**.
- Returns the **same response** for subsequent retries within a time window.
- Handles concurrent duplicates (race) without double-executing.

## 3) Goals
- **Single-flight execution** per (key, *request fingerprint*).
- **Replay identical response** for matching retries.
- **TTL** for stored results; eviction strategy.
- **Pluggable persistence**: in-memory, file, database/redis/kv.
- Minimal footprint; works as a library or gateway/middleware.

## 4) Non-Goals
- Global distributed exactly-once semantics (we provide *at-most-once per key* within a scope).
- Streaming body replay for arbitrarily large payloads (we bound size).
- Cross-API multi-step sagas (out of scope).

---

## 5) Client Contract

### Headers
- `Idempotency-Key` (required for unsafe methods): opaque string (≤ 200 chars).  
- `Idempotency-TTL` (optional): hint in seconds; server may clamp to policy.

### Methods Covered
- **Unsafe**: `POST`, `PUT`, `PATCH`, `DELETE` → middleware enforced.  
- **Safe**: `GET`, `HEAD`, `OPTIONS` bypass by default (configurable).

### Status Codes & Errors
- `200–299/3xx/4xx/5xx`: stored and replayed as-is (see header filtering).  
- `409 Conflict`: same key used with a **different fingerprint**.  
- `422 Unprocessable Entity`: malformed/unsupported key.  
- `425 Too Early`: optional for early-retry flow control (if using locks + backoff).  
- `409 In-Progress` (or `202 Accepted`): if a concurrent request with same key is already executing and policy is “don’t wait”.

---

## 6) Core Concepts

### 6.1 Request Fingerprint
Keys must not collide across **different requests**. Compute a deterministic fingerprint:

```
fingerprint = hash(
  method + "\n" +
  canonical_path + "\n" +          
  stable_query_string + "\n" +     
  canonical_headers + "\n" +       
  body_digest                       
)
```

### 6.2 State Machine (per key)
- `NEW` → no record → acquire lock → `RUNNING`.
- `RUNNING` → concurrent duplicate:
  - **wait** policy: block until completed → return stored response.
  - **no-wait** policy: return `409 In-Progress` or `202` with `Retry-After`.
- `COMPLETED` → return cached response (until TTL expires).
- `FAILED` → store response too; still replay the failure.

### 6.3 Stored Artifact
- `status_code`
- `headers` (filtered)
- `body` (bytes or reference)
- `request_fingerprint`
- `created_at`, `expires_at`
- `execution_time_ms`
- optional metadata (`trace_id`, etc.)

### 6.4 Header Filtering on Replay
Strip volatile headers:
- Remove: `Date`, `Server`, `Connection`, `Transfer-Encoding`, `Keep-Alive`, `Trailer`, `Upgrade`.
- Optionally remove `Set-Cookie`.
- Add: `Idempotent-Replay: true`, `Idempotency-Key: <key>`.

---

## 7) Persistence Adapter Interface

```
get(key) -> Record | null
put_new_running(key, fingerprint, ttl_s, meta) -> {ok, lease_token} | {exists, record_or_state}
complete(lease_token, result_record) -> ok
fail(lease_token, result_record) -> ok
refresh_ttl(key, extra_s) -> ok
cleanup_expired(now) -> count
```

Adapters:
- **In-memory** (concurrent map + locks).  
- **File** (JSON blobs + lock files).  
- **DB/KV** (SQL table or Redis).  

---

## 8) Concurrency & Locks
- **Lease** with expiry to prevent deadlocks.
- Configurable execution timeout.
- Policy for handling concurrent `RUNNING` requests: wait or return conflict.

---

## 9) TTL, Size Limits, and Eviction
- Default TTL: 24h (configurable).
- Hard limits: body size, header size, max keys.
- Cleanup job for expired entries.

---

## 10) Middleware Behavior (Pseudo-Flow)

```
on_request(req):
  if not unsafe_method(req) or no key:
    return handler(req)

  key = req.header["Idempotency-Key"]
  fp  = fingerprint(req)

  rec = store.get(key)

  if rec == null:
    res = store.put_new_running(key, fp, ttl)
    if res.exists: return handle_existing(...)
    result = handler(req)
    store.complete(res.lease, result)
    return attach_replay_headers(result, key)

  else:
    if rec.state == COMPLETED or FAILED:
      if rec.fingerprint != fp: return 409 Conflict
      return replay(rec, key)
    if rec.state == RUNNING:
      return handle_running(rec, policy)
```

---

## 11) Observability
Metrics:
- `idem.requests_total{result=[new, replay, conflict, in_progress]}`  
- `idem.execution_ms_bucket` (histogram)  
- `idem.keys_active`

Logs:
- Log lifecycle transitions (`RUNNING→COMPLETED`, etc.) with key prefix and trace ID.

---

## 12) Security
- Treat keys as secrets.
- Encrypt body storage if persistent.
- Strong key entropy (UUIDv4 or ≥120 bits random).
- Rate-limit key brute force.

---

## 13) Configuration
```
enabled_methods: ["POST","PUT","PATCH","DELETE"]
default_ttl_s: 86400
wait_policy: "wait" | "no-wait"
execution_timeout_s: 30
max_body_bytes: 1048576
adapter: "memory" | "file" | "redis" | "sql"
```

---

## 14) Test Plan
1. Happy path → replay identical.
2. Conflict → 409 on different fingerprint.
3. Concurrent → only one executes.
4. TTL expiry → key reused.
5. Crash recovery → lease expiry triggers retry.
6. Large body limit → capped or rejected.

---

## 15) Example Stored Record

```json
{
  "key": "abc123",
  "fingerprint": "e3b0c44298fc1c149afbf4c8996fb924…",
  "state": "COMPLETED",
  "response": {
    "status": 201,
    "headers": { "Content-Type": "application/json" },
    "body_b64": "eyJpZCI6ICIxMjM0NSJ9"
  },
  "created_at": "2025-10-01T01:02:03Z",
  "expires_at": "2025-10-02T01:02:03Z",
  "execution_time_ms": 142
}
```

---

## 16) Deliverables (Weekend Scope)
- [ ] Fingerprinting logic.  
- [ ] Middleware with state machine.  
- [ ] In-memory adapter.  
- [ ] Replay headers.  
- [ ] Config + metrics.  
- [ ] Conformance tests.  

**Nice-to-have:** file adapter, CLI inspector, demo API.

---
