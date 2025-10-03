"""Property-based tests for IdempotencyConfig using Hypothesis.

This test suite uses property-based testing to generate diverse inputs
and verify invariants hold across all valid and invalid configurations.
"""

import os
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from idempotent_middleware.config import VALID_HTTP_METHODS, IdempotencyConfig

# Strategy for valid HTTP methods
http_methods_strategy = st.sampled_from(list(VALID_HTTP_METHODS))

# Strategy for lists of valid HTTP methods
http_methods_list_strategy = st.lists(
    http_methods_strategy,
    min_size=1,
    max_size=len(VALID_HTTP_METHODS),
    unique=True,
)

# Strategy for valid TTL seconds (1 to 604800)
valid_ttl_strategy = st.integers(min_value=1, max_value=604800)

# Strategy for invalid TTL seconds
invalid_ttl_strategy = st.one_of(
    st.integers(max_value=0),
    st.integers(min_value=604801, max_value=10000000),
)

# Strategy for valid execution timeout (1 to 300)
valid_timeout_strategy = st.integers(min_value=1, max_value=300)

# Strategy for invalid execution timeout
invalid_timeout_strategy = st.one_of(
    st.integers(max_value=0),
    st.integers(min_value=301, max_value=10000),
)

# Strategy for valid max_body_bytes (0 or positive)
valid_max_body_strategy = st.integers(min_value=0, max_value=100_000_000)

# Strategy for invalid max_body_bytes (negative)
invalid_max_body_strategy = st.integers(max_value=-1)

# Strategy for wait policy
wait_policy_strategy = st.sampled_from(["wait", "no-wait"])

# Strategy for storage adapter
storage_adapter_strategy = st.sampled_from(["memory", "file", "redis", "sql"])

# Strategy for header names (realistic HTTP headers)
header_name_strategy = st.sampled_from(
    [
        "content-type",
        "content-length",
        "x-request-id",
        "authorization",
        "user-agent",
        "accept",
        "accept-language",
        "x-forwarded-for",
    ]
)

# Strategy for lists of header names
header_list_strategy = st.lists(
    header_name_strategy,
    min_size=0,
    max_size=10,
    unique=True,
)


