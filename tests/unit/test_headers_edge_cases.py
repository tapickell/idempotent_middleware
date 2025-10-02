"""Edge case tests for headers utility functions.

Tests for unusual inputs, boundary conditions, and special cases.
"""

from hypothesis import given
from hypothesis import strategies as st

from idempotent_middleware.utils.headers import (
    add_replay_headers,
    canonicalize_headers,
    filter_response_headers,
    get_header_value,
    merge_headers,
)


class TestFilterResponseHeadersEdgeCases:
    """Edge case tests for filter_response_headers."""

    def test_empty_headers(self) -> None:
        """Empty headers dict should return empty dict."""
        result = filter_response_headers({})
        assert result == {}

    def test_only_volatile_headers(self) -> None:
        """Dict with only volatile headers should return empty."""
        headers = {
            "Date": "Mon, 01 Oct 2025 12:00:00 GMT",
            "Server": "nginx",
            "Connection": "keep-alive",
        }
        result = filter_response_headers(headers)
        assert result == {}

    def test_mixed_case_volatile_headers(self) -> None:
        """Volatile headers with mixed case should be filtered."""
        headers = {
            "Content-Type": "application/json",
            "DATE": "Mon, 01 Oct 2025 12:00:00 GMT",
            "SeRvEr": "nginx",
            "Connection": "keep-alive",
        }
        result = filter_response_headers(headers)
        assert result == {"Content-Type": "application/json"}
        assert "DATE" not in result
        assert "SeRvEr" not in result

    def test_remove_cookies_flag(self) -> None:
        """remove_cookies flag should remove optional volatile headers."""
        headers = {
            "Content-Type": "application/json",
            "Set-Cookie": "session=abc123",
            "ETag": '"abc"',
            "Age": "300",
        }

        # Without remove_cookies - optional headers kept
        result1 = filter_response_headers(headers, remove_cookies=False)
        assert "Set-Cookie" in result1
        assert "ETag" in result1

        # With remove_cookies - optional headers removed
        result2 = filter_response_headers(headers, remove_cookies=True)
        assert "Set-Cookie" not in result2
        assert "ETag" not in result2

    def test_additional_volatile_headers(self) -> None:
        """Additional volatile headers should be removed."""
        headers = {
            "Content-Type": "application/json",
            "X-Request-ID": "abc123",
            "X-Custom": "value",
        }

        result = filter_response_headers(
            headers,
            additional_volatile=["x-request-id", "x-custom"],
        )

        assert result == {"Content-Type": "application/json"}

    def test_additional_volatile_case_insensitive(self) -> None:
        """Additional volatile headers should be case-insensitive."""
        headers = {
            "Content-Type": "application/json",
            "X-Request-ID": "abc123",
        }

        result = filter_response_headers(
            headers,
            additional_volatile=["X-REQUEST-ID"],  # Different case
        )

        assert result == {"Content-Type": "application/json"}

    def test_preserves_original_key_case(self) -> None:
        """Original header key case should be preserved."""
        headers = {
            "Content-Type": "application/json",
            "X-Custom-Header": "value",
        }

        result = filter_response_headers(headers)

        # Should preserve exact case
        assert "Content-Type" in result
        assert "X-Custom-Header" in result
        assert "content-type" not in result

    def test_unicode_header_values(self) -> None:
        """Unicode in header values should be preserved."""
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "X-Custom": "Hello 世界",
        }

        result = filter_response_headers(headers)

        assert result["X-Custom"] == "Hello 世界"

    def test_empty_header_values(self) -> None:
        """Empty header values should be preserved."""
        headers = {
            "Content-Type": "application/json",
            "X-Empty": "",
        }

        result = filter_response_headers(headers)

        assert result["X-Empty"] == ""

    def test_whitespace_in_header_values(self) -> None:
        """Whitespace in header values should be preserved."""
        headers = {
            "Content-Type": "  application/json  ",
            "X-Spaces": "value  with  spaces",
        }

        result = filter_response_headers(headers)

        assert result["Content-Type"] == "  application/json  "
        assert result["X-Spaces"] == "value  with  spaces"

    @given(
        headers=st.dictionaries(
            st.text(min_size=1, max_size=50),
            st.text(min_size=0, max_size=200),
            min_size=0,
            max_size=20,
        )
    )
    def test_filter_is_deterministic(self, headers: dict[str, str]) -> None:
        """Filtering should be deterministic."""
        result1 = filter_response_headers(headers)
        result2 = filter_response_headers(headers)
        assert result1 == result2


