"""Configuration module for idempotency middleware.

This module provides the IdempotencyConfig class for configuring the behavior of the
idempotency middleware, including storage options, request handling policies, and validation.

Example:
    Basic usage with defaults:

        >>> config = IdempotencyConfig()
        >>> config.enabled_methods
        ['POST', 'PUT', 'PATCH', 'DELETE']

    Custom configuration:

        >>> config = IdempotencyConfig(
        ...     enabled_methods=["POST", "PUT"],
        ...     default_ttl_seconds=3600,
        ...     storage_adapter="redis",
        ...     redis_url="redis://myhost:6379/0"
        ... )

    Loading from environment:

        >>> import os
        >>> os.environ['IDEMPOTENCY_ENABLED_METHODS'] = 'POST,PUT'
        >>> os.environ['IDEMPOTENCY_DEFAULT_TTL_SECONDS'] = '3600'
        >>> config = IdempotencyConfig.from_env()

    Loading from dictionary:

        >>> config_dict = {
        ...     'enabled_methods': ['POST', 'PUT'],
        ...     'default_ttl_seconds': 3600,
        ...     'storage_adapter': 'redis'
        ... }
        >>> config = IdempotencyConfig.from_dict(config_dict)
"""

import os
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Valid HTTP methods for idempotency
VALID_HTTP_METHODS = {
    "GET",
    "HEAD",
    "POST",
    "PUT",
    "DELETE",
    "CONNECT",
    "OPTIONS",
    "TRACE",
    "PATCH",
}


