"""Structured logging configuration for idempotency middleware.

This module provides structured logging using structlog to emit
JSON-formatted logs with contextual information. This makes logs
easier to parse and analyze in log aggregation systems.

The logger includes automatic context binding for:
- Idempotency keys
- Trace IDs
- Request fingerprints
- State transitions
- Execution times

Examples:
    Configure logging::

        from idempotent_middleware.observability.logging import configure_logging

        configure_logging(level="INFO", json_output=True)

    Use the logger::

        from idempotent_middleware.observability.logging import get_logger

        logger = get_logger(__name__)
        logger.info(
            "request.processed",
            key="payment-123",
            result="replay",
            execution_time_ms=150,
        )

    Output (JSON)::

        {
            "event": "request.processed",
            "key": "payment-123",
            "result": "replay",
            "execution_time_ms": 150,
            "timestamp": "2024-01-01T00:00:00.000000Z",
            "level": "info"
        }
"""

import logging
import sys
from typing import Any

import structlog


def configure_logging(
    level: str = "INFO",
    json_output: bool = True,
) -> None:
    """Configure structured logging for the application.

    This should be called once at application startup to set up
    the logging pipeline.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_output: If True, emit JSON logs; if False, use console format

    Examples:
        >>> configure_logging(level="DEBUG", json_output=True)
        >>> configure_logging(level="INFO", json_output=False)
    """
    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper()),
    )

    # Configure structlog
    processors: list[object] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    if json_output:
        # JSON output for production
        processors.append(structlog.processors.JSONRenderer())
    else:
        # Console output for development
        processors.extend(
            [
                structlog.dev.ConsoleRenderer(colors=True),
            ]
        )

    structlog.configure(
        processors=processors,  # type: ignore[arg-type]
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper())),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    """Get a structured logger instance.

    Args:
        name: Logger name (typically __name__ from the calling module)

    Returns:
        A structlog logger instance

    Examples:
        >>> logger = get_logger(__name__)
        >>> logger.info("event.happened", key="value")
    """
    return structlog.get_logger(name)


# Pre-configured logger for the middleware
logger = get_logger("idempotent_middleware")
