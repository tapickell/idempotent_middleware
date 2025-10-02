"""State machine handler for idempotency request processing.

This module implements the core state machine logic for handling idempotent
requests according to the specification. It manages state transitions:

    NEW -> RUNNING -> COMPLETED/FAILED

The state machine handles:
- Lease acquisition for new requests
- Conflict detection (same key, different fingerprint)
- Concurrent duplicate handling (wait vs no-wait policies)
- Response replay for completed requests

Examples:
    Processing a new request::

        from idempotent_middleware.core.state_machine import process_request
        from idempotent_middleware.storage.memory import MemoryStorageAdapter
        from idempotent_middleware.config import Config

        storage = MemoryStorageAdapter()
        config = Config()

        async def handler(request):
            # Execute the actual request
            return Response(status=200, body=b"Success")

        result = await process_request(
            storage=storage,
            key="payment-123",
            fingerprint="abc123",
            handler=handler,
            request=request,
            config=config,
        )
"""

import asyncio
import base64
import time
from collections.abc import Awaitable, Callable
from typing import Any

from idempotent_middleware.config import IdempotencyConfig
from idempotent_middleware.core.replay import ReplayedResponse, replay_response
from idempotent_middleware.exceptions import ConflictError
from idempotent_middleware.models import RequestState, StoredResponse
from idempotent_middleware.storage.base import StorageAdapter


class StateResult:
    """Result of state machine processing.

    Attributes:
        response: The response object (either new or replayed)
        was_replayed: True if response was replayed from cache
        execution_time_ms: Execution time in milliseconds (None for replays)
    """

    def __init__(
        self,
        response: ReplayedResponse,
        was_replayed: bool,
        execution_time_ms: int | None = None,
    ) -> None:
        """Initialize a state result.

        Args:
            response: The response object
            was_replayed: Whether the response was replayed
            execution_time_ms: Execution time in milliseconds
        """
        self.response = response
        self.was_replayed = was_replayed
        self.execution_time_ms = execution_time_ms


async def process_request(
    storage: StorageAdapter,
    key: str,
    fingerprint: str,
    handler: Callable[[Any], Awaitable[ReplayedResponse]],
    request: Any,
    config: IdempotencyConfig,
    trace_id: str | None = None,
) -> StateResult:
    """Process an idempotent request through the state machine.

    This is the main entry point for the state machine logic. It handles
    all state transitions and ensures idempotency guarantees.

    Flow:
        1. Check if record exists for this key
        2. If no record: acquire lease and execute handler
        3. If record exists and COMPLETED/FAILED: check fingerprint and replay
        4. If record exists and RUNNING: wait or return conflict

    Args:
        storage: Storage adapter for idempotency records
        key: Idempotency key from request header
        fingerprint: SHA-256 fingerprint of request
        handler: Async function that executes the actual request
        request: The original request object (passed to handler)
        config: Configuration object
        trace_id: Optional distributed tracing ID

    Returns:
        StateResult with the response and metadata

    Raises:
        ConflictError: If fingerprint mismatch detected
        StorageError: If storage backend fails
    """
    # Check if record exists
    record = await storage.get(key)

    if record is None:
        # NEW: No record exists, try to acquire lease
        return await handle_new_request(
            storage=storage,
            key=key,
            fingerprint=fingerprint,
            handler=handler,
            request=request,
            config=config,
            trace_id=trace_id,
        )
    else:
        # Record exists, handle based on state
        if record.state in (RequestState.COMPLETED, RequestState.FAILED):
            # Check fingerprint match
            if record.fingerprint != fingerprint:
                raise ConflictError(
                    message=f"Request fingerprint mismatch for key {key}",
                    key=key,
                    stored_fingerprint=record.fingerprint,
                    request_fingerprint=fingerprint,
                )

            # Replay the stored response
            response = replay_response(record, key)
            return StateResult(
                response=response,
                was_replayed=True,
                execution_time_ms=record.execution_time_ms,
            )

        elif record.state == RequestState.RUNNING:
            # Another request is currently executing
            return await handle_running_request(
                storage=storage,
                record=record,
                fingerprint=fingerprint,
                config=config,
            )

    # Should never reach here
    raise RuntimeError(f"Unexpected record state: {record.state}")


