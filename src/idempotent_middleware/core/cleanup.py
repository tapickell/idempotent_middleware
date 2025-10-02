"""TTL-based cleanup background task for expired idempotency records.

This module provides a background task that periodically removes expired
records from the storage backend. This prevents unbounded growth of the
storage and ensures that old keys can be reused after expiration.

The cleanup task:
1. Runs at configurable intervals (default 5 minutes)
2. Calls storage.cleanup_expired() to remove old records
3. Reports metrics and logs for observability
4. Handles errors gracefully without crashing the application

For storage backends with built-in TTL (like Redis with EXPIRE),
the cleanup task is optional but still useful for monitoring.

Examples:
    Start cleanup task in the background::

        from idempotent_middleware.core.cleanup import start_cleanup_task
        from idempotent_middleware.storage.memory import MemoryStorageAdapter

        storage = MemoryStorageAdapter()

        # Start background task
        task = await start_cleanup_task(
            storage=storage,
            interval_seconds=300,  # 5 minutes
        )

        # Later, when shutting down
        await stop_cleanup_task(task)

    Integrate with FastAPI startup/shutdown::

        from fastapi import FastAPI

        app = FastAPI()
        cleanup_task = None

        @app.on_event("startup")
        async def startup():
            global cleanup_task
            cleanup_task = await start_cleanup_task(storage)

        @app.on_event("shutdown")
        async def shutdown():
            if cleanup_task:
                await stop_cleanup_task(cleanup_task)
"""

import asyncio

from idempotent_middleware.observability.logging import get_logger
from idempotent_middleware.observability.metrics import record_cleanup
from idempotent_middleware.storage.base import StorageAdapter

logger = get_logger(__name__)


async def cleanup_loop(
    storage: StorageAdapter,
    interval_seconds: int = 300,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Background task that periodically cleans up expired records.

    This function runs in an infinite loop, calling storage.cleanup_expired()
    at regular intervals. It handles errors gracefully and logs all operations.

    The loop can be stopped by setting the stop_event.

    Args:
        storage: Storage adapter to clean up
        interval_seconds: Time between cleanup runs (default 300s = 5 minutes)
        stop_event: Event to signal the loop to stop (optional)

    Examples:
        >>> storage = MemoryStorageAdapter()
        >>> stop_event = asyncio.Event()
        >>> await cleanup_loop(storage, interval_seconds=60, stop_event=stop_event)
    """
    if stop_event is None:
        stop_event = asyncio.Event()

    logger.info(
        "cleanup.started",
        interval_seconds=interval_seconds,
    )

    while not stop_event.is_set():
        try:
            # Perform cleanup
            count = await storage.cleanup_expired()

            # Record metrics
            record_cleanup(count)

            # Log results
            if count > 0:
                logger.info(
                    "cleanup.completed",
                    records_removed=count,
                )
            else:
                logger.debug(
                    "cleanup.completed",
                    records_removed=0,
                )

        except Exception as e:
            logger.error(
                "cleanup.failed",
                error=str(e),
                error_type=type(e).__name__,
            )
            # Continue running even if cleanup fails

        # Wait for next interval or stop signal
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=interval_seconds,
            )
        except asyncio.TimeoutError:
            # Timeout is expected - continue to next iteration
            continue

    logger.info("cleanup.stopped")


async def start_cleanup_task(
    storage: StorageAdapter,
    interval_seconds: int = 300,
) -> asyncio.Task[None]:
    """Start the cleanup background task.

    Creates and returns an asyncio Task that runs the cleanup loop.
    The task runs indefinitely until explicitly stopped.

    Args:
        storage: Storage adapter to clean up
        interval_seconds: Time between cleanup runs (default 300s = 5 minutes)

    Returns:
        The asyncio Task running the cleanup loop

    Examples:
        >>> storage = MemoryStorageAdapter()
        >>> task = await start_cleanup_task(storage)
        >>> # ... later ...
        >>> await stop_cleanup_task(task)
    """
    stop_event = asyncio.Event()

    task = asyncio.create_task(
        cleanup_loop(
            storage=storage,
            interval_seconds=interval_seconds,
            stop_event=stop_event,
        )
    )

    # Store the stop_event in the task for later use
    task._stop_event = stop_event  # type: ignore[attr-defined]

    return task


async def stop_cleanup_task(task: asyncio.Task[None]) -> None:
    """Stop a running cleanup task gracefully.

    Signals the task to stop and waits for it to complete.

    Args:
        task: The cleanup task to stop (returned from start_cleanup_task)

    Examples:
        >>> task = await start_cleanup_task(storage)
        >>> await stop_cleanup_task(task)
    """
    # Get the stop_event from the task
    stop_event: asyncio.Event | None = getattr(task, "_stop_event", None)

    if stop_event:
        stop_event.set()

    # Wait for task to complete (with timeout to avoid hanging)
    try:
        await asyncio.wait_for(task, timeout=5.0)
    except asyncio.TimeoutError:
        logger.warning("cleanup.stop_timeout", message="Cleanup task did not stop in time")
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            logger.debug("cleanup.cancelled")
