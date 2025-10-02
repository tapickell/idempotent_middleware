"""Framework adapters for idempotency middleware.

This package provides adapters that integrate the framework-agnostic core
middleware with specific web frameworks:

- asgi.py: ASGI middleware for FastAPI, Starlette, etc.
- wsgi.py: WSGI middleware for Flask, Django, etc. (future)

The adapters handle the conversion between framework-specific request/response
objects and the middleware's internal representation.
"""

from idempotent_middleware.adapters.asgi import ASGIIdempotencyMiddleware

__all__ = ["ASGIIdempotencyMiddleware"]
