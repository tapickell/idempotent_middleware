"""Framework-agnostic core middleware for idempotency handling.

This module provides the main middleware logic that orchestrates the
entire idempotency flow. It is framework-agnostic and can be wrapped
by adapters for different web frameworks.

The middleware:
1. Extracts idempotency key from request headers
2. Validates the key format
3. Computes request fingerprint
4. Delegates to state machine for processing
5. Handles errors and returns appropriate responses

Examples:
    Using the middleware directly::

        from idempotent_middleware.core.middleware import IdempotencyMiddleware
        from idempotent_middleware.storage.memory import MemoryStorageAdapter
        from idempotent_middleware.config import Config

        storage = MemoryStorageAdapter()
        config = Config()
        middleware = IdempotencyMiddleware(storage, config)

        async def handler(request):
            # Process the request
            return Response(status=200, body=b"Success")

        result = await middleware.process(request, handler)
"""

from collections.abc import Awaitable, Callable

from idempotent_middleware.config import IdempotencyConfig
from idempotent_middleware.core.replay import ReplayedResponse
from idempotent_middleware.core.state_machine import process_request
from idempotent_middleware.exceptions import ConflictError, IdempotencyError
from idempotent_middleware.fingerprint import compute_fingerprint
from idempotent_middleware.storage.base import StorageAdapter
from idempotent_middleware.utils.headers import add_replay_headers


class Request:
    """Abstract request representation.

    This is a simple container for request data that the middleware needs.
    Framework adapters should convert their framework-specific request
    objects into this format.

    Attributes:
        method: HTTP method (GET, POST, etc.)
        path: URL path
        query_string: Query string without leading '?'
        headers: Request headers as dict
        body: Request body as bytes
    """

    def __init__(
        self,
        method: str,
        path: str,
        query_string: str,
        headers: dict[str, str],
        body: bytes,
    ) -> None:
        """Initialize a request.

        Args:
            method: HTTP method
            path: URL path
            query_string: Query string
            headers: Request headers
            body: Request body
        """
        self.method = method
        self.path = path
        self.query_string = query_string
        self.headers = headers
        self.body = body


class IdempotencyMiddleware:
    """Framework-agnostic idempotency middleware.

    This class orchestrates the entire idempotency flow:
    1. Extract idempotency key from request
    2. Skip safe methods (GET, HEAD, OPTIONS, TRACE)
    3. Validate key and request size
    4. Compute fingerprint
    5. Process through state machine
    6. Return response with appropriate headers

    Attributes:
        storage: Storage adapter for idempotency records
        config: Configuration object
    """

    # Safe HTTP methods that don't need idempotency
    SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

    def __init__(self, storage: StorageAdapter, config: IdempotencyConfig) -> None:
        """Initialize the middleware.

        Args:
            storage: Storage adapter for idempotency records
            config: Configuration object
        """
        self.storage = storage
        self.config = config

    async def process(
        self,
        request: Request,
        handler: Callable[[Request], Awaitable[ReplayedResponse]],
        trace_id: str | None = None,
    ) -> ReplayedResponse:
        """Process a request with idempotency handling.

        This is the main entry point for the middleware. It handles the
        complete idempotency flow and returns the response.

        Args:
            request: The incoming request
            handler: Async function to execute if not replayed
            trace_id: Optional distributed tracing ID

        Returns:
            ReplayedResponse object

        Raises:
            IdempotencyError: For various idempotency-related errors
        """
        # Check if method is safe (no idempotency needed)
        if request.method.upper() in self.SAFE_METHODS:
            return await handler(request)

        # Extract idempotency key from headers
        key = self._extract_key(request)
        if key is None:
            # No idempotency key, process normally
            return await handler(request)

        # Validate key format
        self._validate_key(key)

        # Validate request size
        self._validate_request_size(request)

        # Compute fingerprint
        # Note: fingerprint_headers is always a list[str] after validation
        headers_list: list[str] = (
            self.config.fingerprint_headers
            if isinstance(self.config.fingerprint_headers, list)
            else [self.config.fingerprint_headers]
        )
        fingerprint = compute_fingerprint(
            method=request.method,
            path=request.path,
            query_string=request.query_string,
            headers=request.headers,
            body=request.body,
            included_headers=headers_list,
        )

        try:
            # Process through state machine
            result = await process_request(
                storage=self.storage,
                key=key,
                fingerprint=fingerprint,
                handler=handler,
                request=request,
                config=self.config,
                trace_id=trace_id,
            )

            # Add/update idempotency headers
            response = result.response
            if not result.was_replayed:
                # Add headers for new responses
                response.headers = add_replay_headers(
                    response.headers,
                    key,
                    is_replay=False,
                )

            return response

        except ConflictError as e:
            # Return 409 Conflict
            return ReplayedResponse(
                status=409,
                headers={
                    "content-type": "text/plain",
                    "idempotency-key": key,
                },
                body=f"Request conflict: {e.message}".encode(),
            )

        except IdempotencyError as e:
            # Return 500 for other idempotency errors
            return ReplayedResponse(
                status=500,
                headers={
                    "content-type": "text/plain",
                },
                body=f"Idempotency error: {e.message}".encode(),
            )

    def _extract_key(self, request: Request) -> str | None:
        """Extract idempotency key from request headers.

        Looks for the configured idempotency header (default: "Idempotency-Key").
        Header names are case-insensitive.

        Args:
            request: The request object

        Returns:
            The idempotency key if present, None otherwise
        """
        header_name = "idempotency-key"

        # Search for header (case-insensitive)
        for key, value in request.headers.items():
            if key.lower() == header_name:
                return value.strip()

        return None

    def _validate_key(self, key: str) -> None:
        """Validate idempotency key format.

        Checks:
        - Key is not empty
        - Key length is within limits (max 200 characters by default)

        Args:
            key: The idempotency key to validate

        Raises:
            IdempotencyError: If key is invalid
        """
        if not key:
            raise IdempotencyError("Idempotency key cannot be empty")

        max_length = 255
        if len(key) > max_length:
            raise IdempotencyError(
                f"Idempotency key exceeds maximum length of {max_length} characters"
            )

    def _validate_request_size(self, request: Request) -> None:
        """Validate request body size.

        Ensures the request body doesn't exceed the configured maximum size.

        Args:
            request: The request object

        Raises:
            IdempotencyError: If request body is too large
        """
        max_size = self.config.max_body_bytes
        if len(request.body) > max_size:
            raise IdempotencyError(f"Request body exceeds maximum size of {max_size} bytes")
