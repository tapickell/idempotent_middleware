"""Request fingerprinting for idempotency.

This module implements request fingerprinting according to the specification in section 6.1.
The fingerprint is computed from canonical representations of request components to ensure
consistent identification of logically identical requests.
"""

import hashlib
import json
from urllib.parse import parse_qs, urlencode


def compute_fingerprint(
    method: str,
    path: str,
    query_string: str,
    headers: dict[str, str],
    body: bytes,
    included_headers: list[str] | None = None,
) -> str:
    """Compute a deterministic fingerprint for a request.

    The fingerprint is computed from canonical representations of the request components:
    1. Canonical path: lowercase, strip trailing / (except root)
    2. Sorted query params: parse, sort keys, re-encode
    3. Canonical headers: lowercase keys, filter to included set, sort, JSON
    4. Body SHA-256 digest
    5. Final: SHA-256 of concatenated components separated by newline

    Args:
        method: HTTP method (e.g., "POST", "PUT")
        path: URL path component
        query_string: Raw query string (without leading '?')
        headers: Request headers as key-value pairs
        body: Request body as bytes
        included_headers: List of header names to include in fingerprint.
                         Defaults to ["content-type", "content-length"]

    Returns:
        Hexadecimal SHA-256 hash string (64 characters)

    Examples:
        >>> compute_fingerprint(
        ...     method="POST",
        ...     path="/api/users",
        ...     query_string="",
        ...     headers={"Content-Type": "application/json"},
        ...     body=b'{"name": "Alice"}',
        ... )
        'a1b2c3d4...'  # SHA-256 hash
    """
    if included_headers is None:
        included_headers = ["content-type", "content-length"]

    # 1. Canonical method: uppercase
    canonical_method = method.upper()

    # 2. Canonical path: lowercase, strip trailing / (except root)
    canonical_path = path.lower() if path else "/"
    if canonical_path != "/" and canonical_path.endswith("/"):
        canonical_path = canonical_path.rstrip("/")

    # 3. Sorted query params
    canonical_query = _canonicalize_query_string(query_string)

    # 4. Canonical headers
    canonical_headers = _canonicalize_headers(headers, included_headers)

    # 5. Body digest
    body_digest = hashlib.sha256(body).hexdigest()

    # 6. Concatenate components with newline separator
    components = [
        canonical_method,
        canonical_path,
        canonical_query,
        canonical_headers,
        body_digest,
    ]
    fingerprint_input = "\n".join(components)

    # 7. Final SHA-256 hash
    return hashlib.sha256(fingerprint_input.encode("utf-8")).hexdigest()


def _canonicalize_query_string(query_string: str) -> str:
    """Canonicalize query string by parsing, sorting, and re-encoding.

    Args:
        query_string: Raw query string without leading '?'

    Returns:
        Canonicalized query string with sorted parameters
    """
    if not query_string or not query_string.strip():
        return ""

    # Parse query string into dict of lists
    parsed = parse_qs(query_string, keep_blank_values=True)

    # Sort by keys, then sort values within each key
    sorted_params: list[tuple[str, str]] = []
    for key in sorted(parsed.keys()):
        values = sorted(parsed[key])
        for value in values:
            sorted_params.append((key, value))

    # Re-encode with sorted parameters
    return urlencode(sorted_params, doseq=False)


def _canonicalize_headers(headers: dict[str, str], included_headers: list[str]) -> str:
    """Canonicalize headers by filtering, lowercasing keys, sorting, and JSON encoding.

    Args:
        headers: Request headers as key-value pairs
        included_headers: List of header names to include (case-insensitive)

    Returns:
        JSON string of canonical headers
    """
    # Lowercase the included_headers list for case-insensitive comparison
    included_lower = {name.lower() for name in included_headers}

    # Filter and lowercase header keys
    canonical: dict[str, str] = {}
    for key, value in headers.items():
        key_lower = key.lower()
        if key_lower in included_lower:
            canonical[key_lower] = value

    # Sort by keys and convert to JSON
    # Use sort_keys and separators for consistent output
    return json.dumps(canonical, sort_keys=True, separators=(",", ":"))
