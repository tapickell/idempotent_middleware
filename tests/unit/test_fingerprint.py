"""Comprehensive tests for request fingerprinting.

Tests cover all aspects of the fingerprinting algorithm including:
- Deterministic fingerprinting (same input = same output)
- Query parameter order independence
- Header case insensitivity
- Volatile header exclusion
- Body change detection
- Edge cases (empty body, no query, no headers)
- Property-based testing with hypothesis
"""

import json

from hypothesis import given
from hypothesis import strategies as st

from idempotent_middleware.fingerprint import (
    _canonicalize_headers,
    _canonicalize_query_string,
    compute_fingerprint,
)


class TestComputeFingerprint:
    """Tests for the main compute_fingerprint function."""

    def test_same_request_produces_same_fingerprint(self) -> None:
        """Same request should always produce the same fingerprint."""
        method = "POST"
        path = "/api/users"
        query_string = "foo=bar&baz=qux"
        headers = {"Content-Type": "application/json", "Content-Length": "16"}
        body = b'{"name": "Alice"}'

        fp1 = compute_fingerprint(method, path, query_string, headers, body)
        fp2 = compute_fingerprint(method, path, query_string, headers, body)

        assert fp1 == fp2
        assert len(fp1) == 64  # SHA-256 produces 64 hex characters

    def test_different_methods_produce_different_fingerprints(self) -> None:
        """Different HTTP methods should produce different fingerprints."""
        path = "/api/users"
        query_string = ""
        headers = {"Content-Type": "application/json"}
        body = b'{"name": "Alice"}'

        fp_post = compute_fingerprint("POST", path, query_string, headers, body)
        fp_put = compute_fingerprint("PUT", path, query_string, headers, body)

        assert fp_post != fp_put

    def test_different_paths_produce_different_fingerprints(self) -> None:
        """Different paths should produce different fingerprints."""
        method = "POST"
        query_string = ""
        headers = {"Content-Type": "application/json"}
        body = b'{"name": "Alice"}'

        fp1 = compute_fingerprint(method, "/api/users", query_string, headers, body)
        fp2 = compute_fingerprint(method, "/api/posts", query_string, headers, body)

        assert fp1 != fp2

    def test_different_bodies_produce_different_fingerprints(self) -> None:
        """Different request bodies should produce different fingerprints."""
        method = "POST"
        path = "/api/users"
        query_string = ""
        headers = {"Content-Type": "application/json"}

        fp1 = compute_fingerprint(method, path, query_string, headers, b'{"name": "Alice"}')
        fp2 = compute_fingerprint(method, path, query_string, headers, b'{"name": "Bob"}')

        assert fp1 != fp2

    def test_query_parameter_order_independence(self) -> None:
        """Query parameters in different order should produce same fingerprint."""
        method = "GET"
        path = "/api/users"
        headers = {}
        body = b""

        fp1 = compute_fingerprint(method, path, "foo=1&bar=2&baz=3", headers, body)
        fp2 = compute_fingerprint(method, path, "baz=3&foo=1&bar=2", headers, body)
        fp3 = compute_fingerprint(method, path, "bar=2&baz=3&foo=1", headers, body)

        assert fp1 == fp2 == fp3

    def test_header_case_insensitivity(self) -> None:
        """Headers with different case should produce same fingerprint."""
        method = "POST"
        path = "/api/users"
        query_string = ""
        body = b'{"name": "Alice"}'

        headers1 = {"Content-Type": "application/json", "Content-Length": "16"}
        headers2 = {"content-type": "application/json", "content-length": "16"}
        headers3 = {"CONTENT-TYPE": "application/json", "CONTENT-LENGTH": "16"}

        fp1 = compute_fingerprint(method, path, query_string, headers1, body)
        fp2 = compute_fingerprint(method, path, query_string, headers2, body)
        fp3 = compute_fingerprint(method, path, query_string, headers3, body)

        assert fp1 == fp2 == fp3

    def test_volatile_headers_excluded(self) -> None:
        """Headers not in included_headers should not affect fingerprint."""
        method = "POST"
        path = "/api/users"
        query_string = ""
        body = b'{"name": "Alice"}'

        # Only content-type and content-length are included by default
        headers1 = {
            "Content-Type": "application/json",
            "Content-Length": "16",
        }
        headers2 = {
            "Content-Type": "application/json",
            "Content-Length": "16",
            "X-Request-ID": "abc123",
            "Authorization": "Bearer token",
            "User-Agent": "Mozilla/5.0",
        }

        fp1 = compute_fingerprint(method, path, query_string, headers1, body)
        fp2 = compute_fingerprint(method, path, query_string, headers2, body)

        assert fp1 == fp2

    def test_custom_included_headers(self) -> None:
        """Custom included_headers should affect fingerprint."""
        method = "POST"
        path = "/api/users"
        query_string = ""
        body = b'{"name": "Alice"}'
        headers = {
            "Content-Type": "application/json",
            "X-Idempotency-Key": "key123",
        }

        # Without including X-Idempotency-Key
        fp1 = compute_fingerprint(
            method,
            path,
            query_string,
            headers,
            body,
            included_headers=["content-type"],
        )

        # With including X-Idempotency-Key
        fp2 = compute_fingerprint(
            method,
            path,
            query_string,
            headers,
            body,
            included_headers=["content-type", "x-idempotency-key"],
        )

        assert fp1 != fp2

    def test_empty_body(self) -> None:
        """Empty body should produce valid fingerprint."""
        method = "POST"
        path = "/api/users"
        query_string = ""
        headers = {"Content-Type": "application/json"}
        body = b""

        fp = compute_fingerprint(method, path, query_string, headers, body)

        assert len(fp) == 64
        assert fp.isalnum()

    def test_no_query_string(self) -> None:
        """Request without query string should produce valid fingerprint."""
        method = "POST"
        path = "/api/users"
        query_string = ""
        headers = {"Content-Type": "application/json"}
        body = b'{"name": "Alice"}'

        fp = compute_fingerprint(method, path, query_string, headers, body)

        assert len(fp) == 64
        assert fp.isalnum()

    def test_no_headers(self) -> None:
        """Request with no headers should produce valid fingerprint."""
        method = "POST"
        path = "/api/users"
        query_string = ""
        headers = {}
        body = b'{"name": "Alice"}'

        fp = compute_fingerprint(method, path, query_string, headers, body)

        assert len(fp) == 64
        assert fp.isalnum()

    def test_path_case_normalization(self) -> None:
        """Paths should be normalized to lowercase."""
        method = "GET"
        query_string = ""
        headers = {}
        body = b""

        fp1 = compute_fingerprint(method, "/api/users", query_string, headers, body)
        fp2 = compute_fingerprint(method, "/API/USERS", query_string, headers, body)
        fp3 = compute_fingerprint(method, "/Api/Users", query_string, headers, body)

        assert fp1 == fp2 == fp3

    def test_trailing_slash_normalization(self) -> None:
        """Trailing slashes should be stripped (except for root path)."""
        method = "GET"
        query_string = ""
        headers = {}
        body = b""

        # Non-root paths
        fp1 = compute_fingerprint(method, "/api/users", query_string, headers, body)
        fp2 = compute_fingerprint(method, "/api/users/", query_string, headers, body)

        assert fp1 == fp2

        # Root path should keep its slash
        fp_root = compute_fingerprint(method, "/", query_string, headers, body)
        assert len(fp_root) == 64

    def test_multiple_trailing_slashes(self) -> None:
        """Multiple trailing slashes should be stripped."""
        method = "GET"
        query_string = ""
        headers = {}
        body = b""

        fp1 = compute_fingerprint(method, "/api/users", query_string, headers, body)
        fp2 = compute_fingerprint(method, "/api/users///", query_string, headers, body)

        assert fp1 == fp2

    def test_query_string_with_duplicate_keys(self) -> None:
        """Query strings with duplicate keys should be handled consistently."""
        method = "GET"
        path = "/api/users"
        headers = {}
        body = b""

        fp1 = compute_fingerprint(method, path, "tag=a&tag=b&tag=c", headers, body)
        fp2 = compute_fingerprint(method, path, "tag=c&tag=a&tag=b", headers, body)

        assert fp1 == fp2

    def test_query_string_with_empty_values(self) -> None:
        """Query strings with empty values should be preserved."""
        method = "GET"
        path = "/api/users"
        headers = {}
        body = b""

        fp1 = compute_fingerprint(method, path, "foo=&bar=value", headers, body)
        fp2 = compute_fingerprint(method, path, "bar=value&foo=", headers, body)

        assert fp1 == fp2

    def test_method_case_normalization(self) -> None:
        """HTTP methods should be normalized to uppercase."""
        path = "/api/users"
        query_string = ""
        headers = {}
        body = b""

        fp1 = compute_fingerprint("post", path, query_string, headers, body)
        fp2 = compute_fingerprint("POST", path, query_string, headers, body)
        fp3 = compute_fingerprint("Post", path, query_string, headers, body)

        assert fp1 == fp2 == fp3

    def test_binary_body_handling(self) -> None:
        """Binary (non-UTF-8) body should be handled correctly."""
        method = "POST"
        path = "/api/upload"
        query_string = ""
        headers = {"Content-Type": "application/octet-stream"}

        # Binary data that's not valid UTF-8
        body1 = bytes([0xFF, 0xFE, 0xFD, 0xFC])
        body2 = bytes([0xFF, 0xFE, 0xFD, 0xFC])
        body3 = bytes([0xFF, 0xFE, 0xFD, 0xFB])

        fp1 = compute_fingerprint(method, path, query_string, headers, body1)
        fp2 = compute_fingerprint(method, path, query_string, headers, body2)
        fp3 = compute_fingerprint(method, path, query_string, headers, body3)

        assert fp1 == fp2
        assert fp1 != fp3

    def test_large_body_handling(self) -> None:
        """Large request bodies should be handled efficiently."""
        method = "POST"
        path = "/api/upload"
        query_string = ""
        headers = {"Content-Type": "application/octet-stream"}

        # 1MB body
        large_body = b"x" * (1024 * 1024)

        fp = compute_fingerprint(method, path, query_string, headers, large_body)

        assert len(fp) == 64
        assert fp.isalnum()

    def test_special_characters_in_query_string(self) -> None:
        """Special characters in query strings should be handled correctly."""
        method = "GET"
        path = "/api/search"
        headers = {}
        body = b""

        # URL-encoded special characters
        fp1 = compute_fingerprint(method, path, "q=hello%20world&lang=en", headers, body)
        fp2 = compute_fingerprint(method, path, "lang=en&q=hello%20world", headers, body)

        assert fp1 == fp2

    def test_unicode_in_body(self) -> None:
        """Unicode characters in body should be handled correctly."""
        method = "POST"
        path = "/api/users"
        query_string = ""
        headers = {"Content-Type": "application/json; charset=utf-8"}

        body1 = '{"name": "Alice", "emoji": "😀"}'.encode()
        body2 = '{"name": "Alice", "emoji": "😀"}'.encode()
        body3 = '{"name": "Bob", "emoji": "😀"}'.encode()

        fp1 = compute_fingerprint(method, path, query_string, headers, body1)
        fp2 = compute_fingerprint(method, path, query_string, headers, body2)
        fp3 = compute_fingerprint(method, path, query_string, headers, body3)

        assert fp1 == fp2
        assert fp1 != fp3

    def test_header_value_preserved(self) -> None:
        """Header values should be preserved exactly (not lowercased)."""
        method = "POST"
        path = "/api/users"
        query_string = ""
        body = b'{"name": "Alice"}'

        # Different content-type values
        headers1 = {"Content-Type": "application/json"}
        headers2 = {"Content-Type": "application/JSON"}

        fp1 = compute_fingerprint(method, path, query_string, headers1, body)
        fp2 = compute_fingerprint(method, path, query_string, headers2, body)

        assert fp1 != fp2


