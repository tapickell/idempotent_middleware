"""Response replay logic for idempotency middleware.

This module provides utilities to reconstruct HTTP responses from stored
idempotency records. The replay process includes:
1. Decoding base64-encoded response bodies
2. Filtering volatile headers (Date, Server, etc.)
3. Adding replay-specific headers (Idempotent-Replay, Idempotency-Key)

The replayed response should be functionally identical to the original
response, allowing clients to receive consistent results for duplicate requests.

Examples:
    Basic replay::

        from idempotent_middleware.core.replay import replay_response
        from idempotent_middleware.models import IdempotencyRecord, StoredResponse

        record = IdempotencyRecord(
            key="payment-123",
            fingerprint="abc123",
            state=RequestState.COMPLETED,
            response=StoredResponse(
                status=200,
                headers={"content-type": "application/json"},
                body_b64="eyJyZXN1bHQiOiAic3VjY2VzcyJ9",
            ),
            ...
        )

        response = replay_response(record, "payment-123")
        # response.status == 200
        # response.headers["Idempotent-Replay"] == "true"
        # response.headers["Idempotency-Key"] == "payment-123"
"""

import base64

from idempotent_middleware.models import IdempotencyRecord
from idempotent_middleware.utils.headers import add_replay_headers, filter_response_headers


class ReplayedResponse:
    """Represents a replayed HTTP response.

    This is a simple data class that holds the reconstructed response
    from a stored idempotency record.

    Attributes:
        status: HTTP status code (e.g., 200, 404, 500)
        headers: Response headers as key-value pairs
        body: Response body as bytes
    """

    def __init__(self, status: int, headers: dict[str, str], body: bytes) -> None:
        """Initialize a replayed response.

        Args:
            status: HTTP status code
            headers: Response headers
            body: Response body as bytes
        """
        self.status = status
        self.headers = headers
        self.body = body


def replay_response(record: IdempotencyRecord, key: str) -> ReplayedResponse:
    """Reconstruct an HTTP response from a stored idempotency record.

    This function takes a completed idempotency record and reconstructs
    the HTTP response that was originally returned. The process includes:

    1. Decode the base64-encoded body from the stored response
    2. Filter out volatile headers (Date, Server, Connection, etc.)
    3. Add replay-specific headers (Idempotent-Replay: true, Idempotency-Key)

    Args:
        record: The idempotency record containing the stored response
        key: The idempotency key for this request

    Returns:
        ReplayedResponse object with status, headers, and body

    Raises:
        ValueError: If the record has no stored response
        ValueError: If the stored response body is not valid base64

    Examples:
        >>> from idempotent_middleware.models import (
        ...     IdempotencyRecord,
        ...     StoredResponse,
        ...     RequestState
        ... )
        >>> from datetime import datetime
        >>>
        >>> record = IdempotencyRecord(
        ...     key="payment-123",
        ...     fingerprint="abc123",
        ...     state=RequestState.COMPLETED,
        ...     response=StoredResponse(
        ...         status=200,
        ...         headers={
        ...             "content-type": "application/json",
        ...             "date": "Mon, 01 Jan 2024 00:00:00 GMT",  # Will be filtered
        ...         },
        ...         body_b64="eyJyZXN1bHQiOiAic3VjY2VzcyJ9",
        ...     ),
        ...     created_at=datetime.utcnow(),
        ...     expires_at=datetime.utcnow(),
        ... )
        >>>
        >>> response = replay_response(record, "payment-123")
        >>> response.status
        200
        >>> response.headers["Idempotent-Replay"]
        'true'
        >>> response.headers["Idempotency-Key"]
        'payment-123'
        >>> "date" in response.headers  # Volatile headers filtered out
        False
    """
    if record.response is None:
        raise ValueError(f"Record {record.key} has no stored response")

    stored = record.response

    # Decode base64-encoded body
    try:
        body = base64.b64decode(stored.body_b64)
    except Exception as e:
        raise ValueError(f"Failed to decode response body: {e}") from e

    # Filter volatile headers from the stored response
    headers = filter_response_headers(stored.headers)

    # Add replay-specific headers
    headers = add_replay_headers(headers, key, is_replay=True)

    return ReplayedResponse(
        status=stored.status,
        headers=headers,
        body=body,
    )