class TestIdempotencyConfigProperties:
    """Property-based tests for IdempotencyConfig."""

    @given(methods=http_methods_list_strategy)
    def test_valid_methods_always_accepted(self, methods: list[str]) -> None:
        """Any combination of valid HTTP methods should be accepted."""
        config = IdempotencyConfig(enabled_methods=methods)

        # All methods should be uppercase
        assert all(m.isupper() for m in config.enabled_methods)

        # All methods should be in the original list (case-insensitive)
        assert {m.upper() for m in methods} == set(config.enabled_methods)

    @given(
        methods=st.lists(
            st.text(
                alphabet=st.characters(
                    blacklist_characters="\x00\n",
                    blacklist_categories=("Cs",),  # Exclude surrogate characters
                ),
                min_size=1,
                max_size=20,
            ),
            min_size=1,
            max_size=5,
        ).filter(lambda ms: not all(m.upper() in VALID_HTTP_METHODS for m in ms))
    )
    def test_invalid_methods_always_rejected(self, methods: list[str]) -> None:
        """Any list containing invalid methods should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            IdempotencyConfig(enabled_methods=methods)

        assert "Invalid HTTP methods" in str(exc_info.value)

    @given(ttl=valid_ttl_strategy)
    def test_valid_ttl_always_accepted(self, ttl: int) -> None:
        """Any TTL in the valid range should be accepted."""
        config = IdempotencyConfig(default_ttl_seconds=ttl)
        assert config.default_ttl_seconds == ttl
        assert 1 <= config.default_ttl_seconds <= 604800

    @given(ttl=invalid_ttl_strategy)
    def test_invalid_ttl_always_rejected(self, ttl: int) -> None:
        """Any TTL outside the valid range should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            IdempotencyConfig(default_ttl_seconds=ttl)

        assert "default_ttl_seconds must be between 1 and 604800" in str(exc_info.value)

    @given(timeout=valid_timeout_strategy)
    def test_valid_timeout_always_accepted(self, timeout: int) -> None:
        """Any execution timeout in the valid range should be accepted."""
        config = IdempotencyConfig(execution_timeout_seconds=timeout)
        assert config.execution_timeout_seconds == timeout
        assert 1 <= config.execution_timeout_seconds <= 300

    @given(timeout=invalid_timeout_strategy)
    def test_invalid_timeout_always_rejected(self, timeout: int) -> None:
        """Any execution timeout outside the valid range should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            IdempotencyConfig(execution_timeout_seconds=timeout)

        assert "execution_timeout_seconds must be between 1 and 300" in str(exc_info.value)

    @given(max_bytes=valid_max_body_strategy)
    def test_valid_max_body_bytes_accepted(self, max_bytes: int) -> None:
        """Any non-negative max_body_bytes should be accepted."""
        config = IdempotencyConfig(max_body_bytes=max_bytes)
        assert config.max_body_bytes == max_bytes
        assert config.max_body_bytes >= 0

    @given(max_bytes=invalid_max_body_strategy)
    def test_invalid_max_body_bytes_rejected(self, max_bytes: int) -> None:
        """Negative max_body_bytes should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            IdempotencyConfig(max_body_bytes=max_bytes)

        assert "max_body_bytes must be >= 0" in str(exc_info.value)

    @given(policy=wait_policy_strategy)
    def test_valid_wait_policy_accepted(self, policy: str) -> None:
        """Valid wait policies should be accepted."""
        config = IdempotencyConfig(wait_policy=policy)  # type: ignore[arg-type]
        assert config.wait_policy == policy

    @given(
        policy=st.text(
            alphabet=st.characters(blacklist_characters="\x00\n"),
            min_size=1,
            max_size=20,
        ).filter(lambda p: p not in ["wait", "no-wait"])
    )
    def test_invalid_wait_policy_rejected(self, policy: str) -> None:
        """Invalid wait policies should be rejected."""
        with pytest.raises(ValidationError):
            IdempotencyConfig(wait_policy=policy)  # type: ignore[arg-type]

    @given(adapter=storage_adapter_strategy)
    def test_valid_storage_adapter_accepted(self, adapter: str) -> None:
        """Valid storage adapters should be accepted."""
        config = IdempotencyConfig(storage_adapter=adapter)  # type: ignore[arg-type]
        assert config.storage_adapter == adapter

    @given(
        adapter=st.text(
            alphabet=st.characters(blacklist_characters="\x00\n"),
            min_size=1,
            max_size=20,
        ).filter(lambda a: a not in ["memory", "file", "redis", "sql"])
    )
    def test_invalid_storage_adapter_rejected(self, adapter: str) -> None:
        """Invalid storage adapters should be rejected."""
        with pytest.raises(ValidationError):
            IdempotencyConfig(storage_adapter=adapter)  # type: ignore[arg-type]

    @given(headers=header_list_strategy)
    def test_fingerprint_headers_always_lowercase(self, headers: list[str]) -> None:
        """Fingerprint headers should always be converted to lowercase."""
        # Mix cases in the input
        mixed_case_headers = [h.upper() if i % 2 == 0 else h.lower() for i, h in enumerate(headers)]
        config = IdempotencyConfig(fingerprint_headers=mixed_case_headers)

        # All should be lowercase
        assert all(h.islower() or not h.isalpha() for h in config.fingerprint_headers)

        # Should match original headers (case-insensitive)
        assert {h.lower() for h in mixed_case_headers} == set(config.fingerprint_headers)

    @given(
        methods=http_methods_list_strategy,
        ttl=valid_ttl_strategy,
        timeout=valid_timeout_strategy,
        max_bytes=valid_max_body_strategy,
        policy=wait_policy_strategy,
        adapter=storage_adapter_strategy,
    )
    def test_config_is_always_frozen(
        self,
        methods: list[str],
        ttl: int,
        timeout: int,
        max_bytes: int,
        policy: str,
        adapter: str,
    ) -> None:
        """Config should always be immutable regardless of values."""
        config = IdempotencyConfig(
            enabled_methods=methods,
            default_ttl_seconds=ttl,
            execution_timeout_seconds=timeout,
            max_body_bytes=max_bytes,
            wait_policy=policy,  # type: ignore[arg-type]
            storage_adapter=adapter,  # type: ignore[arg-type]
        )

        # Try to modify - should fail
        with pytest.raises(ValidationError):
            config.default_ttl_seconds = 999  # type: ignore[misc]

    @given(
        methods=http_methods_list_strategy,
        ttl=valid_ttl_strategy,
    )
    def test_from_dict_round_trip(self, methods: list[str], ttl: int) -> None:
        """Config can be converted to dict and back."""
        config1 = IdempotencyConfig(
            enabled_methods=methods,
            default_ttl_seconds=ttl,
        )

        # Convert to dict
        config_dict = config1.model_dump()

        # Create from dict
        config2 = IdempotencyConfig.from_dict(config_dict)

        # Should be equivalent
        assert config1.enabled_methods == config2.enabled_methods
        assert config1.default_ttl_seconds == config2.default_ttl_seconds

    @given(
        data=st.fixed_dictionaries(
            {
                "enabled_methods": http_methods_list_strategy,
                "default_ttl_seconds": valid_ttl_strategy,
                "execution_timeout_seconds": valid_timeout_strategy,
                "max_body_bytes": valid_max_body_strategy,
            }
        )
    )
    def test_from_dict_valid_data_always_succeeds(self, data: dict[str, Any]) -> None:
        """from_dict should always succeed with valid data."""
        config = IdempotencyConfig.from_dict(data)

        # Verify all fields were set correctly
        assert {m.upper() for m in data["enabled_methods"]} == set(config.enabled_methods)
        assert config.default_ttl_seconds == data["default_ttl_seconds"]
        assert config.execution_timeout_seconds == data["execution_timeout_seconds"]
        assert config.max_body_bytes == data["max_body_bytes"]