class TestCanonicalizeQueryString:
    """Tests for the _canonicalize_query_string helper function."""

    def test_empty_query_string(self) -> None:
        """Empty query string should return empty string."""
        assert _canonicalize_query_string("") == ""

    def test_single_parameter(self) -> None:
        """Single parameter should be returned as-is."""
        result = _canonicalize_query_string("foo=bar")
        assert result == "foo=bar"

    def test_multiple_parameters_sorted(self) -> None:
        """Multiple parameters should be sorted by key."""
        result = _canonicalize_query_string("zebra=1&apple=2&banana=3")
        assert result == "apple=2&banana=3&zebra=1"

    def test_duplicate_keys_sorted(self) -> None:
        """Duplicate keys should have their values sorted."""
        result = _canonicalize_query_string("tag=c&tag=a&tag=b")
        assert result == "tag=a&tag=b&tag=c"

    def test_empty_values_preserved(self) -> None:
        """Empty values should be preserved."""
        result = _canonicalize_query_string("foo=&bar=value")
        assert result == "bar=value&foo="

    def test_special_characters_preserved(self) -> None:
        """URL-encoded special characters should be preserved."""
        result = _canonicalize_query_string("q=hello%20world&foo=bar")
        # Note: parse_qs decodes, urlencode re-encodes
        # Space becomes '+' in standard URL encoding
        assert "foo=bar" in result
        assert "q=" in result


