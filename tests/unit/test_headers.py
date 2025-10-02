"""Unit tests for header filtering utilities."""

from idempotent_middleware.utils.headers import (
    VOLATILE_HEADERS,
    add_replay_headers,
    canonicalize_headers,
    filter_response_headers,
    get_header_value,
    merge_headers,
)


class TestFilterResponseHeaders:
    """Tests for filter_response_headers function."""

    def test_removes_volatile_headers(self):
        """Should remove all volatile headers."""
        headers = {
            "Content-Type": "application/json",
            "Date": "Mon, 01 Oct 2025 12:00:00 GMT",
            "Server": "nginx/1.18.0",
            "Connection": "keep-alive",
            "Transfer-Encoding": "chunked",
        }

        filtered = filter_response_headers(headers)

        assert filtered == {"Content-Type": "application/json"}
        assert "Date" not in filtered
        assert "Server" not in filtered
        assert "Connection" not in filtered
        assert "Transfer-Encoding" not in filtered

    def test_preserves_non_volatile_headers(self):
        """Should preserve non-volatile headers."""
        headers = {
            "Content-Type": "application/json",
            "Content-Length": "42",
            "X-Custom-Header": "value",
            "Cache-Control": "no-cache",
        }

        filtered = filter_response_headers(headers)

        assert filtered == headers

    def test_case_insensitive_filtering(self):
        """Should filter headers regardless of case."""
        headers = {
            "Content-Type": "application/json",
            "DATE": "Mon, 01 Oct 2025 12:00:00 GMT",
            "Server": "nginx",
            "CONNECTION": "close",
        }

        filtered = filter_response_headers(headers)

        assert filtered == {"Content-Type": "application/json"}

    def test_remove_cookies_false_preserves_set_cookie(self):
        """Should preserve Set-Cookie when remove_cookies=False."""
        headers = {
            "Content-Type": "application/json",
            "Set-Cookie": "session=abc123",
        }

        filtered = filter_response_headers(headers, remove_cookies=False)

        assert "Set-Cookie" in filtered
        assert filtered["Set-Cookie"] == "session=abc123"

    def test_remove_cookies_true_removes_set_cookie(self):
        """Should remove Set-Cookie when remove_cookies=True."""
        headers = {
            "Content-Type": "application/json",
            "Set-Cookie": "session=abc123",
        }

        filtered = filter_response_headers(headers, remove_cookies=True)

        assert "Set-Cookie" not in filtered
        assert filtered == {"Content-Type": "application/json"}

    def test_additional_volatile_headers(self):
        """Should remove additional volatile headers."""
        headers = {
            "Content-Type": "application/json",
            "X-Request-Id": "12345",
            "X-Trace-Id": "67890",
        }

        filtered = filter_response_headers(
            headers, additional_volatile=["X-Request-Id", "X-Trace-Id"]
        )

        assert filtered == {"Content-Type": "application/json"}

    def test_additional_volatile_case_insensitive(self):
        """Additional volatile headers should be case-insensitive."""
        headers = {
            "Content-Type": "application/json",
            "X-REQUEST-ID": "12345",
        }

        filtered = filter_response_headers(headers, additional_volatile=["x-request-id"])

        assert filtered == {"Content-Type": "application/json"}

    def test_empty_headers(self):
        """Should handle empty headers."""
        assert filter_response_headers({}) == {}

    def test_all_volatile_headers(self):
        """Should remove all headers if all are volatile."""
        headers = {
            "Date": "Mon, 01 Oct 2025 12:00:00 GMT",
            "Server": "nginx",
            "Connection": "close",
        }

        filtered = filter_response_headers(headers)

        assert filtered == {}

    def test_does_not_mutate_original(self):
        """Should not mutate the original headers dict."""
        headers = {
            "Content-Type": "application/json",
            "Date": "Mon, 01 Oct 2025 12:00:00 GMT",
        }
        original = headers.copy()

        filter_response_headers(headers)

        assert headers == original


