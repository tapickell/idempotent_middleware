"""Storage adapter protocol and interface for idempotency middleware.

This module defines the abstract interface that all storage backends must
implement to work with the idempotency middleware. The interface is designed
to support atomic operations, lease-based execution control, and efficient
record lifecycle management.

The StorageAdapter protocol defines the contract that storage backends must
fulfill, including thread safety, atomicity guarantees, and error handling
requirements. Implementations can target various backends including Redis,
DynamoDB, PostgreSQL, or in-memory storage.

Examples:
    Implementing a custom storage adapter::

        from idempotent_middleware.storage.base import StorageAdapter
        from idempotent_middleware.models import IdempotencyRecord, LeaseResult

        class MyStorageAdapter:
            async def get(self, key: str) -> IdempotencyRecord | None:
                # Fetch record from backend
                data = await self.backend.get(key)
                if data is None:
                    return None
                return IdempotencyRecord.model_validate_json(data)

            async def put_new_running(
                self,
                key: str,
                fingerprint: str,
                ttl_seconds: int,
                trace_id: str | None = None,
            ) -> LeaseResult:
                # Atomically create new RUNNING record with lease
                ...

    Using a storage adapter::

        from idempotent_middleware.storage.base import StorageAdapter

        async def process_request(
            storage: StorageAdapter,
            key: str,
            fingerprint: str,
        ) -> Response:
            # Try to acquire lease
            result = await storage.put_new_running(key, fingerprint, 3600)

            if not result.success:
                # Another process is handling this or response exists
                return build_response(result.existing_record)

            try:
                # Process the request
                response = await handle_request()

                # Store result
                await storage.complete(result.lease_token, record)
                return response
            except Exception as e:
                # Mark as failed
                await storage.fail(result.lease_token, record)
                raise

Thread Safety and Atomicity Requirements:
    All StorageAdapter implementations MUST guarantee:

    1. **Atomic lease acquisition**: put_new_running() must atomically check
       for existing records and create new ones. No race conditions allowed.

    2. **Lease token validation**: complete() and fail() must verify that the
       provided lease token matches the stored token before making updates.

    3. **Concurrent safety**: Multiple processes calling the same methods
       concurrently must not corrupt data or violate idempotency guarantees.

    4. **Expiration handling**: Records with expired TTLs should be treated
       as non-existent by get() and put_new_running() operations.

    5. **Idempotent operations**: Multiple calls to complete() or fail() with
       the same lease token should be safe (though only the first succeeds).

Performance Considerations:
    Storage adapters should optimize for:

    1. **Fast reads**: get() is called on every request, must be sub-millisecond
    2. **Atomic writes**: put_new_running() uses compare-and-swap or transactions
    3. **Batch cleanup**: cleanup_expired() should efficiently remove old records
    4. **Connection pooling**: Reuse connections to avoid overhead
    5. **Minimal serialization**: Use efficient formats (msgpack, protobuf, etc.)
"""

from typing import Protocol, runtime_checkable

from idempotent_middleware.models import IdempotencyRecord, LeaseResult, StoredResponse


