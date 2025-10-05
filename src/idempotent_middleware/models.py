"""Core type definitions and models for idempotency middleware.

This module provides the fundamental data structures used throughout the idempotency
middleware system, including request states, stored responses, idempotency records,
and lease management results.

Examples:
    Creating an idempotency record::

        from datetime import UTC, datetime, timedelta
        from idempotent_middleware.models import (
            IdempotencyRecord,
            RequestState,
            StoredResponse,
        )

        record = IdempotencyRecord(
            key="idempotency-key-123",
            fingerprint="a" * 64,
            state=RequestState.NEW,
            response=None,
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )

    Storing a completed response::

        response = StoredResponse(
            status=200,
            headers={"content-type": "application/json"},
            body_b64="eyJyZXN1bHQiOiAic3VjY2VzcyJ9",
        )

        record.state = RequestState.COMPLETED
        record.response = response
        record.execution_time_ms = 150
"""

import base64
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class RequestState(str, Enum):
    """Represents the current state of an idempotent request.

    Attributes:
        NEW: Request has been received but not yet started processing.
        RUNNING: Request is currently being processed.
        COMPLETED: Request processing finished successfully.
        FAILED: Request processing encountered an error.
    """

    NEW = "NEW"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class StoredResponse(BaseModel):
    """A cached HTTP response that can be returned for duplicate requests.

    The response body is base64-encoded to safely handle binary content
    and ensure consistent serialization across different storage backends.

    Attributes:
        status: HTTP status code (e.g., 200, 201, 400).
        headers: HTTP response headers as key-value pairs.
        body_b64: Base64-encoded response body.

    Examples:
        Creating a stored response::

            import base64

            body = b'{"result": "success"}'
            response = StoredResponse(
                status=200,
                headers={"content-type": "application/json"},
                body_b64=base64.b64encode(body).decode("ascii"),
            )

        Decoding the response body::

            body_bytes = base64.b64decode(response.body_b64)
            body_text = body_bytes.decode("utf-8")
    """

    status: int = Field(
        ...,
        description="HTTP status code",
        ge=100,
        le=599,
        examples=[200, 201, 400, 500],
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="HTTP response headers",
        examples=[{"content-type": "application/json", "x-request-id": "abc123"}],
    )
    body_b64: str = Field(
        ...,
        description="Base64-encoded response body",
        examples=["eyJyZXN1bHQiOiAic3VjY2VzcyJ9"],
    )

    @field_validator("body_b64")
    @classmethod
    def validate_base64(cls, v: str) -> str:
        """Validate that the body is properly base64-encoded.

        Args:
            v: The base64-encoded string to validate.

        Returns:
            The validated base64 string.

        Raises:
            ValueError: If the string is not valid base64.
        """
        try:
            base64.b64decode(v)
        except Exception as e:
            raise ValueError(f"Invalid base64 encoding: {e}") from e
        return v

    def get_body_bytes(self) -> bytes:
        """Decode and return the response body as bytes.

        Returns:
            The decoded response body.

        Examples:
            >>> response = StoredResponse(status=200, headers={}, body_b64="SGVsbG8=")
            >>> response.get_body_bytes()
            b'Hello'
        """
        return base64.b64decode(self.body_b64)


