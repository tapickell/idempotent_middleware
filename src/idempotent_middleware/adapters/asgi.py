"""ASGI middleware adapter for FastAPI and Starlette applications.

This module provides an ASGI middleware wrapper around the core idempotency
middleware, making it easy to integrate with ASGI frameworks like FastAPI
and Starlette.

The middleware:
1. Converts ASGI requests to the internal Request format
2. Processes through the core middleware
3. Converts internal responses back to ASGI format

Examples:
    FastAPI integration::

        from fastapi import FastAPI
        from idempotent_middleware.adapters.asgi import ASGIIdempotencyMiddleware
        from idempotent_middleware.storage.memory import MemoryStorageAdapter
        from idempotent_middleware.config import Config

        app = FastAPI()

        storage = MemoryStorageAdapter()
        config = Config()

        app.add_middleware(
            ASGIIdempotencyMiddleware,
            storage=storage,
            config=config,
        )

        @app.post("/api/payments")
        async def create_payment(data: PaymentData):
            # This endpoint is now idempotent
            return {"status": "success"}

    Starlette integration::

        from starlette.applications import Starlette
        from starlette.middleware import Middleware

        middleware = [
            Middleware(
                ASGIIdempotencyMiddleware,
                storage=storage,
                config=config,
            )
        ]

        app = Starlette(middleware=middleware)
"""

from collections.abc import Awaitable, Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response

from idempotent_middleware.config import IdempotencyConfig
from idempotent_middleware.core.middleware import IdempotencyMiddleware, Request
from idempotent_middleware.core.replay import ReplayedResponse
from idempotent_middleware.storage.base import StorageAdapter


class ASGIIdempotencyMiddleware(BaseHTTPMiddleware):
    """ASGI middleware for idempotency handling.

    This middleware wraps the core IdempotencyMiddleware and adapts it
    for use with ASGI frameworks like FastAPI and Starlette.

    Attributes:
        storage: Storage adapter for idempotency records
        config: Configuration object
        middleware: Core middleware instance
    """

    def __init__(
        self,
        app: Any,
        storage: StorageAdapter,
        config: IdempotencyConfig | None = None,
    ) -> None:
        """Initialize the ASGI middleware.

        Args:
            app: The ASGI application
            storage: Storage adapter for idempotency records
            config: Configuration object (uses defaults if not provided)
        """
        super().__init__(app)
        self.storage = storage
        self.config = config or IdempotencyConfig()
        self.middleware = IdempotencyMiddleware(storage, self.config)

    async def dispatch(
        self,
        request: StarletteRequest,
        call_next: Callable[[StarletteRequest], Awaitable[Response]],
    ) -> Response:
        """Process an ASGI request with idempotency handling.

        This method is called by Starlette for each incoming request.
        It converts the request to the internal format, processes it
        through the core middleware, and converts the response back.

        Args:
            request: The Starlette request object
            call_next: Function to call the next middleware/handler

        Returns:
            Starlette Response object
        """
        # Convert Starlette request to internal format
        internal_request = await self._convert_request(request)

        # Create a handler that calls the next middleware
        async def handler(_req: Request) -> ReplayedResponse:
            # Call the actual application
            response = await call_next(request)

            # Read response body
            body = b""
            if hasattr(response, "body_iterator"):
                async for chunk in response.body_iterator:
                    if isinstance(chunk, (bytes, bytearray, memoryview)):
                        body += bytes(chunk)
                    else:
                        body += chunk
            else:
                # For responses that already have body
                body_attr = response.body if hasattr(response, "body") else b""
                body = (
                    bytes(body_attr)
                    if isinstance(body_attr, (bytearray, memoryview))
                    else body_attr
                )

            # Convert to ReplayedResponse
            return ReplayedResponse(
                status=response.status_code,
                headers=dict(response.headers),
                body=body,
            )

        # Process through middleware
        result = await self.middleware.process(
            internal_request,
            handler,
            trace_id=self._extract_trace_id(request),
        )

        # Convert back to Starlette Response
        return self._convert_response(result)

    async def _convert_request(self, request: StarletteRequest) -> Request:
        """Convert Starlette request to internal Request format.

        Args:
            request: Starlette request object

        Returns:
            Internal Request object
        """
        # Read request body
        body = await request.body()

        # Convert headers to dict
        headers: dict[str, str] = {}
        for key, value in request.headers.items():
            headers[key] = value

        # Extract query string
        query_string = request.url.query or ""

        return Request(
            method=request.method,
            path=request.url.path,
            query_string=query_string,
            headers=headers,
            body=body,
        )

    def _convert_response(self, response: ReplayedResponse) -> Response:
        """Convert internal ReplayedResponse to Starlette Response.

        Args:
            response: Internal response object

        Returns:
            Starlette Response object
        """
        return Response(
            content=response.body,
            status_code=response.status,
            headers=response.headers,
        )

    def _extract_trace_id(self, request: StarletteRequest) -> str | None:
        """Extract distributed tracing ID from request headers.

        Looks for common tracing headers like X-Trace-Id, X-Request-Id, etc.

        Args:
            request: Starlette request object

        Returns:
            Trace ID if found, None otherwise
        """
        # Try common tracing headers
        trace_headers = [
            "x-trace-id",
            "x-request-id",
            "x-correlation-id",
            "traceparent",
        ]

        for header in trace_headers:
            value = request.headers.get(header)
            if value:
                return value

        return None
