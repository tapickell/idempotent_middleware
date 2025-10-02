"""In-memory storage adapter with asyncio concurrency control.

This module provides a thread-safe in-memory implementation of the
StorageAdapter interface using asyncio.Lock for concurrency control.

The MemoryStorageAdapter is suitable for:
    - Single-process applications
    - Development and testing
    - Low-latency scenarios where persistence is not required

For distributed systems or persistence requirements, use RedisStorageAdapter
or FileStorageAdapter instead.

Thread Safety:
    - Each idempotency key has its own asyncio.Lock
    - A global lock protects the _locks dictionary
    - Locks are held only during critical sections
    - Locks are cleaned up after record expiry

Lease Management:
    - Lease tokens are UUID4 strings
    - Tokens are validated before allowing state transitions
    - This prevents stale completions from crashed workers

Examples:
    Basic usage::

        from idempotent_middleware.storage.memory import MemoryStorageAdapter

        adapter = MemoryStorageAdapter()

        # Try to acquire lease
        result = await adapter.put_new_running(
            key="payment-123",
            fingerprint="a" * 64,
            ttl_seconds=86400,
        )

        if result.success:
            # Execute the request
            response = await execute_request()

            # Mark as completed
            await adapter.complete(
                key="payment-123",
                lease_token=result.lease_token,
                response=response,
                execution_time_ms=150,
            )

    Concurrent duplicate handling::

        # Two concurrent requests with same key
        result1 = await adapter.put_new_running(key="payment-123", ...)
        result2 = await adapter.put_new_running(key="payment-123", ...)

        # Only one succeeds
        assert result1.success != result2.success

        # The failed one gets the existing record
        if not result2.success:
            existing = result2.existing_record
            print(f"Another request is {existing.state}")
"""

import asyncio
import uuid
from datetime import datetime, timedelta

from idempotent_middleware.models import (
    IdempotencyRecord,
    LeaseResult,
    RequestState,
    StoredResponse,
)
from idempotent_middleware.storage.base import StorageAdapter