async def handle_new_request(
    storage: StorageAdapter,
    key: str,
    fingerprint: str,
    handler: Callable[[Any], Awaitable[ReplayedResponse]],
    request: Any,
    config: IdempotencyConfig,
    trace_id: str | None = None,
) -> StateResult:
    """Handle a new request (no existing record).

    Attempts to acquire a lease and execute the handler. If lease
    acquisition fails (race condition), defers to existing record handling.

    Args:
        storage: Storage adapter
        key: Idempotency key
        fingerprint: Request fingerprint
        handler: Handler function to execute
        request: Original request object
        config: Configuration
        trace_id: Optional trace ID

    Returns:
        StateResult with execution result
    """
    # Try to acquire lease
    result = await storage.put_new_running(
        key=key,
        fingerprint=fingerprint,
        ttl_seconds=config.default_ttl_seconds,
        trace_id=trace_id,
    )

    if not result.success:
        # Race condition: another request beat us
        # Handle the existing record
        existing = result.existing_record
        if existing is None:
            raise RuntimeError("Lease acquisition failed but no existing record")

        if existing.state in (RequestState.COMPLETED, RequestState.FAILED):
            # Check fingerprint
            if existing.fingerprint != fingerprint:
                raise ConflictError(
                    message=f"Request fingerprint mismatch for key {key}",
                    key=key,
                    stored_fingerprint=existing.fingerprint,
                    request_fingerprint=fingerprint,
                )

            # Replay
            response = replay_response(existing, key)
            return StateResult(
                response=response,
                was_replayed=True,
                execution_time_ms=existing.execution_time_ms,
            )
        else:
            # RUNNING state
            return await handle_running_request(
                storage=storage,
                record=existing,
                fingerprint=fingerprint,
                config=config,
            )

    # We have the lease, execute the handler
    lease_token = result.lease_token
    if lease_token is None:
        raise RuntimeError("Lease acquisition succeeded but no token returned")

    start_time = time.time()
    try:
        # Execute the actual request handler
        response = await handler(request)

        # Calculate execution time
        execution_time_ms = int((time.time() - start_time) * 1000)

        # Store the response
        stored_response = StoredResponse(
            status=response.status,
            headers=response.headers,
            body_b64=base64.b64encode(response.body).decode("utf-8"),
        )

        # Mark as completed
        success = await storage.complete(
            key=key,
            lease_token=lease_token,
            response=stored_response,
            execution_time_ms=execution_time_ms,
        )

        if not success:
            # Lease validation failed (should be rare)
            # But we still have the result, so return it
            pass

        return StateResult(
            response=response,
            was_replayed=False,
            execution_time_ms=execution_time_ms,
        )

    except Exception as e:
        # Handler failed, mark as FAILED
        execution_time_ms = int((time.time() - start_time) * 1000)

        # Create an error response
        error_body = f"Internal error: {str(e)}"
        stored_response = StoredResponse(
            status=500,
            headers={"content-type": "text/plain"},
            body_b64=base64.b64encode(error_body.encode("utf-8")).decode("utf-8"),
        )

        # Mark as failed
        await storage.fail(
            key=key,
            lease_token=lease_token,
            response=stored_response,
            execution_time_ms=execution_time_ms,
        )

        # Re-raise the exception
        raise


async def handle_running_request(
    storage: StorageAdapter,
    record: Any,
    fingerprint: str,
    config: IdempotencyConfig,
) -> StateResult:
    """Handle a request when another request is currently running.

    Behavior depends on the concurrent_wait_policy:
    - "no-wait": Return 409 immediately
    - "wait": Poll until the running request completes

    Args:
        storage: Storage adapter
        record: The existing RUNNING record
        fingerprint: Request fingerprint
        config: Configuration

    Returns:
        StateResult with the response

    Raises:
        ConflictError: If fingerprint mismatch or timeout
    """
    # Check fingerprint first
    if record.fingerprint != fingerprint:
        raise ConflictError(
            message=f"Request fingerprint mismatch for key {record.key}",
            key=record.key,
            stored_fingerprint=record.fingerprint,
            request_fingerprint=fingerprint,
        )

    if config.wait_policy == "no-wait":
        # Return 409 immediately
        error_response = ReplayedResponse(
            status=409,
            headers={
                "content-type": "text/plain",
                "retry-after": "5",
            },
            body=b"Request is currently being processed",
        )
        return StateResult(
            response=error_response,
            was_replayed=False,
            execution_time_ms=None,
        )

    # Wait policy: poll until completed
    timeout_seconds = config.execution_timeout_seconds
    start_time = time.time()
    poll_interval = 0.1  # 100ms

    while time.time() - start_time < timeout_seconds:
        await asyncio.sleep(poll_interval)

        # Check if record has been updated
        updated = await storage.get(record.key)
        if updated is None:
            # Record disappeared (expired?), treat as timeout
            break

        if updated.state in (RequestState.COMPLETED, RequestState.FAILED):
            # Request completed, replay the response
            response = replay_response(updated, record.key)
            return StateResult(
                response=response,
                was_replayed=True,
                execution_time_ms=updated.execution_time_ms,
            )

    # Timeout
    error_response = ReplayedResponse(
        status=425,
        headers={
            "content-type": "text/plain",
            "retry-after": "10",
        },
        body=b"Execution timeout - request still processing",
    )
    return StateResult(
        response=error_response,
        was_replayed=False,
        execution_time_ms=None,
    )