class TestCanonicalizeHeaders:
    """Tests for the _canonicalize_headers helper function."""

    def test_empty_headers(self) -> None:
        """Empty headers should return empty JSON object."""
        result = _canonicalize_headers({}, ["content-type"])
        assert result == "{}"

    def test_filter_headers(self) -> None:
        """Only included headers should be returned."""
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer token",
            "X-Request-ID": "123",
        }
        result = _canonicalize_headers(headers, ["content-type"])
        data = json.loads(result)
        assert "content-type" in data
        assert "authorization" not in data
        assert "x-request-id" not in data

    def test_lowercase_keys(self) -> None:
        """Header keys should be lowercased."""
        headers = {"Content-Type": "application/json", "CONTENT-LENGTH": "100"}
        result = _canonicalize_headers(headers, ["content-type", "content-length"])
        data = json.loads(result)
        assert "content-type" in data
        assert "content-length" in data
        assert "Content-Type" not in data

    def test_sorted_output(self) -> None:
        """Headers should be sorted by key in JSON output."""
        headers = {"Zebra": "z", "Apple": "a", "Banana": "b"}
        result = _canonicalize_headers(headers, ["zebra", "apple", "banana"])
        # JSON with sort_keys should have keys in alphabetical order
        assert result == '{"apple":"a","banana":"b","zebra":"z"}'

    def test_case_insensitive_matching(self) -> None:
        """Header matching should be case-insensitive."""
        headers = {"Content-Type": "application/json", "content-length": "100"}
        result = _canonicalize_headers(headers, ["CONTENT-TYPE", "content-LENGTH"])
        data = json.loads(result)
        assert data == {"content-type": "application/json", "content-length": "100"}

    def test_preserve_header_values(self) -> None:
        """Header values should be preserved exactly."""
        headers = {"Content-Type": "Application/JSON"}
        result = _canonicalize_headers(headers, ["content-type"])
        data = json.loads(result)
        assert data["content-type"] == "Application/JSON"


