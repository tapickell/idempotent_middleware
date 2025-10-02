"""Unit tests for configuration module.

Tests the IdempotencyConfig class including validation, factory methods,
and immutability.
"""

import os
from typing import Any

import pytest
from pydantic import ValidationError

from idempotent_middleware.config import VALID_HTTP_METHODS, IdempotencyConfig


class TestIdempotencyConfigDefaults:
    """Tests for default configuration values."""

    def test_default_values(self) -> None:
        """Test that default values are set correctly."""
        config = IdempotencyConfig()

        assert config.enabled_methods == ["POST", "PUT", "PATCH", "DELETE"]
        assert config.default_ttl_seconds == 86400
        assert config.wait_policy == "wait"
        assert config.execution_timeout_seconds == 30
        assert config.max_body_bytes == 1048576
        assert config.storage_adapter == "memory"
        assert config.redis_url == "redis://localhost:6379"
        assert config.file_storage_path == "/tmp/idempotency"
        assert config.fingerprint_headers == ["content-type", "content-length"]

    def test_defaults_are_valid(self) -> None:
        """Test that default configuration passes all validations."""
        config = IdempotencyConfig()
        assert isinstance(config, IdempotencyConfig)


class TestEnabledMethodsValidation:
    """Tests for enabled_methods field validation."""

    def test_enabled_methods_uppercase_conversion(self) -> None:
        """Test that methods are converted to uppercase."""
        config = IdempotencyConfig(enabled_methods=["post", "put", "patch"])
        assert config.enabled_methods == ["POST", "PUT", "PATCH"]

    def test_enabled_methods_mixed_case(self) -> None:
        """Test that mixed case methods are normalized."""
        config = IdempotencyConfig(enabled_methods=["PoSt", "PuT", "pAtCh"])
        assert config.enabled_methods == ["POST", "PUT", "PATCH"]

    def test_enabled_methods_all_valid_methods(self) -> None:
        """Test that all valid HTTP methods are accepted."""
        config = IdempotencyConfig(enabled_methods=list(VALID_HTTP_METHODS))
        assert set(config.enabled_methods) == VALID_HTTP_METHODS

    def test_enabled_methods_invalid_method(self) -> None:
        """Test that invalid HTTP methods are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            IdempotencyConfig(enabled_methods=["POST", "INVALID"])

        error = exc_info.value
        assert "Invalid HTTP methods: INVALID" in str(error)

    def test_enabled_methods_multiple_invalid_methods(self) -> None:
        """Test error message with multiple invalid methods."""
        with pytest.raises(ValidationError) as exc_info:
            IdempotencyConfig(enabled_methods=["POST", "INVALID", "FAKE"])

        error = exc_info.value
        error_str = str(error)
        assert "Invalid HTTP methods" in error_str
        assert "INVALID" in error_str
        assert "FAKE" in error_str

    def test_enabled_methods_comma_separated_string(self) -> None:
        """Test that comma-separated string is parsed correctly."""
        config = IdempotencyConfig(enabled_methods="post,put,patch")
        assert config.enabled_methods == ["POST", "PUT", "PATCH"]

    def test_enabled_methods_comma_separated_with_spaces(self) -> None:
        """Test comma-separated string with spaces."""
        config = IdempotencyConfig(enabled_methods="post, put , patch")
        assert config.enabled_methods == ["POST", "PUT", "PATCH"]

    def test_enabled_methods_invalid_type(self) -> None:
        """Test that invalid types are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            IdempotencyConfig(enabled_methods=123)  # type: ignore

        assert "enabled_methods must be a list" in str(exc_info.value)


