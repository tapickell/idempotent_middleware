"""Prometheus metrics for idempotency middleware.

This module provides Prometheus metrics to monitor middleware performance
and behavior. Metrics include:

- Request counters by result type (new, replay, conflict, etc.)
- Execution time histograms
- Active keys gauge
- Cleanup operation tracking

Examples:
    Recording a replayed request::

        from idempotent_middleware.observability.metrics import record_request

        record_request(result="replay", status_code=200)

    Recording execution time::

        from idempotent_middleware.observability.metrics import record_execution_time

        record_execution_time(execution_time_ms=150)

    Recording cleanup operations::

        from idempotent_middleware.observability.metrics import record_cleanup

        record_cleanup(records_removed=42)
"""

from prometheus_client import Counter, Gauge, Histogram

# Request counter by result type
# Labels: result (new, replay, conflict, error), status_code
requests_total = Counter(
    "idempotency_requests_total",
    "Total number of requests processed by idempotency middleware",
    ["result", "status_code"],
)

# Execution time histogram (milliseconds)
# Only tracks new executions, not replays
execution_time_ms = Histogram(
    "idempotency_execution_time_ms",
    "Request execution time in milliseconds (new executions only)",
    buckets=[
        10,
        25,
        50,
        100,
        250,
        500,
        1000,
        2500,
        5000,
        10000,
    ],  # 10ms to 10s
)

# Active keys gauge
# Tracks number of keys currently in RUNNING state
active_keys = Gauge(
    "idempotency_active_keys",
    "Number of idempotency keys currently in RUNNING state",
)

# Cleanup operations counter
cleanup_operations = Counter(
    "idempotency_cleanup_operations_total",
    "Total number of cleanup operations performed",
)

# Cleanup records removed counter
cleanup_records_removed = Counter(
    "idempotency_cleanup_records_removed_total",
    "Total number of expired records removed by cleanup",
)


def record_request(result: str, status_code: int) -> None:
    """Record a processed request in metrics.

    Args:
        result: The result type (new, replay, conflict, error, timeout)
        status_code: HTTP status code of the response

    Examples:
        >>> record_request("replay", 200)
        >>> record_request("conflict", 409)
        >>> record_request("error", 500)
    """
    requests_total.labels(result=result, status_code=str(status_code)).inc()


def record_execution_time(exec_time_ms: int) -> None:
    """Record request execution time.

    This should only be called for new executions, not replays.

    Args:
        exec_time_ms: Execution time in milliseconds

    Examples:
        >>> record_execution_time(150)
    """
    execution_time_seconds = exec_time_ms / 1000.0  # Convert to seconds
    execution_time_ms.observe(execution_time_seconds)


def increment_active_keys() -> None:
    """Increment the active keys gauge.

    Called when a new RUNNING record is created.

    Examples:
        >>> increment_active_keys()
    """
    active_keys.inc()


def decrement_active_keys() -> None:
    """Decrement the active keys gauge.

    Called when a RUNNING record transitions to COMPLETED or FAILED.

    Examples:
        >>> decrement_active_keys()
    """
    active_keys.dec()


def record_cleanup(records_removed: int) -> None:
    """Record a cleanup operation.

    Args:
        records_removed: Number of expired records removed

    Examples:
        >>> record_cleanup(42)
    """
    cleanup_operations.inc()
    cleanup_records_removed.inc(records_removed)