class IdempotencyRecord(BaseModel):
    """Complete record of an idempotent request and its lifecycle.

    This model tracks all information about a request identified by an
    idempotency key, including its current state, cached response (if any),
    timing information, and lease ownership.

    Attributes:
        key: The idempotency key provided by the client.
        fingerprint: SHA-256 hash of request fingerprint (64 hex chars).
        state: Current processing state of the request.
        response: Cached response (if COMPLETED or FAILED), None otherwise.
        created_at: When this record was first created.
        expires_at: When this record should be deleted from storage.
        execution_time_ms: Time taken to process the request in milliseconds.
        lease_token: UUID of the process currently holding the execution lease.
        trace_id: Distributed tracing ID for correlation across systems.

    Examples:
        Creating a new record::

            from datetime import UTC, datetime, timedelta
            import uuid

            record = IdempotencyRecord(
                key="user-payment-123",
                fingerprint="a" * 64,
                state=RequestState.NEW,
                response=None,
                created_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(hours=24),
                lease_token=str(uuid.uuid4()),
                trace_id="trace-abc123",
            )

        Marking a record as completed::

            record.state = RequestState.COMPLETED
            record.response = StoredResponse(
                status=200,
                headers={"content-type": "application/json"},
                body_b64="eyJyZXN1bHQiOiAic3VjY2VzcyJ9",
            )
            record.execution_time_ms = 250
    """

    key: str = Field(
        ...,
        description="Idempotency key provided by the client",
        min_length=1,
        max_length=255,
        examples=["payment-user123-20231215", "order-create-abc123"],
    )
    fingerprint: str = Field(
        ...,
        description="SHA-256 hash of request fingerprint (64 hex characters)",
        pattern=r"^[a-f0-9]{64}$",
        examples=["a" * 64, "b" * 64],
    )
    state: RequestState = Field(
        ...,
        description="Current processing state of the request",
        examples=[RequestState.NEW, RequestState.RUNNING, RequestState.COMPLETED],
    )
    response: StoredResponse | None = Field(
        default=None,
        description="Cached response (set when COMPLETED or FAILED)",
    )
    created_at: datetime = Field(
        ...,
        description="Timestamp when the record was created",
        examples=["2023-12-15T10:30:00Z"],
    )
    expires_at: datetime = Field(
        ...,
        description="Timestamp when the record should be deleted",
        examples=["2023-12-16T10:30:00Z"],
    )
    execution_time_ms: int | None = Field(
        default=None,
        description="Request execution time in milliseconds",
        ge=0,
        examples=[150, 500, 2000],
    )
    lease_token: str | None = Field(
        default=None,
        description="UUID of the process holding the execution lease",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    trace_id: str | None = Field(
        default=None,
        description="Distributed tracing ID for request correlation",
        examples=["trace-abc123", "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"],
    )

    @field_validator("fingerprint")
    @classmethod
    def validate_fingerprint(cls, v: str) -> str:
        """Validate that the fingerprint is a valid SHA-256 hex string.

        Args:
            v: The fingerprint string to validate.

        Returns:
            The validated fingerprint.

        Raises:
            ValueError: If the fingerprint is not exactly 64 hex characters.
        """
        if len(v) != 64:
            raise ValueError(f"Fingerprint must be exactly 64 characters, got {len(v)}")
        if not all(c in "0123456789abcdef" for c in v):
            raise ValueError("Fingerprint must contain only lowercase hex characters")
        return v

    @field_validator("lease_token")
    @classmethod
    def validate_lease_token(cls, v: str | None) -> str | None:
        """Validate that the lease token is a valid UUID if present.

        Args:
            v: The lease token string to validate.

        Returns:
            The validated lease token.

        Raises:
            ValueError: If the lease token is not a valid UUID.
        """
        if v is not None:
            try:
                UUID(v)
            except ValueError as e:
                raise ValueError(f"Invalid UUID format for lease_token: {e}") from e
        return v

    @field_validator("expires_at")
    @classmethod
    def validate_expires_after_created(cls, v: datetime, info: Any) -> datetime:
        """Validate that expires_at is after created_at.

        Args:
            v: The expires_at datetime to validate.
            info: Validation context containing other field values.

        Returns:
            The validated expires_at datetime.

        Raises:
            ValueError: If expires_at is not after created_at.
        """
        if "created_at" in info.data and v <= info.data["created_at"]:
            raise ValueError("expires_at must be after created_at")
        return v


class LeaseResult(BaseModel):
    """Result of attempting to acquire an execution lease for an idempotency key.

    When a request attempts to acquire a lease, it either succeeds (becomes the
    lease holder) or fails (another process holds the lease or a response exists).

    Attributes:
        success: Whether the lease was successfully acquired.
        lease_token: UUID token if lease was acquired, None otherwise.
        existing_record: The current record if lease failed, None if succeeded.

    Examples:
        Successful lease acquisition::

            result = LeaseResult(
                success=True,
                lease_token="550e8400-e29b-41d4-a716-446655440000",
                existing_record=None,
            )

        Failed lease acquisition (request already running)::

            result = LeaseResult(
                success=False,
                lease_token=None,
                existing_record=IdempotencyRecord(
                    key="payment-123",
                    fingerprint="a" * 64,
                    state=RequestState.RUNNING,
                    response=None,
                    created_at=datetime.now(UTC),
                    expires_at=datetime.now(UTC) + timedelta(hours=24),
                    lease_token="other-process-uuid",
                ),
            )

        Failed lease acquisition (cached response available)::

            result = LeaseResult(
                success=False,
                lease_token=None,
                existing_record=IdempotencyRecord(
                    key="payment-123",
                    fingerprint="a" * 64,
                    state=RequestState.COMPLETED,
                    response=StoredResponse(
                        status=200,
                        headers={"content-type": "application/json"},
                        body_b64="eyJyZXN1bHQiOiAic3VjY2VzcyJ9",
                    ),
                    created_at=datetime.now(UTC),
                    expires_at=datetime.now(UTC) + timedelta(hours=24),
                ),
            )
    """

    success: bool = Field(
        ...,
        description="Whether the lease was successfully acquired",
        examples=[True, False],
    )
    lease_token: str | None = Field(
        default=None,
        description="UUID token if lease acquired, None otherwise",
        examples=["550e8400-e29b-41d4-a716-446655440000", None],
    )
    existing_record: IdempotencyRecord | None = Field(
        default=None,
        description="Current record if lease failed, None if succeeded",
    )

    @field_validator("lease_token")
    @classmethod
    def validate_lease_token_with_success(cls, v: str | None, info: Any) -> str | None:
        """Validate that lease_token is present if and only if success is True.

        Args:
            v: The lease token to validate.
            info: Validation context containing other field values.

        Returns:
            The validated lease token.

        Raises:
            ValueError: If success/lease_token consistency is violated.
        """
        if "success" in info.data:
            success = info.data["success"]
            if success and v is None:
                raise ValueError("lease_token must be provided when success is True")
            if not success and v is not None:
                raise ValueError("lease_token must be None when success is False")
        return v

    @field_validator("existing_record")
    @classmethod
    def validate_existing_record_with_success(
        cls, v: IdempotencyRecord | None, info: Any
    ) -> IdempotencyRecord | None:
        """Validate that existing_record is present if and only if success is False.

        Args:
            v: The existing record to validate.
            info: Validation context containing other field values.

        Returns:
            The validated existing record.

        Raises:
            ValueError: If success/existing_record consistency is violated.
        """
        if "success" in info.data:
            success = info.data["success"]
            if success and v is not None:
                raise ValueError("existing_record must be None when success is True")
            if not success and v is None:
                raise ValueError("existing_record must be provided when success is False")
        return v