class TestTTLValidation:
    """Tests for default_ttl_seconds field validation."""

    def test_ttl_minimum_valid(self) -> None:
        """Test that minimum valid TTL (1 second) is accepted."""
        config = IdempotencyConfig(default_ttl_seconds=1)
        assert config.default_ttl_seconds == 1

    def test_ttl_maximum_valid(self) -> None:
        """Test that maximum valid TTL (7 days) is accepted."""
        config = IdempotencyConfig(default_ttl_seconds=604800)
        assert config.default_ttl_seconds == 604800

    def test_ttl_mid_range_valid(self) -> None:
        """Test that mid-range TTL values are accepted."""
        config = IdempotencyConfig(default_ttl_seconds=3600)
        assert config.default_ttl_seconds == 3600

    def test_ttl_below_minimum(self) -> None:
        """Test that TTL below minimum is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            IdempotencyConfig(default_ttl_seconds=0)

        error = exc_info.value
        assert "default_ttl_seconds must be between 1 and 604800" in str(error)

    def test_ttl_above_maximum(self) -> None:
        """Test that TTL above maximum is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            IdempotencyConfig(default_ttl_seconds=604801)

        error = exc_info.value
        assert "default_ttl_seconds must be between 1 and 604800" in str(error)

    def test_ttl_negative(self) -> None:
        """Test that negative TTL is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            IdempotencyConfig(default_ttl_seconds=-1)

        error = exc_info.value
        assert "default_ttl_seconds must be between 1 and 604800" in str(error)


class TestExecutionTimeoutValidation:
    """Tests for execution_timeout_seconds field validation."""

    def test_timeout_minimum_valid(self) -> None:
        """Test that minimum valid timeout (1 second) is accepted."""
        config = IdempotencyConfig(execution_timeout_seconds=1)
        assert config.execution_timeout_seconds == 1

    def test_timeout_maximum_valid(self) -> None:
        """Test that maximum valid timeout (5 minutes) is accepted."""
        config = IdempotencyConfig(execution_timeout_seconds=300)
        assert config.execution_timeout_seconds == 300

    def test_timeout_mid_range_valid(self) -> None:
        """Test that mid-range timeout values are accepted."""
        config = IdempotencyConfig(execution_timeout_seconds=60)
        assert config.execution_timeout_seconds == 60

    def test_timeout_below_minimum(self) -> None:
        """Test that timeout below minimum is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            IdempotencyConfig(execution_timeout_seconds=0)

        error = exc_info.value
        assert "execution_timeout_seconds must be between 1 and 300" in str(error)

    def test_timeout_above_maximum(self) -> None:
        """Test that timeout above maximum is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            IdempotencyConfig(execution_timeout_seconds=301)

        error = exc_info.value
        assert "execution_timeout_seconds must be between 1 and 300" in str(error)


class TestMaxBodyBytesValidation:
    """Tests for max_body_bytes field validation."""

    def test_max_body_bytes_zero(self) -> None:
        """Test that zero (unlimited) is accepted."""
        config = IdempotencyConfig(max_body_bytes=0)
        assert config.max_body_bytes == 0

    def test_max_body_bytes_positive(self) -> None:
        """Test that positive values are accepted."""
        config = IdempotencyConfig(max_body_bytes=2097152)
        assert config.max_body_bytes == 2097152

    def test_max_body_bytes_negative(self) -> None:
        """Test that negative values are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            IdempotencyConfig(max_body_bytes=-1)

        error = exc_info.value
        assert "max_body_bytes must be >= 0" in str(error)


class TestWaitPolicyValidation:
    """Tests for wait_policy field validation."""

    def test_wait_policy_wait(self) -> None:
        """Test that 'wait' policy is accepted."""
        config = IdempotencyConfig(wait_policy="wait")
        assert config.wait_policy == "wait"

    def test_wait_policy_no_wait(self) -> None:
        """Test that 'no-wait' policy is accepted."""
        config = IdempotencyConfig(wait_policy="no-wait")
        assert config.wait_policy == "no-wait"

    def test_wait_policy_invalid(self) -> None:
        """Test that invalid policy is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            IdempotencyConfig(wait_policy="invalid")  # type: ignore

        error = exc_info.value
        assert "wait_policy" in str(error).lower()


class TestStorageAdapterValidation:
    """Tests for storage_adapter field validation."""

    def test_storage_adapter_memory(self) -> None:
        """Test that 'memory' adapter is accepted."""
        config = IdempotencyConfig(storage_adapter="memory")
        assert config.storage_adapter == "memory"

    def test_storage_adapter_file(self) -> None:
        """Test that 'file' adapter is accepted."""
        config = IdempotencyConfig(storage_adapter="file")
        assert config.storage_adapter == "file"

    def test_storage_adapter_redis(self) -> None:
        """Test that 'redis' adapter is accepted."""
        config = IdempotencyConfig(storage_adapter="redis")
        assert config.storage_adapter == "redis"

    def test_storage_adapter_sql(self) -> None:
        """Test that 'sql' adapter is accepted."""
        config = IdempotencyConfig(storage_adapter="sql")
        assert config.storage_adapter == "sql"

    def test_storage_adapter_invalid(self) -> None:
        """Test that invalid adapter is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            IdempotencyConfig(storage_adapter="invalid")  # type: ignore

        error = exc_info.value
        assert "storage_adapter" in str(error).lower()


