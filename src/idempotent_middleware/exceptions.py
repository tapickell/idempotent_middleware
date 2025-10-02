"""Custom exceptions for the idempotency middleware.

This module defines the exception hierarchy used throughout the middleware
to signal various error conditions, including storage failures, conflicts,
and lease management issues.

Examples:
    Handling a conflict error::

        from idempotent_middleware.exceptions import ConflictError

        try:
            await storage.put_new_running(key, fingerprint, ttl)
        except ConflictError as e:
            # Different fingerprint for same key
            logger.warning("Request conflict detected", error=str(e))
            return Response(status_code=409)

    Handling a storage error::

        from idempotent_middleware.exceptions import StorageError

        try:
            record = await storage.get(key)
        except StorageError as e:
            logger.error("Storage backend failure", error=str(e))
            # Fall through to allow request to proceed
            record = None
"""


class IdempotencyError(Exception):
    """Base exception for all idempotency-related errors.

    All exceptions raised by the idempotency middleware inherit from this
    base class, allowing callers to catch all middleware-specific errors
    with a single except clause.

    Attributes:
        message: Human-readable error description.

    Examples:
        Catching all idempotency errors::

            try:
                await process_with_idempotency(request)
            except IdempotencyError as e:
                logger.error("Idempotency error occurred", error=str(e))
                return Response(status_code=500)
    """

    def __init__(self, message: str) -> None:
        """Initialize the exception with a message.

        Args:
            message: Human-readable error description.
        """
        self.message = message
        super().__init__(message)


class ConflictError(IdempotencyError):
    """Request conflict detected - same key, different fingerprint.

    This exception is raised when a request is received with an idempotency
    key that already exists in storage, but the request fingerprint (hash of
    the request body, headers, etc.) does not match the stored fingerprint.

    This indicates that the client is attempting to reuse an idempotency key
    for a different request, which violates the idempotency contract. The
    middleware should return HTTP 409 Conflict in this case.

    Attributes:
        message: Human-readable error description.
        key: The idempotency key that conflicted.
        stored_fingerprint: The fingerprint stored in the backend.
        request_fingerprint: The fingerprint of the incoming request.

    Examples:
        Raising a conflict error::

            if record.fingerprint != request_fingerprint:
                raise ConflictError(
                    message=f"Fingerprint mismatch for key {key}",
                    key=key,
                    stored_fingerprint=record.fingerprint,
                    request_fingerprint=request_fingerprint,
                )

        Handling a conflict error::

            try:
                result = await storage.put_new_running(key, fingerprint, ttl)
            except ConflictError:
                return JSONResponse(
                    status_code=409,
                    content={"error": "Idempotency key conflict"},
                )
    """

    def __init__(
        self,
        message: str,
        key: str,
        stored_fingerprint: str,
        request_fingerprint: str,
    ) -> None:
        """Initialize the conflict error with details.

        Args:
            message: Human-readable error description.
            key: The idempotency key that conflicted.
            stored_fingerprint: The fingerprint stored in the backend.
            request_fingerprint: The fingerprint of the incoming request.
        """
        super().__init__(message)
        self.key = key
        self.stored_fingerprint = stored_fingerprint
        self.request_fingerprint = request_fingerprint


class LeaseExpiredError(IdempotencyError):
    """The execution lease has expired and cannot be used.

    This exception is raised when attempting to complete or fail a request
    using a lease token that is no longer valid. This can occur if:

    1. The lease TTL has expired
    2. Another process has forcibly taken over the lease
    3. The record has been deleted from storage

    When this occurs, the middleware should typically retry the operation
    or treat it as a permanent failure depending on the context.

    Attributes:
        message: Human-readable error description.
        lease_token: The expired or invalid lease token.

    Examples:
        Raising a lease expired error::

            if record.lease_token != lease_token:
                raise LeaseExpiredError(
                    message=f"Lease token {lease_token} is invalid",
                    lease_token=lease_token,
                )

        Handling a lease expired error::

            try:
                await storage.complete(lease_token, record)
            except LeaseExpiredError:
                logger.warning("Lease expired, unable to store result")
                # Result was computed but cannot be cached
                return result
    """

    def __init__(self, message: str, lease_token: str) -> None:
        """Initialize the lease expired error with details.

        Args:
            message: Human-readable error description.
            lease_token: The expired or invalid lease token.
        """
        super().__init__(message)
        self.lease_token = lease_token


class StorageError(IdempotencyError):
    """Storage backend operation failed.

    This exception is raised when the underlying storage backend encounters
    an error that prevents it from completing the requested operation. This
    could be due to:

    1. Network failures (connection timeouts, DNS resolution)
    2. Backend service unavailability (Redis down, DynamoDB throttling)
    3. Permission or authentication errors
    4. Data corruption or consistency issues

    The middleware should handle this gracefully, typically by allowing the
    request to proceed without idempotency protection rather than failing
    the entire request.

    Attributes:
        message: Human-readable error description.
        cause: The underlying exception that caused the storage error.

    Examples:
        Raising a storage error::

            try:
                await redis.get(key)
            except RedisError as e:
                raise StorageError(
                    message=f"Failed to retrieve key from Redis: {e}",
                    cause=e,
                ) from e

        Handling a storage error::

            try:
                record = await storage.get(key)
            except StorageError as e:
                logger.error("Storage backend unavailable", error=str(e))
                # Proceed without idempotency protection
                record = None
    """

    def __init__(self, message: str, cause: Exception | None = None) -> None:
        """Initialize the storage error with details.

        Args:
            message: Human-readable error description.
            cause: The underlying exception that caused the storage error.
        """
        super().__init__(message)
        self.cause = cause
