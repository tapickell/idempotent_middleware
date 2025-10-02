"""
Idempotency middleware for Python web applications.

This package provides middleware for handling idempotency keys in HTTP requests,
ensuring that unsafe operations are executed at most once per unique key.
"""

__version__ = "0.1.0"

# Public API exports will be added as components are implemented
__all__ = ["__version__"]