@runtime_checkable
class StorageAdapter(Protocol):
    """Protocol defining the interface for idempotency storage backends.

    All storage adapters must implement this protocol to work with the
    idempotency middleware. The protocol ensures consistent behavior across
    different storage backends (Redis, DynamoDB, PostgreSQL, etc.).

    All methods are async and must be safe to call concurrently from multiple
    processes and threads. Implementations must handle their own connection
    pooling, retry logic, and error handling.

    Thread Safety:
        All methods must be thread-safe and safe to call concurrently from
        multiple asyncio tasks, threads, and processes. Use appropriate
        locking, transactions, or atomic operations to prevent race conditions.

    Atomicity:
        Operations like put_new_running() must be atomic - either they
        completely succeed or completely fail with no partial state changes.
        Use database transactions, Redis WATCH/MULTI, or similar mechanisms.

    Error Handling:
        Methods should raise StorageError for transient failures (network,
        timeouts) and ConflictError for idempotency violations. Implementations
        should NOT raise backend-specific exceptions directly.
    """

    async def get(self, key: str) -> IdempotencyRecord | None:
        """Retrieve an idempotency record by key.

        Args:
            key: The idempotency key to look up.

        Returns:
            The idempotency record if found, None otherwise.

        Examples:
            >>> record = await adapter.get("payment-123")
            >>> if record:
            ...     print(f"State: {record.state}")
        """
        ...

    async def put_new_running(
        self,
        key: str,
        fingerprint: str,
        ttl_seconds: int,
        trace_id: str | None = None,
    ) -> LeaseResult:
        """Atomically create a new RUNNING record and acquire execution lease.

        This operation must be atomic - if multiple concurrent calls occur
        with the same key, exactly one should succeed and receive a lease token.

        Args:
            key: The idempotency key.
            fingerprint: SHA-256 hash of the request fingerprint.
            ttl_seconds: Time-to-live in seconds for the record.
            trace_id: Optional distributed tracing ID.

        Returns:
            LeaseResult with success=True and lease_token if acquired,
            or success=False with existing_record if key already exists.

        Examples:
            >>> result = await adapter.put_new_running(
            ...     key="payment-123",
            ...     fingerprint="a" * 64,
            ...     ttl_seconds=86400,
            ...     trace_id="trace-abc",
            ... )
            >>> if result.success:
            ...     print(f"Acquired lease: {result.lease_token}")
            ... else:
            ...     print(f"Key exists: {result.existing_record.state}")
        """
        ...

    async def complete(
        self,
        key: str,
        lease_token: str,
        response: StoredResponse,
        execution_time_ms: int,
    ) -> bool:
        """Mark a record as COMPLETED and store the response.

        This operation must validate that the lease_token matches the
        record's current lease before updating. This prevents stale
        completions from crashed or slow workers.

        Args:
            key: The idempotency key.
            lease_token: The lease token acquired from put_new_running.
            response: The cached response to store.
            execution_time_ms: Request execution time in milliseconds.

        Returns:
            True if the record was updated, False if lease validation failed.

        Examples:
            >>> response = StoredResponse(
            ...     status=200,
            ...     headers={"content-type": "application/json"},
            ...     body_b64="eyJyZXN1bHQiOiAic3VjY2VzcyJ9",
            ... )
            >>> success = await adapter.complete(
            ...     key="payment-123",
            ...     lease_token="550e8400-e29b-41d4-a716-446655440000",
            ...     response=response,
            ...     execution_time_ms=150,
            ... )
            >>> assert success
        """
        ...

    async def fail(
        self,
        key: str,
        lease_token: str,
        response: StoredResponse,
        execution_time_ms: int,
    ) -> bool:
        """Mark a record as FAILED and store the error response.

        Similar to complete() but sets state to FAILED. This allows caching
        of error responses to avoid retrying known-failing operations.

        Args:
            key: The idempotency key.
            lease_token: The lease token acquired from put_new_running.
            response: The error response to store.
            execution_time_ms: Request execution time in milliseconds.

        Returns:
            True if the record was updated, False if lease validation failed.

        Examples:
            >>> error_response = StoredResponse(
            ...     status=400,
            ...     headers={"content-type": "application/json"},
            ...     body_b64="eyJlcnJvciI6ICJJbnZhbGlkIGlucHV0In0=",
            ... )
            >>> success = await adapter.fail(
            ...     key="payment-123",
            ...     lease_token="550e8400-e29b-41d4-a716-446655440000",
            ...     response=error_response,
            ...     execution_time_ms=50,
            ... )
        """
        ...

    async def cleanup_expired(self) -> int:
        """Remove expired records from storage.

        This should remove all records where expires_at < current time.
        For in-memory adapters, this also cleans up unused locks.

        Returns:
            The number of records removed.

        Examples:
            >>> count = await adapter.cleanup_expired()
            >>> print(f"Cleaned up {count} expired records")
        """
        ...