class TestConfigEnvironmentVariables:
    """Property-based tests for environment variable loading."""

    @given(
        methods=http_methods_list_strategy,
        ttl=valid_ttl_strategy,
    )
    def test_from_env_parses_correctly(self, methods: list[str], ttl: int) -> None:
        """Environment variables should be parsed correctly."""
        # Set environment variables
        methods_str = ",".join(methods)
        os.environ["IDEMPOTENCY_ENABLED_METHODS"] = methods_str
        os.environ["IDEMPOTENCY_DEFAULT_TTL_SECONDS"] = str(ttl)

        try:
            config = IdempotencyConfig.from_env()

            # Verify parsing
            assert {m.upper() for m in methods} == set(config.enabled_methods)
            assert config.default_ttl_seconds == ttl
        finally:
            # Cleanup
            os.environ.pop("IDEMPOTENCY_ENABLED_METHODS", None)
            os.environ.pop("IDEMPOTENCY_DEFAULT_TTL_SECONDS", None)

    @given(
        prefix=st.text(
            alphabet=st.characters(whitelist_categories=("Lu",)),  # Uppercase letters
            min_size=3,
            max_size=20,
        ).map(lambda s: s + "_"),
        ttl=valid_ttl_strategy,
    )
    def test_from_env_custom_prefix_works(self, prefix: str, ttl: int) -> None:
        """Custom prefixes should work correctly."""
        env_var = f"{prefix}DEFAULT_TTL_SECONDS"
        os.environ[env_var] = str(ttl)

        try:
            config = IdempotencyConfig.from_env(prefix=prefix)
            assert config.default_ttl_seconds == ttl
        finally:
            os.environ.pop(env_var, None)


class TestConfigCommaSeperatedStrings:
    """Property-based tests for comma-separated string parsing."""

    @given(
        methods=http_methods_list_strategy,
        spaces=st.lists(st.text(alphabet=" \t", min_size=0, max_size=5), min_size=1, max_size=10),
    )
    def test_methods_comma_separated_with_random_spaces(
        self,
        methods: list[str],
        spaces: list[str],
    ) -> None:
        """Comma-separated methods with random spacing should parse correctly."""
        # Ensure we have enough spaces for all methods
        while len(spaces) < len(methods):
            spaces.append("")

        methods_str = ",".join(
            f"{space}{method}" for space, method in zip(spaces, methods, strict=False)
        )
        config = IdempotencyConfig(enabled_methods=methods_str)

        # Should parse correctly despite spacing
        assert {m.upper() for m in methods} == set(config.enabled_methods)

    @given(headers=header_list_strategy)
    def test_headers_comma_separated_parsing(self, headers: list[str]) -> None:
        """Comma-separated headers should parse correctly."""
        if not headers:
            # Skip empty list
            return

        headers_str = ",".join(headers)
        config = IdempotencyConfig(fingerprint_headers=headers_str)

        # Should parse correctly
        assert {h.lower() for h in headers} == set(config.fingerprint_headers)