class TestAddReplayHeaders:
    """Tests for add_replay_headers function."""

    def test_adds_replay_headers_for_replay(self):
        """Should add replay headers when is_replay=True."""
        headers = {"Content-Type": "application/json"}

        result = add_replay_headers(headers, "test-key-123")

        assert result["Idempotent-Replay"] == "true"
        assert result["Idempotency-Key"] == "test-key-123"
        assert result["Content-Type"] == "application/json"

    def test_adds_replay_headers_for_first_execution(self):
        """Should add replay=false for first execution."""
        headers = {"Content-Type": "application/json"}

        result = add_replay_headers(headers, "test-key-123", is_replay=False)

        assert result["Idempotent-Replay"] == "false"
        assert result["Idempotency-Key"] == "test-key-123"

    def test_preserves_existing_headers(self):
        """Should preserve all existing headers."""
        headers = {
            "Content-Type": "application/json",
            "Content-Length": "42",
            "X-Custom": "value",
        }

        result = add_replay_headers(headers, "key-456")

        assert "Content-Type" in result
        assert "Content-Length" in result
        assert "X-Custom" in result
        assert result["Content-Type"] == "application/json"

    def test_overwrites_existing_replay_headers(self):
        """Should overwrite existing replay headers."""
        headers = {
            "Content-Type": "application/json",
            "Idempotent-Replay": "false",
            "Idempotency-Key": "old-key",
        }

        result = add_replay_headers(headers, "new-key")

        assert result["Idempotent-Replay"] == "true"
        assert result["Idempotency-Key"] == "new-key"

    def test_does_not_mutate_original(self):
        """Should not mutate the original headers dict."""
        headers = {"Content-Type": "application/json"}
        original = headers.copy()

        add_replay_headers(headers, "test-key")

        assert headers == original

    def test_empty_headers(self):
        """Should work with empty headers."""
        result = add_replay_headers({}, "key-789")

        assert result["Idempotent-Replay"] == "true"
        assert result["Idempotency-Key"] == "key-789"


class TestCanonicalizeHeaders:
    """Tests for canonicalize_headers function."""

    def test_converts_to_lowercase(self):
        """Should convert all header names to lowercase."""
        headers = {
            "Content-Type": "application/json",
            "Content-Length": "42",
            "X-CUSTOM-HEADER": "value",
        }

        result = canonicalize_headers(headers)

        assert "content-type" in result
        assert "content-length" in result
        assert "x-custom-header" in result
        assert "Content-Type" not in result

    def test_strips_whitespace_from_values(self):
        """Should strip whitespace from header values."""
        headers = {
            "Content-Type": "  application/json  ",
            "X-Custom": "\tvalue\t",
        }

        result = canonicalize_headers(headers)

        assert result["content-type"] == "application/json"
        assert result["x-custom"] == "value"

    def test_filters_to_included_headers(self):
        """Should only include specified headers."""
        headers = {
            "Content-Type": "application/json",
            "Content-Length": "42",
            "User-Agent": "curl/7.68.0",
        }

        result = canonicalize_headers(headers, ["content-type", "content-length"])

        assert "content-type" in result
        assert "content-length" in result
        assert "user-agent" not in result

    def test_included_headers_case_insensitive(self):
        """Included headers should be case-insensitive."""
        headers = {
            "Content-Type": "application/json",
            "CONTENT-LENGTH": "42",
        }

        result = canonicalize_headers(headers, ["Content-Type", "Content-Length"])

        assert "content-type" in result
        assert "content-length" in result

    def test_empty_headers(self):
        """Should handle empty headers."""
        assert canonicalize_headers({}) == {}

    def test_no_included_headers_includes_all(self):
        """Should include all headers when included_headers=None."""
        headers = {
            "Content-Type": "application/json",
            "X-Custom": "value",
        }

        result = canonicalize_headers(headers, included_headers=None)

        assert len(result) == 2
        assert "content-type" in result
        assert "x-custom" in result

    def test_included_headers_not_present(self):
        """Should return empty when included headers not present."""
        headers = {"Content-Type": "application/json"}

        result = canonicalize_headers(headers, ["x-missing"])

        assert result == {}

    def test_does_not_mutate_original(self):
        """Should not mutate the original headers dict."""
        headers = {"Content-Type": "application/json"}
        original = headers.copy()

        canonicalize_headers(headers)

        assert headers == original