class TestAddReplayHeadersEdgeCases:
    """Edge case tests for add_replay_headers."""

    def test_empty_headers(self) -> None:
        """Empty headers should get replay headers added."""
        result = add_replay_headers({}, "test-key")

        assert result["Idempotent-Replay"] == "true"
        assert result["Idempotency-Key"] == "test-key"

    def test_preserves_existing_headers(self) -> None:
        """Existing headers should be preserved."""
        headers = {
            "Content-Type": "application/json",
            "X-Custom": "value",
        }

        result = add_replay_headers(headers, "test-key")

        assert result["Content-Type"] == "application/json"
        assert result["X-Custom"] == "value"
        assert result["Idempotent-Replay"] == "true"

    def test_overwrites_existing_replay_headers(self) -> None:
        """Existing replay headers should be overwritten."""
        headers = {
            "Idempotent-Replay": "false",
            "Idempotency-Key": "old-key",
        }

        result = add_replay_headers(headers, "new-key", is_replay=True)

        assert result["Idempotent-Replay"] == "true"
        assert result["Idempotency-Key"] == "new-key"

    def test_is_replay_false(self) -> None:
        """is_replay=False should set header correctly."""
        result = add_replay_headers({}, "test-key", is_replay=False)

        assert result["Idempotent-Replay"] == "false"
        assert result["Idempotency-Key"] == "test-key"

    def test_special_characters_in_key(self) -> None:
        """Special characters in key should be preserved."""
        key = "key-with-special-chars-!@#$%"
        result = add_replay_headers({}, key)

        assert result["Idempotency-Key"] == key

    def test_unicode_in_key(self) -> None:
        """Unicode in key should be preserved."""
        key = "key-世界-123"
        result = add_replay_headers({}, key)

        assert result["Idempotency-Key"] == key

    def test_empty_key(self) -> None:
        """Empty key should be handled."""
        result = add_replay_headers({}, "")

        assert result["Idempotency-Key"] == ""

    def test_very_long_key(self) -> None:
        """Very long key should be handled."""
        key = "k" * 10000
        result = add_replay_headers({}, key)

        assert result["Idempotency-Key"] == key

    def test_does_not_mutate_original(self) -> None:
        """Original headers dict should not be mutated."""
        headers = {"Content-Type": "application/json"}
        original_headers = headers.copy()

        add_replay_headers(headers, "test-key")

        assert headers == original_headers


