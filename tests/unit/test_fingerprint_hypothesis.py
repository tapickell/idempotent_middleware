"""Property-based tests for fingerprint module using Hypothesis.

This test suite verifies that fingerprinting behaves correctly across
diverse inputs including edge cases, unicode, large bodies, and ensures
proper canonicalization.
"""

import json
from urllib.parse import parse_qs, urlencode

from hypothesis import assume, given
from hypothesis import strategies as st

from idempotent_middleware.fingerprint import (
    _canonicalize_headers,
    _canonicalize_query_string,
    compute_fingerprint,
)

# Strategies for HTTP components
http_method_strategy = st.sampled_from(["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])

# Path strategy - realistic URL paths
path_strategy = st.one_of(
    st.just("/"),
    st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="/-_"),
        min_size=1,
        max_size=100,
    ).map(lambda s: "/" + s.strip("/")),
)

# Query string strategy
query_param_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")), min_size=1, max_size=20
)
query_value_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters=" "),
    min_size=0,
    max_size=50,
)
query_dict_strategy = st.dictionaries(
    query_param_strategy, query_value_strategy, min_size=0, max_size=10
)

# Header strategy
header_name_strategy = st.sampled_from(
    ["Content-Type", "Content-Length", "Authorization", "X-Request-ID", "User-Agent"]
)
header_value_strategy = st.text(min_size=0, max_size=200)
headers_dict_strategy = st.dictionaries(
    header_name_strategy, header_value_strategy, min_size=0, max_size=10
)

# Body strategy - various byte patterns
body_strategy = st.one_of(
    st.binary(min_size=0, max_size=10000),
    st.text(min_size=0, max_size=5000).map(lambda s: s.encode("utf-8")),
    st.just(b""),
    st.builds(json.dumps, st.dictionaries(st.text(min_size=1, max_size=20), st.integers())).map(
        lambda s: s.encode("utf-8")
    ),
)