class TestGetHeaderValue:
    """Tests for get_header_value function."""

    def test_finds_header_exact_case(self):
        """Should find header with exact case match."""
        headers = {"Content-Type": "application/json"}

        value = get_header_value(headers, "Content-Type")

        assert value == "application/json"

    def test_finds_header_different_case(self):
        """Should find header with different case."""
        headers = {"Content-Type": "application/json"}

        value = get_header_value(headers, "content-type")

        assert value == "application/json"

    def test_finds_header_uppercase(self):
        """Should find header when both are uppercase."""
        headers = {"CONTENT-TYPE": "application/json"}

        value = get_header_value(headers, "content-type")

        assert value == "application/json"

    def test_returns_none_for_missing_header(self):
        """Should return None for missing header."""
        headers = {"Content-Type": "application/json"}

        value = get_header_value(headers, "X-Missing")

        assert value is None

    def test_returns_default_for_missing_header(self):
        """Should return default value for missing header."""
        headers = {"Content-Type": "application/json"}

        value = get_header_value(headers, "X-Missing", default="default-value")

        assert value == "default-value"

    def test_empty_headers(self):
        """Should handle empty headers."""
        value = get_header_value({}, "Content-Type", default="default")

        assert value == "default"

    def test_first_match_wins(self):
        """Should return first match when multiple case variants exist."""
        # Note: This shouldn't happen in practice, but testing behavior
        headers = {
            "Content-Type": "text/html",
            "content-type": "application/json",
        }

        value = get_header_value(headers, "CONTENT-TYPE")

        # Should return one of them (implementation dependent on dict order)
        assert value in ["text/html", "application/json"]


class TestMergeHeaders:
    """Tests for merge_headers function."""

    def test_merges_non_overlapping_headers(self):
        """Should merge headers with no overlap."""
        h1 = {"Content-Type": "application/json"}
        h2 = {"Content-Length": "42"}

        result = merge_headers(h1, h2)

        assert result["Content-Type"] == "application/json"
        assert result["Content-Length"] == "42"

    def test_later_overrides_earlier(self):
        """Later dicts should override earlier ones."""
        h1 = {"Content-Type": "text/html"}
        h2 = {"Content-Type": "application/json"}

        result = merge_headers(h1, h2)

        assert result["Content-Type"] == "application/json"

    def test_case_insensitive_override(self):
        """Should override headers with different case."""
        h1 = {"Content-Type": "text/html"}
        h2 = {"content-type": "application/json"}

        result = merge_headers(h1, h2)

        # Should have only one entry
        assert len(result) == 1
        # Case from last dict is preserved
        assert "content-type" in result
        assert result["content-type"] == "application/json"

    def test_preserves_last_case(self):
        """Should preserve case from last dictionary."""
        h1 = {"CONTENT-TYPE": "text/html"}
        h2 = {"Content-Type": "application/json"}

        result = merge_headers(h1, h2)

        assert "Content-Type" in result
        assert "CONTENT-TYPE" not in result

    def test_multiple_dicts(self):
        """Should merge multiple dictionaries."""
        h1 = {"A": "1"}
        h2 = {"B": "2"}
        h3 = {"C": "3"}

        result = merge_headers(h1, h2, h3)

        assert result == {"A": "1", "B": "2", "C": "3"}

    def test_empty_dicts(self):
        """Should handle empty dictionaries."""
        result = merge_headers({}, {}, {})

        assert result == {}

    def test_single_dict(self):
        """Should work with single dictionary."""
        h1 = {"Content-Type": "application/json"}

        result = merge_headers(h1)

        assert result == {"Content-Type": "application/json"}

    def test_no_dicts(self):
        """Should return empty dict when no arguments."""
        result = merge_headers()

        assert result == {}

    def test_does_not_mutate_originals(self):
        """Should not mutate original dictionaries."""
        h1 = {"Content-Type": "text/html"}
        h2 = {"Content-Length": "42"}
        original_h1 = h1.copy()
        original_h2 = h2.copy()

        merge_headers(h1, h2)

        assert h1 == original_h1
        assert h2 == original_h2


class TestVolatileHeadersConstant:
    """Tests for VOLATILE_HEADERS constant."""

    def test_contains_expected_headers(self):
        """Should contain all expected volatile headers."""
        expected = [
            "date",
            "server",
            "connection",
            "transfer-encoding",
            "keep-alive",
            "trailer",
            "upgrade",
        ]

        for header in expected:
            assert header in VOLATILE_HEADERS

    def test_all_lowercase(self):
        """All headers should be lowercase."""
        for header in VOLATILE_HEADERS:
            assert header == header.lower()
