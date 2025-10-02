"""Header filtering and manipulation utilities for idempotency middleware.

This module provides functions for:
- Filtering volatile headers from responses
- Adding replay-specific headers
- Canonicalizing headers for fingerprinting
"""

# Headers that should be removed from replayed responses
# These are volatile and may differ between the original request and replay
VOLATILE_HEADERS = {
    "date",
    "server",
    "connection",
    "transfer-encoding",
    "keep-alive",
    "trailer",
    "upgrade",
    "proxy-connection",
    "proxy-authenticate",
    "proxy-authorization",
}

# Optional headers that may be removed (configurable)
OPTIONAL_VOLATILE_HEADERS = {
    "set-cookie",
    "age",
    "expires",
    "etag",
    "last-modified",
}


def filter_response_headers(
    headers: dict[str, str],
    remove_cookies: bool = False,
    additional_volatile: list[str] | None = None,
) -> dict[str, str]:
    """Filter volatile headers from response headers.

    Args:
        headers: Original response headers
        remove_cookies: If True, remove Set-Cookie headers
        additional_volatile: Additional header names to remove (case-insensitive)

    Returns:
        Filtered headers dictionary

    Example:
        >>> headers = {
        ...     "Content-Type": "application/json",
        ...     "Date": "Mon, 01 Oct 2025 12:00:00 GMT",
        ...     "Server": "nginx/1.18.0"
        ... }
        >>> filter_response_headers(headers)
        {'Content-Type': 'application/json'}
    """
    # Build set of headers to remove (all lowercase)
    headers_to_remove = VOLATILE_HEADERS.copy()

    if remove_cookies:
        headers_to_remove.update(OPTIONAL_VOLATILE_HEADERS)

    if additional_volatile:
        headers_to_remove.update(h.lower() for h in additional_volatile)

    # Filter headers (case-insensitive comparison)
    filtered = {
        key: value for key, value in headers.items() if key.lower() not in headers_to_remove
    }

    return filtered


def add_replay_headers(
    headers: dict[str, str],
    idempotency_key: str,
    is_replay: bool = True,
) -> dict[str, str]:
    """Add idempotency-specific headers to response.

    Args:
        headers: Existing response headers
        idempotency_key: The idempotency key used for this request
        is_replay: Whether this is a replayed response (default True)

    Returns:
        Headers with replay metadata added

    Example:
        >>> headers = {"Content-Type": "application/json"}
        >>> add_replay_headers(headers, "abc-123")
        {
            'Content-Type': 'application/json',
            'Idempotent-Replay': 'true',
            'Idempotency-Key': 'abc-123'
        }
    """
    # Create new dict to avoid mutating original
    result = headers.copy()

    # Add replay indicator
    result["Idempotent-Replay"] = "true" if is_replay else "false"

    # Add the idempotency key (useful for debugging)
    result["Idempotency-Key"] = idempotency_key

    return result


def canonicalize_headers(
    headers: dict[str, str],
    included_headers: list[str] | None = None,
) -> dict[str, str]:
    """Canonicalize headers for fingerprinting.

    Normalizes headers by:
    1. Converting keys to lowercase
    2. Stripping whitespace from values
    3. Filtering to only included headers (if specified)
    4. Sorting by key

    Args:
        headers: Raw headers dictionary
        included_headers: If provided, only include these headers (case-insensitive).
                         If None, include all headers.

    Returns:
        Canonicalized headers suitable for fingerprinting

    Example:
        >>> headers = {
        ...     "Content-Type": "application/json  ",
        ...     "Content-Length": "42",
        ...     "User-Agent": "curl/7.68.0"
        ... }
        >>> canonicalize_headers(headers, ["content-type", "content-length"])
        {'content-length': '42', 'content-type': 'application/json'}
    """
    # Convert to lowercase and strip values
    normalized = {key.lower(): value.strip() for key, value in headers.items()}

    # Filter to included headers if specified
    if included_headers is not None:
        included_set = {h.lower() for h in included_headers}
        normalized = {key: value for key, value in normalized.items() if key in included_set}

    return normalized


def get_header_value(
    headers: dict[str, str],
    header_name: str,
    default: str | None = None,
) -> str | None:
    """Get header value with case-insensitive lookup.

    Args:
        headers: Headers dictionary
        header_name: Name of header to find (case-insensitive)
        default: Default value if header not found

    Returns:
        Header value or default

    Example:
        >>> headers = {"Content-Type": "application/json"}
        >>> get_header_value(headers, "content-type")
        'application/json'
        >>> get_header_value(headers, "missing", "default")
        'default'
    """
    header_name_lower = header_name.lower()

    for key, value in headers.items():
        if key.lower() == header_name_lower:
            return value

    return default


def merge_headers(*header_dicts: dict[str, str]) -> dict[str, str]:
    """Merge multiple header dictionaries with case-insensitive key handling.

    Later dictionaries override earlier ones. Keys from the last dict are used.

    Args:
        *header_dicts: Variable number of header dictionaries to merge

    Returns:
        Merged headers dictionary

    Example:
        >>> h1 = {"Content-Type": "text/html"}
        >>> h2 = {"content-type": "application/json", "X-Custom": "value"}
        >>> merge_headers(h1, h2)
        {'content-type': 'application/json', 'X-Custom': 'value'}
    """
    # Track canonical case for each header (use last seen)
    canonical_keys: dict[str, str] = {}
    result: dict[str, str] = {}

    for headers in header_dicts:
        for key, value in headers.items():
            key_lower = key.lower()

            # Remove old key if exists with different case
            if key_lower in canonical_keys:
                old_key = canonical_keys[key_lower]
                if old_key in result:
                    del result[old_key]

            # Store new value with new case
            canonical_keys[key_lower] = key
            result[key] = value

    return result
