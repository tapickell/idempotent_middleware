"""Unit tests for response replay logic."""

import base64
from datetime import UTC, datetime, timedelta

import pytest

from idempotent_middleware.core.replay import ReplayedResponse, replay_response
from idempotent_middleware.models import (
    IdempotencyRecord,
    RequestState,
    StoredResponse,
)


def test_replay_response_basic() -> None:
    """Test basic response replay."""
    body_text = '{"result": "success"}'
    body_b64 = base64.b64encode(body_text.encode("utf-8")).decode("utf-8")

    record = IdempotencyRecord(
        key="test-key",
        fingerprint="a" * 64,
        state=RequestState.COMPLETED,
        response=StoredResponse(
            status=200,
            headers={"content-type": "application/json"},
            body_b64=body_b64,
        ),
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    response = replay_response(record, "test-key")

    assert isinstance(response, ReplayedResponse)
    assert response.status == 200
    assert response.body == body_text.encode("utf-8")
    assert "content-type" in response.headers
    assert response.headers["Idempotent-Replay"] == "true"
    assert response.headers["Idempotency-Key"] == "test-key"


def test_replay_response_filters_volatile_headers() -> None:
    """Test that volatile headers are filtered out."""
    record = IdempotencyRecord(
        key="test-key",
        fingerprint="b" * 64,
        state=RequestState.COMPLETED,
        response=StoredResponse(
            status=200,
            headers={
                "content-type": "application/json",
                "date": "Mon, 01 Jan 2024 00:00:00 GMT",  # Should be filtered
                "server": "nginx",  # Should be filtered
                "connection": "keep-alive",  # Should be filtered
            },
            body_b64=base64.b64encode(b"test").decode("utf-8"),
        ),
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    response = replay_response(record, "test-key")

    assert "content-type" in response.headers
    assert "date" not in response.headers
    assert "server" not in response.headers
    assert "connection" not in response.headers


def test_replay_response_no_stored_response() -> None:
    """Test replay fails when record has no stored response."""
    record = IdempotencyRecord(
        key="test-key",
        fingerprint="c" * 64,
        state=RequestState.RUNNING,
        response=None,  # No stored response
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    with pytest.raises(ValueError, match="has no stored response"):
        replay_response(record, "test-key")


def test_replay_response_invalid_base64() -> None:
    """Test that StoredResponse validates base64 on construction."""
    from pydantic import ValidationError

    # StoredResponse should reject invalid base64 during construction
    with pytest.raises(ValidationError, match="Invalid base64"):
        StoredResponse(
            status=200,
            headers={},
            body_b64="not-valid-base64!!!",  # Invalid base64
        )


def test_replay_response_empty_body() -> None:
    """Test replay works with empty body."""
    record = IdempotencyRecord(
        key="test-key",
        fingerprint="e" * 64,
        state=RequestState.COMPLETED,
        response=StoredResponse(
            status=204,
            headers={},
            body_b64=base64.b64encode(b"").decode("utf-8"),
        ),
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    response = replay_response(record, "test-key")

    assert response.status == 204
    assert response.body == b""


def test_replay_response_error_status() -> None:
    """Test replay works for error responses."""
    error_body = '{"error": "Invalid input"}'
    body_b64 = base64.b64encode(error_body.encode("utf-8")).decode("utf-8")

    record = IdempotencyRecord(
        key="test-key",
        fingerprint="f" * 64,
        state=RequestState.FAILED,
        response=StoredResponse(
            status=400,
            headers={"content-type": "application/json"},
            body_b64=body_b64,
        ),
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    response = replay_response(record, "test-key")

    assert response.status == 400
    assert response.body == error_body.encode("utf-8")