class TestCanonicalizeHeadersEdgeCases:
    """Edge case tests for canonicalize_headers."""

    def test_empty_headers(self) -> None:
        """Empty headers should return empty dict."""
        result = canonicalize_headers({})
        assert result == {}

    def test_lowercases_keys(self) -> None:
        """All header keys should be lowercased."""
        headers = {
            "Content-Type": "application/json",
            "CONTENT-LENGTH": "42",
            "X-CuStOm": "value",
        }

        result = canonicalize_headers(headers)

        assert "content-type" in result
        assert "content-length" in result
        assert "x-custom" in result
        assert "Content-Type" not in result

    def test_strips_whitespace_from_values(self) -> None:
        """Whitespace should be stripped from values."""
        headers = {
            "Content-Type": "  application/json  ",
            "X-Custom": "\t value \n",
        }

        result = canonicalize_headers(headers)

        assert result["content-type"] == "application/json"
        assert result["x-custom"] == "value"

    def test_filters_to_included_headers(self) -> None:
        """Should only include specified headers."""
        headers = {
            "Content-Type": "application/json",
            "Content-Length": "42",
            "Authorization": "Bearer token",
            "X-Custom": "value",
        }

        result = canonicalize_headers(headers, ["content-type", "content-length"])

        assert len(result) == 2
        assert "content-type" in result
        assert "content-length" in result
        assert "authorization" not in result
        assert "x-custom" not in result

    def test_included_headers_case_insensitive(self) -> None:
        """Included headers list should be case-insensitive."""
        headers = {
            "Content-Type": "application/json",
            "X-Custom": "value",
        }

        result = canonicalize_headers(headers, ["CONTENT-TYPE"])

        assert "content-type" in result
        assert "x-custom" not in result

    def test_none_included_headers_includes_all(self) -> None:
        """None for included_headers should include all headers."""
        headers = {
            "Content-Type": "application/json",
            "X-Custom": "value",
            "Authorization": "Bearer token",
        }

        result = canonicalize_headers(headers, None)

        assert len(result) == 3
        assert all(h in result for h in ["content-type", "x-custom", "authorization"])

    def test_empty_included_headers_returns_empty(self) -> None:
        """Empty included_headers list should return empty dict."""
        headers = {
            "Content-Type": "application/json",
            "X-Custom": "value",
        }

        result = canonicalize_headers(headers, [])

        assert result == {}

    def test_duplicate_keys_different_case(self) -> None:
        """Duplicate keys with different cases should use last value."""
        # This is a weird edge case - dict can't actually have duplicate keys
        # but we test the canonicalization handles case properly
        headers = {
            "content-type": "text/html",
            "Content-Type": "application/json",  # This overwrites the first
        }

        result = canonicalize_headers(headers)

        # Should have one entry, lowercased
        assert "content-type" in result
        # Python dict semantics: last value wins
        assert result["content-type"] == "application/json"

    def test_unicode_in_header_values(self) -> None:
        """Unicode in values should be preserved."""
        headers = {
            "X-Custom": "Hello 世界",
            "X-Emoji": "🎉",
        }

        result = canonicalize_headers(headers)

        assert result["x-custom"] == "Hello 世界"
        assert result["x-emoji"] == "🎉"

    def test_empty_header_values(self) -> None:
        """Empty values should be preserved after stripping."""
        headers = {
            "X-Empty": "",
            "X-Spaces": "   ",
        }

        result = canonicalize_headers(headers)

        assert result["x-empty"] == ""
        assert result["x-spaces"] == ""  # Whitespace stripped

    @given(
        headers=st.dictionaries(
            st.text(min_size=1, max_size=50),
            st.text(min_size=0, max_size=200),
            min_size=0,
            max_size=20,
        )
    )
    def test_canonicalization_is_deterministic(self, headers: dict[str, str]) -> None:
        """Canonicalization should be deterministic."""
        result1 = canonicalize_headers(headers)
        result2 = canonicalize_headers(headers)
        assert result1 == result2


class TestGetHeaderValueEdgeCases:
    """Edge case tests for get_header_value."""

    def test_empty_headers(self) -> None:
        """Empty headers should return default."""
        result = get_header_value({}, "Content-Type", "default")
        assert result == "default"

    def test_header_not_found_returns_default(self) -> None:
        """Missing header should return default."""
        headers = {"Content-Type": "application/json"}

        result = get_header_value(headers, "Authorization", "default")
        assert result == "default"

    def test_header_not_found_no_default_returns_none(self) -> None:
        """Missing header with no default should return None."""
        headers = {"Content-Type": "application/json"}

        result = get_header_value(headers, "Authorization")
        assert result is None

    def test_case_insensitive_lookup(self) -> None:
        """Lookup should be case-insensitive."""
        headers = {"Content-Type": "application/json"}

        assert get_header_value(headers, "content-type") == "application/json"
        assert get_header_value(headers, "CONTENT-TYPE") == "application/json"
        assert get_header_value(headers, "CoNtEnT-TyPe") == "application/json"

    def test_returns_first_match(self) -> None:
        """Should return first matching header (case-insensitive)."""
        # If somehow dict has duplicate keys with different cases (shouldn't happen)
        # we should get a match
        headers = {"content-type": "text/html"}

        result = get_header_value(headers, "Content-Type")
        assert result == "text/html"

    def test_empty_header_value(self) -> None:
        """Empty header value should be returned."""
        headers = {"X-Empty": ""}

        result = get_header_value(headers, "X-Empty", "default")
        assert result == ""

    def test_whitespace_header_value(self) -> None:
        """Whitespace-only value should be returned as-is."""
        headers = {"X-Spaces": "   "}

        result = get_header_value(headers, "X-Spaces")
        assert result == "   "

    def test_unicode_header_value(self) -> None:
        """Unicode values should be returned correctly."""
        headers = {"X-Custom": "Hello 世界"}

        result = get_header_value(headers, "X-Custom")
        assert result == "Hello 世界"

    def test_special_characters_in_header_name(self) -> None:
        """Special characters in header name should work."""
        headers = {"X-Custom-Header-123": "value"}

        result = get_header_value(headers, "x-custom-header-123")
        assert result == "value"

    @given(
        headers=st.dictionaries(
            st.text(min_size=1, max_size=50),
            st.text(min_size=0, max_size=200),
            min_size=1,
            max_size=20,
        )
    )
    def test_get_existing_header_always_works(self, headers: dict[str, str]) -> None:
        """Getting an existing header should always work."""
        # Pick a random header from the dict
        header_name = list(headers.keys())[0]
        expected_value = headers[header_name]

        # Should find it regardless of case
        result = get_header_value(headers, header_name.upper())
        assert result == expected_value