class MemoryStorageAdapter(StorageAdapter):
    """In-memory storage adapter with asyncio concurrency control.

    This adapter stores idempotency records in a Python dictionary
    with per-key asyncio.Lock for thread-safe operations.

    Attributes:
        _store: Dictionary mapping keys to IdempotencyRecord objects.
        _locks: Dictionary mapping keys to asyncio.Lock objects.
        _global_lock: Lock protecting the _locks dictionary.

    Thread Safety:
        All public methods are async and use locks to ensure
        thread-safe access to internal state.
    """

    def __init__(self) -> None:
        """Initialize a new in-memory storage adapter.

        Creates empty storage dictionaries and initializes the global lock.
        """
        self._store: dict[str, IdempotencyRecord] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    async def get(self, key: str) -> IdempotencyRecord | None:
        """Retrieve an idempotency record by key.

        Args:
            key: The idempotency key to look up.

        Returns:
            The idempotency record if found, None otherwise.
        """
        return self._store.get(key)

    async def put_new_running(
        self,
        key: str,
        fingerprint: str,
        ttl_seconds: int,
        trace_id: str | None = None,
    ) -> LeaseResult:
        """Atomically create a new RUNNING record and acquire execution lease.

        This method ensures only one concurrent caller can successfully
        create a record for a given key. The lock is held until the
        request completes (via complete() or fail()).

        Race Condition Handling:
            If multiple concurrent calls occur with the same key,
            the first one to acquire the lock will create the record
            and hold the lease. Subsequent calls will find the existing
            record and return failure with that record.

        Args:
            key: The idempotency key.
            fingerprint: SHA-256 hash of the request fingerprint.
            ttl_seconds: Time-to-live in seconds for the record.
            trace_id: Optional distributed tracing ID.

        Returns:
            LeaseResult with success=True and lease_token if acquired,
            or success=False with existing_record if key already exists.
        """
        # First check if record exists (fast path, no lock needed)
        existing = self._store.get(key)
        if existing is not None:
            return LeaseResult(
                success=False,
                lease_token=None,
                existing_record=existing,
            )

        # Ensure lock exists for this key (protected by global lock)
        async with self._global_lock:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()

        # Acquire the key-specific lock
        lock = self._locks[key]
        await lock.acquire()

        try:
            # Double-check record doesn't exist (race condition protection)
            existing = self._store.get(key)
            if existing is not None:
                # Record was created by another coroutine, release lock and return failure
                lock.release()
                return LeaseResult(
                    success=False,
                    lease_token=None,
                    existing_record=existing,
                )

            # Create new RUNNING record with lease token
            lease_token = str(uuid.uuid4())
            now = datetime.utcnow()
            record = IdempotencyRecord(
                key=key,
                fingerprint=fingerprint,
                state=RequestState.RUNNING,
                response=None,
                created_at=now,
                expires_at=now + timedelta(seconds=ttl_seconds),
                execution_time_ms=None,
                lease_token=lease_token,
                trace_id=trace_id,
            )
            self._store[key] = record

            # Return success with lease token
            # Note: Lock is NOT released here - it stays held until complete/fail
            return LeaseResult(
                success=True,
                lease_token=lease_token,
                existing_record=None,
            )
        except Exception:
            # On error, release lock and re-raise
            lock.release()
            raise

    async def complete(
        self,
        key: str,
        lease_token: str,
        response: StoredResponse,
        execution_time_ms: int,
    ) -> bool:
        """Mark a record as COMPLETED and store the response.

        This method validates the lease token before updating the record.
        The lock held since put_new_running() is released after updating.

        Args:
            key: The idempotency key.
            lease_token: The lease token acquired from put_new_running.
            response: The cached response to store.
            execution_time_ms: Request execution time in milliseconds.

        Returns:
            True if the record was updated, False if lease validation failed.
        """
        # Get the record
        record = self._store.get(key)
        if record is None:
            # Record doesn't exist
            return False

        # Validate lease token
        if record.lease_token != lease_token:
            # Lease token mismatch (stale completion attempt)
            return False

        # Update record to COMPLETED state
        record.state = RequestState.COMPLETED
        record.response = response
        record.execution_time_ms = execution_time_ms

        # Release the lock that was held since put_new_running()
        if key in self._locks:
            lock = self._locks[key]
            if lock.locked():
                lock.release()

        return True

    async def fail(
        self,
        key: str,
        lease_token: str,
        response: StoredResponse,
        execution_time_ms: int,
    ) -> bool:
        """Mark a record as FAILED and store the error response.

        This method validates the lease token before updating the record.
        The lock held since put_new_running() is released after updating.

        Args:
            key: The idempotency key.
            lease_token: The lease token acquired from put_new_running.
            response: The error response to store.
            execution_time_ms: Request execution time in milliseconds.

        Returns:
            True if the record was updated, False if lease validation failed.
        """
        # Get the record
        record = self._store.get(key)
        if record is None:
            # Record doesn't exist
            return False

        # Validate lease token
        if record.lease_token != lease_token:
            # Lease token mismatch (stale completion attempt)
            return False

        # Update record to FAILED state
        record.state = RequestState.FAILED
        record.response = response
        record.execution_time_ms = execution_time_ms

        # Release the lock that was held since put_new_running()
        if key in self._locks:
            lock = self._locks[key]
            if lock.locked():
                lock.release()

        return True

    async def cleanup_expired(self) -> int:
        """Remove expired records from storage.

        This method removes all records where expires_at < current time.
        It also cleans up unused locks (locks that are not currently held).

        Returns:
            The number of records removed.
        """
        now = datetime.utcnow()
        expired_keys: list[str] = []

        # Find expired records
        for key, record in self._store.items():
            if record.expires_at < now:
                expired_keys.append(key)

        # Remove expired records and clean up locks
        removed_count = 0
        async with self._global_lock:
            for key in expired_keys:
                # Remove record if it still exists and is still expired
                if key in self._store:
                    record = self._store[key]
                    if record.expires_at < now:
                        del self._store[key]
                        removed_count += 1

                # Clean up lock if it's not currently held
                if key in self._locks:
                    lock = self._locks[key]
                    if not lock.locked():
                        del self._locks[key]

        return removed_count