class TestFingerprintProperties:
    """Property-based tests for compute_fingerprint function."""

    @given(
        method=http_method_strategy,
        path=path_strategy,
        query=query_dict_strategy,
        headers=headers_dict_strategy,
        body=body_strategy,
    )
    def test_fingerprint_is_deterministic(
        self,
        method: str,
        path: str,
        query: dict[str, str],
        headers: dict[str, str],
        body: bytes,
    ) -> None:
        """Same inputs should always produce the same fingerprint."""
        query_string = urlencode(query)

        fp1 = compute_fingerprint(method, path, query_string, headers, body)
        fp2 = compute_fingerprint(method, path, query_string, headers, body)

        assert fp1 == fp2

    @given(
        method=http_method_strategy,
        path=path_strategy,
        query=query_dict_strategy,
        headers=headers_dict_strategy,
        body=body_strategy,
    )
    def test_fingerprint_is_valid_sha256(
        self,
        method: str,
        path: str,
        query: dict[str, str],
        headers: dict[str, str],
        body: bytes,
    ) -> None:
        """Fingerprint should always be a valid SHA-256 hash."""
        query_string = urlencode(query)

        fp = compute_fingerprint(method, path, query_string, headers, body)

        # Should be 64 hex characters
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)

    @given(
        method=http_method_strategy,
        path=path_strategy,
        query=query_dict_strategy,
        headers=headers_dict_strategy,
        body=body_strategy,
    )
    def test_method_case_insensitive(
        self,
        method: str,
        path: str,
        query: dict[str, str],
        headers: dict[str, str],
        body: bytes,
    ) -> None:
        """Method case should not affect fingerprint (canonicalized to uppercase)."""
        query_string = urlencode(query)

        fp1 = compute_fingerprint(method.upper(), path, query_string, headers, body)
        fp2 = compute_fingerprint(method.lower(), path, query_string, headers, body)
        fp3 = compute_fingerprint(method.title(), path, query_string, headers, body)

        assert fp1 == fp2 == fp3

    @given(
        method=http_method_strategy,
        body=body_strategy,
    )
    def test_path_case_insensitive(
        self,
        method: str,
        body: bytes,
    ) -> None:
        """Path case should not affect fingerprint (canonicalized to lowercase)."""
        path1 = "/api/users"
        path2 = "/API/USERS"
        path3 = "/Api/Users"

        fp1 = compute_fingerprint(method, path1, "", {}, body)
        fp2 = compute_fingerprint(method, path2, "", {}, body)
        fp3 = compute_fingerprint(method, path3, "", {}, body)

        assert fp1 == fp2 == fp3

    @given(
        method=http_method_strategy,
        body=body_strategy,
    )
    def test_trailing_slash_normalized(
        self,
        method: str,
        body: bytes,
    ) -> None:
        """Trailing slashes should be normalized (except for root)."""
        fp1 = compute_fingerprint(method, "/api/users", "", {}, body)
        fp2 = compute_fingerprint(method, "/api/users/", "", {}, body)

        # Should be the same (trailing slash removed)
        assert fp1 == fp2

        # But root path with and without slash should be same
        fp_root1 = compute_fingerprint(method, "/", "", {}, body)
        fp_root2 = compute_fingerprint(method, "", "", {}, body)

        # Root should keep the slash
        # Empty path becomes root
        assert fp_root1 == fp_root2

    @given(
        method=http_method_strategy,
        path=path_strategy,
        body=body_strategy,
    )
    def test_query_param_order_doesnt_matter(
        self,
        method: str,
        path: str,
        body: bytes,
    ) -> None:
        """Query parameter order should not affect fingerprint."""
        query1 = "c=3&a=1&b=2"
        query2 = "a=1&b=2&c=3"
        query3 = "b=2&c=3&a=1"

        fp1 = compute_fingerprint(method, path, query1, {}, body)
        fp2 = compute_fingerprint(method, path, query2, {}, body)
        fp3 = compute_fingerprint(method, path, query3, {}, body)

        assert fp1 == fp2 == fp3

    @given(
        method=http_method_strategy,
        path=path_strategy,
        query=query_dict_strategy,
        body=body_strategy,
    )
    def test_header_case_doesnt_matter_in_included_headers(
        self,
        method: str,
        path: str,
        query: dict[str, str],
        body: bytes,
    ) -> None:
        """Header key case should not affect fingerprint."""
        query_string = urlencode(query)

        headers1 = {"Content-Type": "application/json"}
        headers2 = {"content-type": "application/json"}
        headers3 = {"CONTENT-TYPE": "application/json"}

        fp1 = compute_fingerprint(method, path, query_string, headers1, body, ["content-type"])
        fp2 = compute_fingerprint(method, path, query_string, headers2, body, ["content-type"])
        fp3 = compute_fingerprint(method, path, query_string, headers3, body, ["content-type"])

        assert fp1 == fp2 == fp3

    @given(
        method=http_method_strategy,
        path=path_strategy,
        query=query_dict_strategy,
        body=body_strategy,
    )
    def test_excluded_headers_dont_affect_fingerprint(
        self,
        method: str,
        path: str,
        query: dict[str, str],
        body: bytes,
    ) -> None:
        """Headers not in included list should not affect fingerprint."""
        query_string = urlencode(query)

        headers1 = {"Content-Type": "application/json"}
        headers2 = {"Content-Type": "application/json", "X-Request-ID": "abc123"}
        headers3 = {"Content-Type": "application/json", "Authorization": "Bearer token"}

        # Only include content-type
        fp1 = compute_fingerprint(method, path, query_string, headers1, body, ["content-type"])
        fp2 = compute_fingerprint(method, path, query_string, headers2, body, ["content-type"])
        fp3 = compute_fingerprint(method, path, query_string, headers3, body, ["content-type"])

        # Should all be the same since excluded headers are ignored
        assert fp1 == fp2 == fp3

    @given(body1=body_strategy, body2=body_strategy)
    def test_different_bodies_produce_different_fingerprints(
        self,
        body1: bytes,
        body2: bytes,
    ) -> None:
        """Different body content should produce different fingerprints."""
        assume(body1 != body2)

        fp1 = compute_fingerprint("POST", "/api/test", "", {}, body1)
        fp2 = compute_fingerprint("POST", "/api/test", "", {}, body2)

        assert fp1 != fp2

    @given(
        method=http_method_strategy,
        path=path_strategy,
        query=query_dict_strategy,
        headers=headers_dict_strategy,
    )
    def test_empty_body_produces_consistent_hash(
        self,
        method: str,
        path: str,
        query: dict[str, str],
        headers: dict[str, str],
    ) -> None:
        """Empty body should produce consistent fingerprint."""
        query_string = urlencode(query)

        fp1 = compute_fingerprint(method, path, query_string, headers, b"")
        fp2 = compute_fingerprint(method, path, query_string, headers, b"")

        assert fp1 == fp2

    @given(text=st.text(min_size=0, max_size=10000))
    def test_unicode_body_handled_correctly(self, text: str) -> None:
        """Unicode text in body should be handled correctly."""
        body = text.encode("utf-8")

        fp1 = compute_fingerprint("POST", "/api/test", "", {}, body)
        fp2 = compute_fingerprint("POST", "/api/test", "", {}, body)

        # Should be deterministic
        assert fp1 == fp2

        # Should be valid SHA-256
        assert len(fp1) == 64
        assert all(c in "0123456789abcdef" for c in fp1)

    @given(size=st.integers(min_value=0, max_value=1_000_000))
    def test_large_body_handled_correctly(self, size: int) -> None:
        """Large bodies should be handled correctly."""
        # Create a large body with repeating pattern
        body = (b"x" * 1000)[:size]

        fp = compute_fingerprint("POST", "/api/test", "", {}, body)

        # Should be valid SHA-256
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)


