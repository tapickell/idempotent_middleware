"""Core middleware logic for idempotency handling.

This package contains the core business logic for the idempotency middleware:
- State machine: Request state transitions (NEW -> RUNNING -> COMPLETED/FAILED)
- Replay: Response reconstruction from stored artifacts
- Middleware: Framework-agnostic request processing
- Cleanup: TTL-based record expiration

The core logic is framework-agnostic and can be wrapped by adapters
for different web frameworks (FastAPI, Flask, Django, etc.).
"""

from idempotent_middleware.core.replay import replay_response

__all__ = ["replay_response"]