class TestMergeHeadersEdgeCases:
    """Edge case tests for merge_headers."""

    def test_no_dicts(self) -> None:
        """No dicts should return empty dict."""
        result = merge_headers()
        assert result == {}

    def test_single_dict(self) -> None:
        """Single dict should be returned as-is."""
        headers = {"Content-Type": "application/json"}

        result = merge_headers(headers)

        assert result == headers
        assert result is not headers  # Should be a copy

    def test_empty_dicts(self) -> None:
        """Multiple empty dicts should return empty dict."""
        result = merge_headers({}, {}, {})
        assert result == {}

    def test_non_overlapping_merge(self) -> None:
        """Non-overlapping headers should all be included."""
        h1 = {"Content-Type": "application/json"}
        h2 = {"Authorization": "Bearer token"}
        h3 = {"X-Custom": "value"}

        result = merge_headers(h1, h2, h3)

        assert len(result) == 3
        assert result["Content-Type"] == "application/json"
        assert result["Authorization"] == "Bearer token"
        assert result["X-Custom"] == "value"

    def test_later_overrides_earlier(self) -> None:
        """Later dicts should override earlier ones."""
        h1 = {"Content-Type": "text/html"}
        h2 = {"Content-Type": "application/json"}

        result = merge_headers(h1, h2)

        assert result["Content-Type"] == "application/json"

    def test_case_insensitive_override(self) -> None:
        """Override should be case-insensitive."""
        h1 = {"Content-Type": "text/html"}
        h2 = {"content-type": "application/json"}

        result = merge_headers(h1, h2)

        # Should have one entry
        assert len(result) == 1

        # Key case from last dict should be used
        assert "content-type" in result
        assert result["content-type"] == "application/json"

    def test_preserves_last_key_case(self) -> None:
        """Should preserve key case from last dict."""
        h1 = {"CONTENT-TYPE": "text/html"}
        h2 = {"Content-Type": "application/xml"}
        h3 = {"content-type": "application/json"}

        result = merge_headers(h1, h2, h3)

        assert "content-type" in result
        assert "Content-Type" not in result
        assert "CONTENT-TYPE" not in result

    def test_does_not_mutate_originals(self) -> None:
        """Original dicts should not be mutated."""
        h1 = {"Content-Type": "text/html"}
        h2 = {"Authorization": "Bearer token"}

        h1_copy = h1.copy()
        h2_copy = h2.copy()

        merge_headers(h1, h2)

        assert h1 == h1_copy
        assert h2 == h2_copy

    def test_unicode_values(self) -> None:
        """Unicode values should be preserved."""
        h1 = {"X-Custom": "Hello"}
        h2 = {"X-Custom": "世界"}

        result = merge_headers(h1, h2)

        assert result["X-Custom"] == "世界"

    def test_empty_values(self) -> None:
        """Empty values should be preserved."""
        h1 = {"X-Empty": "value"}
        h2 = {"X-Empty": ""}

        result = merge_headers(h1, h2)

        assert result["X-Empty"] == ""

    def test_many_dicts(self) -> None:
        """Merging many dicts should work."""
        dicts = [{f"Header-{i}": f"value-{i}"} for i in range(100)]

        result = merge_headers(*dicts)

        assert len(result) == 100
        for i in range(100):
            assert result[f"Header-{i}"] == f"value-{i}"

    def test_complex_override_chain(self) -> None:
        """Complex chain of overrides should work correctly."""
        h1 = {"A": "1", "B": "1", "C": "1"}
        h2 = {"a": "2", "B": "2"}  # Override A (case-insensitive) and B
        h3 = {"c": "3"}  # Override C (case-insensitive)

        result = merge_headers(h1, h2, h3)

        assert len(result) == 3
        assert result["a"] == "2"  # Last case for A
        assert result["B"] == "2"  # Last case for B
        assert result["c"] == "3"  # Last case for C