class TestQueryStringCanonicalization:
    """Property-based tests for query string canonicalization."""

    @given(query=query_dict_strategy)
    def test_query_canonicalization_is_deterministic(self, query: dict[str, str]) -> None:
        """Canonicalization should be deterministic."""
        query_string = urlencode(query)

        canonical1 = _canonicalize_query_string(query_string)
        canonical2 = _canonicalize_query_string(query_string)

        assert canonical1 == canonical2

    @given(query=query_dict_strategy)
    def test_query_canonicalization_sorts_params(self, query: dict[str, str]) -> None:
        """Canonicalization should sort parameters."""
        if not query:
            return

        query_string = urlencode(query)
        canonical = _canonicalize_query_string(query_string)

        # Parse the canonical form
        parsed = parse_qs(canonical, keep_blank_values=True)

        # Keys should be in sorted order
        keys = list(parsed.keys())
        assert keys == sorted(keys)

    def test_empty_query_string_returns_empty(self) -> None:
        """Empty query string should return empty string."""
        assert _canonicalize_query_string("") == ""
        assert _canonicalize_query_string("   ") == ""

    @given(
        data=st.lists(
            st.tuples(query_param_strategy, query_value_strategy),
            min_size=1,
            max_size=10,
        )
    )
    def test_query_with_repeated_keys_sorted(self, data: list[tuple[str, str]]) -> None:
        """Repeated query parameters should be sorted."""
        query_string = urlencode(data)
        canonical = _canonicalize_query_string(query_string)

        # Should be deterministic
        canonical2 = _canonicalize_query_string(query_string)
        assert canonical == canonical2