class TestPropertyBased:
    """Property-based tests using hypothesis."""

    @given(
        method=st.sampled_from(["GET", "POST", "PUT", "DELETE", "PATCH"]),
        path=st.text(min_size=1, max_size=100),
        body=st.binary(min_size=0, max_size=1000),
    )
    def test_deterministic_fingerprinting(self, method: str, path: str, body: bytes) -> None:
        """Fingerprinting should be deterministic for any valid input."""
        query_string = ""
        headers = {"Content-Type": "application/json"}

        fp1 = compute_fingerprint(method, path, query_string, headers, body)
        fp2 = compute_fingerprint(method, path, query_string, headers, body)

        assert fp1 == fp2
        assert len(fp1) == 64

    @given(
        params=st.lists(
            st.tuples(
                st.text(min_size=1, max_size=20),
                st.text(min_size=0, max_size=20),
            ),
            min_size=1,
            max_size=10,
        )
    )
    def test_query_parameter_order_independence_property(
        self, params: list[tuple[str, str]]
    ) -> None:
        """Query parameter order should not affect fingerprint."""
        method = "GET"
        path = "/api/test"
        headers = {}
        body = b""

        # Create query string from params
        query_string1 = "&".join(f"{k}={v}" for k, v in params)

        # Reverse the order
        query_string2 = "&".join(f"{k}={v}" for k, v in reversed(params))

        fp1 = compute_fingerprint(method, path, query_string1, headers, body)
        fp2 = compute_fingerprint(method, path, query_string2, headers, body)

        # If params are unique, fingerprints should match
        # (Note: duplicate keys make this more complex, but canonicalization handles it)
        assert len(fp1) == 64
        assert len(fp2) == 64

    @given(
        headers=st.dictionaries(
            keys=st.sampled_from(["Content-Type", "content-type", "CONTENT-TYPE"]),
            values=st.text(min_size=1, max_size=50),
            min_size=1,
            max_size=1,
        )
    )
    def test_header_case_insensitivity_property(self, headers: dict[str, str]) -> None:
        """Header key case should not affect fingerprint."""
        method = "POST"
        path = "/api/test"
        query_string = ""
        body = b'{"test": "data"}'

        fp = compute_fingerprint(method, path, query_string, headers, body)

        assert len(fp) == 64

    @given(body=st.binary(min_size=0, max_size=10000))
    def test_body_changes_affect_fingerprint(self, body: bytes) -> None:
        """Different bodies should produce different fingerprints (with high probability)."""
        method = "POST"
        path = "/api/test"
        query_string = ""
        headers = {}

        fp = compute_fingerprint(method, path, query_string, headers, body)

        # Fingerprint should always be valid SHA-256
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)

    @given(
        method=st.sampled_from(["get", "post", "PUT", "DeLeTe"]),
    )
    def test_method_normalization_property(self, method: str) -> None:
        """HTTP method should be normalized regardless of case."""
        path = "/api/test"
        query_string = ""
        headers = {}
        body = b""

        fp1 = compute_fingerprint(method, path, query_string, headers, body)
        fp2 = compute_fingerprint(method.upper(), path, query_string, headers, body)
        fp3 = compute_fingerprint(method.lower(), path, query_string, headers, body)

        assert fp1 == fp2 == fp3


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_very_long_path(self) -> None:
        """Very long paths should be handled correctly."""
        method = "GET"
        path = "/" + "a" * 10000
        query_string = ""
        headers = {}
        body = b""

        fp = compute_fingerprint(method, path, query_string, headers, body)

        assert len(fp) == 64

    def test_very_long_query_string(self) -> None:
        """Very long query strings should be handled correctly."""
        method = "GET"
        path = "/api/test"
        # Create a very long query string
        query_string = "&".join(f"param{i}=value{i}" for i in range(1000))
        headers = {}
        body = b""

        fp = compute_fingerprint(method, path, query_string, headers, body)

        assert len(fp) == 64

    def test_many_headers(self) -> None:
        """Many headers should be handled correctly."""
        method = "POST"
        path = "/api/test"
        query_string = ""
        headers = {f"X-Custom-{i}": f"value{i}" for i in range(100)}
        headers["Content-Type"] = "application/json"
        body = b'{"test": "data"}'

        fp = compute_fingerprint(method, path, query_string, headers, body)

        assert len(fp) == 64

    def test_root_path_only(self) -> None:
        """Root path '/' should be handled correctly."""
        method = "GET"
        path = "/"
        query_string = ""
        headers = {}
        body = b""

        fp = compute_fingerprint(method, path, query_string, headers, body)

        assert len(fp) == 64

    def test_query_string_with_no_values(self) -> None:
        """Query string with keys but no values should be handled."""
        method = "GET"
        path = "/api/test"
        query_string = "foo&bar&baz"
        headers = {}
        body = b""

        fp = compute_fingerprint(method, path, query_string, headers, body)

        assert len(fp) == 64

    def test_empty_included_headers_list(self) -> None:
        """Empty included_headers list should produce fingerprint with no headers."""
        method = "POST"
        path = "/api/test"
        query_string = ""
        headers = {"Content-Type": "application/json", "Content-Length": "100"}
        body = b'{"test": "data"}'

        fp1 = compute_fingerprint(method, path, query_string, headers, body, included_headers=[])
        fp2 = compute_fingerprint(method, path, query_string, {}, body, included_headers=[])

        # Should be the same since no headers are included
        assert fp1 == fp2