class TestFingerprintHeadersValidation:
    """Tests for fingerprint_headers field validation."""

    def test_fingerprint_headers_lowercase_conversion(self) -> None:
        """Test that headers are converted to lowercase."""
        config = IdempotencyConfig(
            fingerprint_headers=["Content-Type", "Content-Length", "X-Request-ID"]
        )
        assert config.fingerprint_headers == ["content-type", "content-length", "x-request-id"]

    def test_fingerprint_headers_mixed_case(self) -> None:
        """Test that mixed case headers are normalized."""
        config = IdempotencyConfig(fingerprint_headers=["CoNtEnT-TyPe", "X-REQUEST-id"])
        assert config.fingerprint_headers == ["content-type", "x-request-id"]

    def test_fingerprint_headers_comma_separated_string(self) -> None:
        """Test that comma-separated string is parsed correctly."""
        config = IdempotencyConfig(fingerprint_headers="content-type,content-length,x-request-id")
        assert config.fingerprint_headers == ["content-type", "content-length", "x-request-id"]

    def test_fingerprint_headers_comma_separated_with_spaces(self) -> None:
        """Test comma-separated string with spaces."""
        config = IdempotencyConfig(
            fingerprint_headers="content-type, content-length , x-request-id"
        )
        assert config.fingerprint_headers == ["content-type", "content-length", "x-request-id"]

    def test_fingerprint_headers_empty_list(self) -> None:
        """Test that empty list is accepted."""
        config = IdempotencyConfig(fingerprint_headers=[])
        assert config.fingerprint_headers == []

    def test_fingerprint_headers_invalid_type(self) -> None:
        """Test that invalid types are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            IdempotencyConfig(fingerprint_headers=123)  # type: ignore

        assert "fingerprint_headers must be a list" in str(exc_info.value)


class TestConfigImmutability:
    """Tests for configuration immutability."""

    def test_config_is_frozen(self) -> None:
        """Test that config cannot be modified after creation."""
        config = IdempotencyConfig()

        with pytest.raises(ValidationError) as exc_info:
            config.enabled_methods = ["GET"]

        error = exc_info.value
        assert "frozen" in str(error).lower()

    def test_config_default_ttl_cannot_be_modified(self) -> None:
        """Test that TTL cannot be modified."""
        config = IdempotencyConfig()

        with pytest.raises(ValidationError):
            config.default_ttl_seconds = 3600

    def test_config_storage_adapter_cannot_be_modified(self) -> None:
        """Test that storage adapter cannot be modified."""
        config = IdempotencyConfig()

        with pytest.raises(ValidationError):
            config.storage_adapter = "redis"


class TestConfigFromEnv:
    """Tests for creating configuration from environment variables."""

    def test_from_env_default_prefix(self) -> None:
        """Test loading from environment with default prefix."""
        os.environ["IDEMPOTENCY_ENABLED_METHODS"] = "POST,PUT"
        os.environ["IDEMPOTENCY_DEFAULT_TTL_SECONDS"] = "3600"
        os.environ["IDEMPOTENCY_WAIT_POLICY"] = "no-wait"
        os.environ["IDEMPOTENCY_STORAGE_ADAPTER"] = "redis"
        os.environ["IDEMPOTENCY_REDIS_URL"] = "redis://prod:6379/1"

        try:
            config = IdempotencyConfig.from_env()

            assert config.enabled_methods == ["POST", "PUT"]
            assert config.default_ttl_seconds == 3600
            assert config.wait_policy == "no-wait"
            assert config.storage_adapter == "redis"
            assert config.redis_url == "redis://prod:6379/1"
        finally:
            # Clean up
            del os.environ["IDEMPOTENCY_ENABLED_METHODS"]
            del os.environ["IDEMPOTENCY_DEFAULT_TTL_SECONDS"]
            del os.environ["IDEMPOTENCY_WAIT_POLICY"]
            del os.environ["IDEMPOTENCY_STORAGE_ADAPTER"]
            del os.environ["IDEMPOTENCY_REDIS_URL"]

    def test_from_env_custom_prefix(self) -> None:
        """Test loading from environment with custom prefix."""
        os.environ["CUSTOM_ENABLED_METHODS"] = "POST,PUT,PATCH"
        os.environ["CUSTOM_DEFAULT_TTL_SECONDS"] = "7200"

        try:
            config = IdempotencyConfig.from_env(prefix="CUSTOM_")

            assert config.enabled_methods == ["POST", "PUT", "PATCH"]
            assert config.default_ttl_seconds == 7200
        finally:
            del os.environ["CUSTOM_ENABLED_METHODS"]
            del os.environ["CUSTOM_DEFAULT_TTL_SECONDS"]

    def test_from_env_partial_override(self) -> None:
        """Test that only specified env vars override defaults."""
        os.environ["IDEMPOTENCY_ENABLED_METHODS"] = "POST"

        try:
            config = IdempotencyConfig.from_env()

            assert config.enabled_methods == ["POST"]
            # Other fields should have default values
            assert config.default_ttl_seconds == 86400
            assert config.wait_policy == "wait"
            assert config.storage_adapter == "memory"
        finally:
            del os.environ["IDEMPOTENCY_ENABLED_METHODS"]

    def test_from_env_no_env_vars(self) -> None:
        """Test that defaults are used when no env vars are set."""
        config = IdempotencyConfig.from_env()

        # Should match default values
        assert config.enabled_methods == ["POST", "PUT", "PATCH", "DELETE"]
        assert config.default_ttl_seconds == 86400

    def test_from_env_all_fields(self) -> None:
        """Test loading all fields from environment."""
        os.environ["IDEMPOTENCY_ENABLED_METHODS"] = "POST"
        os.environ["IDEMPOTENCY_DEFAULT_TTL_SECONDS"] = "1800"
        os.environ["IDEMPOTENCY_WAIT_POLICY"] = "no-wait"
        os.environ["IDEMPOTENCY_EXECUTION_TIMEOUT_SECONDS"] = "60"
        os.environ["IDEMPOTENCY_MAX_BODY_BYTES"] = "2097152"
        os.environ["IDEMPOTENCY_STORAGE_ADAPTER"] = "file"
        os.environ["IDEMPOTENCY_REDIS_URL"] = "redis://test:6379"
        os.environ["IDEMPOTENCY_FILE_STORAGE_PATH"] = "/var/idempotency"
        os.environ["IDEMPOTENCY_FINGERPRINT_HEADERS"] = "content-type,x-request-id"

        try:
            config = IdempotencyConfig.from_env()

            assert config.enabled_methods == ["POST"]
            assert config.default_ttl_seconds == 1800
            assert config.wait_policy == "no-wait"
            assert config.execution_timeout_seconds == 60
            assert config.max_body_bytes == 2097152
            assert config.storage_adapter == "file"
            assert config.redis_url == "redis://test:6379"
            assert config.file_storage_path == "/var/idempotency"
            assert config.fingerprint_headers == ["content-type", "x-request-id"]
        finally:
            del os.environ["IDEMPOTENCY_ENABLED_METHODS"]
            del os.environ["IDEMPOTENCY_DEFAULT_TTL_SECONDS"]
            del os.environ["IDEMPOTENCY_WAIT_POLICY"]
            del os.environ["IDEMPOTENCY_EXECUTION_TIMEOUT_SECONDS"]
            del os.environ["IDEMPOTENCY_MAX_BODY_BYTES"]
            del os.environ["IDEMPOTENCY_STORAGE_ADAPTER"]
            del os.environ["IDEMPOTENCY_REDIS_URL"]
            del os.environ["IDEMPOTENCY_FILE_STORAGE_PATH"]
            del os.environ["IDEMPOTENCY_FINGERPRINT_HEADERS"]

    def test_from_env_invalid_value(self) -> None:
        """Test that invalid env values raise validation errors."""
        os.environ["IDEMPOTENCY_DEFAULT_TTL_SECONDS"] = "invalid"

        try:
            with pytest.raises(ValueError):
                IdempotencyConfig.from_env()
        finally:
            del os.environ["IDEMPOTENCY_DEFAULT_TTL_SECONDS"]


class TestConfigFromDict:
    """Tests for creating configuration from dictionary."""

    def test_from_dict_basic(self) -> None:
        """Test creating config from dictionary."""
        config_dict: dict[str, Any] = {
            "enabled_methods": ["POST", "PUT"],
            "default_ttl_seconds": 3600,
            "storage_adapter": "redis",
        }

        config = IdempotencyConfig.from_dict(config_dict)

        assert config.enabled_methods == ["POST", "PUT"]
        assert config.default_ttl_seconds == 3600
        assert config.storage_adapter == "redis"

    def test_from_dict_all_fields(self) -> None:
        """Test creating config with all fields from dictionary."""
        config_dict: dict[str, Any] = {
            "enabled_methods": ["POST", "PUT", "PATCH"],
            "default_ttl_seconds": 7200,
            "wait_policy": "no-wait",
            "execution_timeout_seconds": 120,
            "max_body_bytes": 2097152,
            "storage_adapter": "file",
            "redis_url": "redis://custom:6379/2",
            "file_storage_path": "/custom/path",
            "fingerprint_headers": ["content-type", "x-custom-header"],
        }

        config = IdempotencyConfig.from_dict(config_dict)

        assert config.enabled_methods == ["POST", "PUT", "PATCH"]
        assert config.default_ttl_seconds == 7200
        assert config.wait_policy == "no-wait"
        assert config.execution_timeout_seconds == 120
        assert config.max_body_bytes == 2097152
        assert config.storage_adapter == "file"
        assert config.redis_url == "redis://custom:6379/2"
        assert config.file_storage_path == "/custom/path"
        assert config.fingerprint_headers == ["content-type", "x-custom-header"]

    def test_from_dict_partial(self) -> None:
        """Test that missing fields use defaults."""
        config_dict: dict[str, Any] = {"enabled_methods": ["POST"]}

        config = IdempotencyConfig.from_dict(config_dict)

        assert config.enabled_methods == ["POST"]
        # Other fields should have defaults
        assert config.default_ttl_seconds == 86400
        assert config.wait_policy == "wait"

    def test_from_dict_empty(self) -> None:
        """Test that empty dict uses all defaults."""
        config = IdempotencyConfig.from_dict({})

        assert config.enabled_methods == ["POST", "PUT", "PATCH", "DELETE"]
        assert config.default_ttl_seconds == 86400
        assert config.storage_adapter == "memory"

    def test_from_dict_invalid_value(self) -> None:
        """Test that invalid values raise validation errors."""
        config_dict: dict[str, Any] = {"default_ttl_seconds": 999999}

        with pytest.raises(ValidationError) as exc_info:
            IdempotencyConfig.from_dict(config_dict)

        error = exc_info.value
        assert "default_ttl_seconds must be between 1 and 604800" in str(error)


class TestConfigCustomValues:
    """Tests for creating configs with custom values."""

    def test_custom_enabled_methods(self) -> None:
        """Test config with custom enabled methods."""
        config = IdempotencyConfig(enabled_methods=["GET", "POST"])
        assert config.enabled_methods == ["GET", "POST"]

    def test_custom_redis_config(self) -> None:
        """Test config for Redis storage."""
        config = IdempotencyConfig(
            storage_adapter="redis",
            redis_url="redis://prod-cache:6379/1",
            default_ttl_seconds=3600,
        )

        assert config.storage_adapter == "redis"
        assert config.redis_url == "redis://prod-cache:6379/1"
        assert config.default_ttl_seconds == 3600

    def test_custom_file_config(self) -> None:
        """Test config for file storage."""
        config = IdempotencyConfig(storage_adapter="file", file_storage_path="/var/lib/idempotency")

        assert config.storage_adapter == "file"
        assert config.file_storage_path == "/var/lib/idempotency"

    def test_no_wait_policy_config(self) -> None:
        """Test config with no-wait policy."""
        config = IdempotencyConfig(wait_policy="no-wait")
        assert config.wait_policy == "no-wait"

    def test_unlimited_body_size(self) -> None:
        """Test config with unlimited body size."""
        config = IdempotencyConfig(max_body_bytes=0)
        assert config.max_body_bytes == 0

    def test_custom_fingerprint_headers(self) -> None:
        """Test config with custom fingerprint headers."""
        config = IdempotencyConfig(
            fingerprint_headers=["content-type", "x-tenant-id", "x-request-id"]
        )
        assert config.fingerprint_headers == ["content-type", "x-tenant-id", "x-request-id"]