class TestHeaderCanonicalization:
    """Property-based tests for header canonicalization."""

    @given(
        headers=headers_dict_strategy,
        included=st.lists(header_name_strategy, min_size=0, max_size=5, unique=True),
    )
    def test_header_canonicalization_is_deterministic(
        self,
        headers: dict[str, str],
        included: list[str],
    ) -> None:
        """Header canonicalization should be deterministic."""
        canonical1 = _canonicalize_headers(headers, included)
        canonical2 = _canonicalize_headers(headers, included)

        assert canonical1 == canonical2

    @given(headers=headers_dict_strategy)
    def test_header_canonicalization_produces_valid_json(
        self,
        headers: dict[str, str],
    ) -> None:
        """Canonicalized headers should be valid JSON."""
        canonical = _canonicalize_headers(headers, list(headers.keys()))

        # Should be parseable JSON
        parsed = json.loads(canonical)
        assert isinstance(parsed, dict)

    @given(headers=headers_dict_strategy)
    def test_header_canonicalization_lowercases_keys(
        self,
        headers: dict[str, str],
    ) -> None:
        """Header keys should be lowercased."""
        canonical = _canonicalize_headers(headers, list(headers.keys()))

        parsed = json.loads(canonical)
        for key in parsed:
            assert key.islower() or not key.isalpha()

    @given(
        value=header_value_strategy,
    )
    def test_header_case_insensitive_matching(self, value: str) -> None:
        """Header matching should be case-insensitive."""
        headers1 = {"Content-Type": value}
        headers2 = {"content-type": value}
        headers3 = {"CONTENT-TYPE": value}

        canonical1 = _canonicalize_headers(headers1, ["content-type"])
        canonical2 = _canonicalize_headers(headers2, ["content-type"])
        canonical3 = _canonicalize_headers(headers3, ["content-type"])

        assert canonical1 == canonical2 == canonical3

    def test_empty_headers_returns_empty_json(self) -> None:
        """Empty headers should return empty JSON object."""
        canonical = _canonicalize_headers({}, [])
        assert canonical == "{}"

    @given(headers=headers_dict_strategy)
    def test_filtering_to_included_headers_only(self, headers: dict[str, str]) -> None:
        """Only included headers should appear in canonical form."""
        if not headers:
            return

        # Include only first header
        included = [list(headers.keys())[0]]

        canonical = _canonicalize_headers(headers, included)
        parsed = json.loads(canonical)

        # Should only have one key
        assert len(parsed) <= 1

        # If non-empty, key should be lowercase version of included header
        if parsed:
            assert list(parsed.keys())[0] == included[0].lower()


class TestFingerprintEdgeCases:
    """Edge cases and special scenarios for fingerprinting."""

    def test_null_bytes_in_body_handled(self) -> None:
        """Null bytes in body should be handled correctly."""
        body = b"hello\x00world"

        fp = compute_fingerprint("POST", "/api/test", "", {}, body)

        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)

    def test_binary_data_in_body(self) -> None:
        """Random binary data should be handled correctly."""
        body = bytes(range(256))

        fp = compute_fingerprint("POST", "/api/test", "", {}, body)

        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)

    @given(
        emoji=st.text(
            alphabet=st.characters(whitelist_categories=("So",)), min_size=1, max_size=100
        )
    )
    def test_emoji_in_body(self, emoji: str) -> None:
        """Emoji in body should be handled correctly."""
        body = emoji.encode("utf-8")

        fp = compute_fingerprint("POST", "/api/test", "", {}, body)

        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)

    def test_very_long_path(self) -> None:
        """Very long paths should be handled correctly."""
        path = "/" + "a" * 10000

        fp = compute_fingerprint("GET", path, "", {}, b"")

        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)

    def test_many_query_params(self) -> None:
        """Many query parameters should be handled correctly."""
        params = {f"param{i}": f"value{i}" for i in range(1000)}
        query_string = urlencode(params)

        fp = compute_fingerprint("GET", "/api/test", query_string, {}, b"")

        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)

    def test_special_characters_in_query(self) -> None:
        """Special characters in query parameters should be handled correctly."""
        query_string = "key=%20%21%40%23%24%25%5E%26%2A%28%29"

        fp = compute_fingerprint("GET", "/api/test", query_string, {}, b"")

        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)