class IdempotencyConfig(BaseModel):
    """Configuration for idempotency middleware.

    This immutable configuration class defines all settings for the idempotency middleware,
    including which HTTP methods to track, storage options, and request handling policies.

    Attributes:
        enabled_methods: List of HTTP methods that require idempotency checks.
            Only requests with these methods will be tracked. Default includes all
            state-changing methods: POST, PUT, PATCH, DELETE.
        default_ttl_seconds: Time-to-live in seconds for idempotency records.
            Must be between 1 and 604800 (7 days). Default is 86400 (24 hours).
        wait_policy: How to handle concurrent requests with the same idempotency key.
            "wait" will block until the first request completes, "no-wait" will
            return a 409 Conflict immediately. Default is "wait".
        execution_timeout_seconds: Maximum time in seconds to wait for a request to complete
            when wait_policy is "wait". Must be between 1 and 300 (5 minutes).
            Default is 30 seconds.
        max_body_bytes: Maximum request body size in bytes to include in fingerprint.
            0 means unlimited. Bodies larger than this will be truncated for fingerprinting.
            Default is 1048576 (1 MB).
        storage_adapter: Type of storage backend to use for idempotency records.
            Options: "memory", "file", "redis", "sql". Default is "memory".
        redis_url: Connection URL for Redis storage adapter. Only used when
            storage_adapter is "redis". Default is "redis://localhost:6379".
        file_storage_path: Directory path for file storage adapter. Only used when
            storage_adapter is "file". Default is "/tmp/idempotency".
        fingerprint_headers: List of HTTP header names to include in request fingerprint.
            Headers are case-insensitive and will be normalized to lowercase.
            Default includes ["content-type", "content-length"].

    Example:
        >>> config = IdempotencyConfig(
        ...     enabled_methods=["POST", "PUT"],
        ...     default_ttl_seconds=3600,
        ...     wait_policy="no-wait",
        ...     storage_adapter="redis",
        ...     redis_url="redis://prod-cache:6379/1"
        ... )
        >>> config.enabled_methods
        ['POST', 'PUT']
        >>> config.default_ttl_seconds
        3600

    Note:
        This class is immutable (frozen=True) to prevent accidental modification
        after initialization. Create a new instance if you need different settings.
    """

    enabled_methods: list[str] | str = Field(
        default=["POST", "PUT", "PATCH", "DELETE"],
        description="List of HTTP methods that require idempotency checks",
    )
    default_ttl_seconds: int = Field(
        default=86400,
        description="Time-to-live in seconds for idempotency records (1-604800)",
    )
    wait_policy: Literal["wait", "no-wait"] = Field(
        default="wait",
        description="Policy for handling concurrent requests: 'wait' or 'no-wait'",
    )
    execution_timeout_seconds: int = Field(
        default=30,
        description="Maximum time in seconds to wait for request completion (1-300)",
    )
    max_body_bytes: int = Field(
        default=1048576,
        description="Maximum request body size in bytes to include in fingerprint (0=unlimited)",
    )
    storage_adapter: Literal["memory", "file", "redis", "sql"] = Field(
        default="memory",
        description="Type of storage backend for idempotency records",
    )
    redis_url: str = Field(
        default="redis://localhost:6379",
        description="Connection URL for Redis storage adapter",
    )
    file_storage_path: str = Field(
        default="/tmp/idempotency",
        description="Directory path for file storage adapter",
    )
    fingerprint_headers: list[str] | str = Field(
        default=["content-type", "content-length"],
        description="List of HTTP header names to include in request fingerprint",
    )

    model_config = {"frozen": True}

    @field_validator("enabled_methods", mode="before")
    @classmethod
    def validate_enabled_methods(cls, v: Any) -> list[str]:
        """Validate and normalize enabled HTTP methods.

        Converts methods to uppercase and validates against known HTTP methods.

        Args:
            v: List of HTTP method strings or comma-separated string.

        Returns:
            List of uppercase, validated HTTP methods.

        Raises:
            ValueError: If any method is not a valid HTTP method.

        Example:
            >>> config = IdempotencyConfig(enabled_methods=["post", "put"])
            >>> config.enabled_methods
            ['POST', 'PUT']
        """
        if isinstance(v, str):
            # Handle comma-separated string (from environment variables)
            v = [method.strip() for method in v.split(",")]

        if not isinstance(v, list):
            raise ValueError("enabled_methods must be a list or comma-separated string")

        # Convert to uppercase
        methods = [method.upper() for method in v]

        # Validate against known HTTP methods
        invalid_methods = set(methods) - VALID_HTTP_METHODS
        if invalid_methods:
            raise ValueError(
                f"Invalid HTTP methods: {', '.join(sorted(invalid_methods))}. "
                f"Valid methods are: {', '.join(sorted(VALID_HTTP_METHODS))}"
            )

        return methods

    @field_validator("default_ttl_seconds")
    @classmethod
    def validate_default_ttl_seconds(cls, v: int) -> int:
        """Validate TTL is within acceptable range.

        Args:
            v: TTL value in seconds.

        Returns:
            Validated TTL value.

        Raises:
            ValueError: If TTL is not between 1 and 604800 (7 days).

        Example:
            >>> config = IdempotencyConfig(default_ttl_seconds=3600)
            >>> config.default_ttl_seconds
            3600
        """
        if not (1 <= v <= 604800):
            raise ValueError(f"default_ttl_seconds must be between 1 and 604800 (7 days), got {v}")
        return v

    @field_validator("execution_timeout_seconds")
    @classmethod
    def validate_execution_timeout_seconds(cls, v: int) -> int:
        """Validate execution timeout is within acceptable range.

        Args:
            v: Timeout value in seconds.

        Returns:
            Validated timeout value.

        Raises:
            ValueError: If timeout is not between 1 and 300 (5 minutes).

        Example:
            >>> config = IdempotencyConfig(execution_timeout_seconds=60)
            >>> config.execution_timeout_seconds
            60
        """
        if not (1 <= v <= 300):
            raise ValueError(
                f"execution_timeout_seconds must be between 1 and 300 (5 minutes), got {v}"
            )
        return v

    @field_validator("max_body_bytes")
    @classmethod
    def validate_max_body_bytes(cls, v: int) -> int:
        """Validate max body bytes is non-negative.

        Args:
            v: Maximum body size in bytes.

        Returns:
            Validated max body bytes value.

        Raises:
            ValueError: If value is negative.

        Example:
            >>> config = IdempotencyConfig(max_body_bytes=2097152)
            >>> config.max_body_bytes
            2097152
        """
        if v < 0:
            raise ValueError(f"max_body_bytes must be >= 0, got {v}")
        return v

    @field_validator("fingerprint_headers", mode="before")
    @classmethod
    def validate_fingerprint_headers(cls, v: Any) -> list[str]:
        """Validate and normalize fingerprint headers.

        Converts headers to lowercase for case-insensitive matching.

        Args:
            v: List of header names or comma-separated string.

        Returns:
            List of lowercase header names.

        Example:
            >>> config = IdempotencyConfig(fingerprint_headers=["Content-Type", "X-Request-ID"])
            >>> config.fingerprint_headers
            ['content-type', 'x-request-id']
        """
        if isinstance(v, str):
            # Handle comma-separated string (from environment variables)
            v = [header.strip() for header in v.split(",")]

        if not isinstance(v, list):
            raise ValueError("fingerprint_headers must be a list or comma-separated string")

        # Convert to lowercase for case-insensitive matching
        return [header.lower() for header in v]

    @model_validator(mode="after")
    def validate_storage_config(self) -> "IdempotencyConfig":
        """Validate storage-specific configuration.

        Ensures that storage adapter-specific settings are valid.

        Returns:
            The validated config instance.

        Raises:
            ValueError: If storage-specific configuration is invalid.

        Example:
            >>> config = IdempotencyConfig(
            ...     storage_adapter="redis",
            ...     redis_url="redis://localhost:6379/0"
            ... )
            >>> config.storage_adapter
            'redis'
        """
        # Additional validation can be added here if needed
        # For example, validating Redis URL format or file path existence
        return self

    @classmethod
    def from_env(cls, prefix: str = "IDEMPOTENCY_") -> "IdempotencyConfig":
        """Create configuration from environment variables.

        Loads configuration from environment variables with the specified prefix.
        Variable names are uppercase field names with the prefix.

        Args:
            prefix: Prefix for environment variable names. Default is "IDEMPOTENCY_".

        Returns:
            IdempotencyConfig instance populated from environment variables.

        Example:
            >>> import os
            >>> os.environ['IDEMPOTENCY_ENABLED_METHODS'] = 'POST,PUT'
            >>> os.environ['IDEMPOTENCY_DEFAULT_TTL_SECONDS'] = '3600'
            >>> os.environ['IDEMPOTENCY_STORAGE_ADAPTER'] = 'redis'
            >>> config = IdempotencyConfig.from_env()
            >>> config.enabled_methods
            ['POST', 'PUT']
            >>> config.default_ttl_seconds
            3600

        Note:
            Environment variables override default values. Missing variables
            will use the default values defined in the model.
        """
        config_dict: dict[str, Any] = {}

        # Map of field names to their types for proper conversion
        field_types = {
            "enabled_methods": list,
            "default_ttl_seconds": int,
            "wait_policy": str,
            "execution_timeout_seconds": int,
            "max_body_bytes": int,
            "storage_adapter": str,
            "redis_url": str,
            "file_storage_path": str,
            "fingerprint_headers": list,
        }

        for field_name, field_type in field_types.items():
            env_var = f"{prefix}{field_name.upper()}"
            env_value = os.environ.get(env_var)

            if env_value is not None:
                if field_type is int:
                    config_dict[field_name] = int(env_value)
                elif field_type is list:
                    # Handle comma-separated strings
                    config_dict[field_name] = env_value
                else:
                    config_dict[field_name] = env_value

        return cls(**config_dict)

    @classmethod
    def from_dict(cls, config_dict: dict[str, Any]) -> "IdempotencyConfig":
        """Create configuration from a dictionary.

        Args:
            config_dict: Dictionary with configuration values.

        Returns:
            IdempotencyConfig instance populated from the dictionary.

        Raises:
            ValidationError: If the dictionary contains invalid values.

        Example:
            >>> config_dict = {
            ...     'enabled_methods': ['POST', 'PUT'],
            ...     'default_ttl_seconds': 3600,
            ...     'storage_adapter': 'redis',
            ...     'redis_url': 'redis://prod:6379/1'
            ... }
            >>> config = IdempotencyConfig.from_dict(config_dict)
            >>> config.enabled_methods
            ['POST', 'PUT']
        """
        return cls(**config_dict)
