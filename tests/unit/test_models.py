"""Unit tests for core models and type definitions.

This module tests:
- RequestState enum values and behavior
- StoredResponse model validation and serialization
- IdempotencyRecord model validation and serialization
- LeaseResult model validation and constraints
"""

import base64
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from idempotent_middleware.models import (
    IdempotencyRecord,
    LeaseResult,
    RequestState,
    StoredResponse,
)


class TestRequestState:
    """Tests for RequestState enum."""

    def test_enum_values(self) -> None:
        """Test that enum has correct values."""
        assert RequestState.NEW.value == "NEW"
        assert RequestState.RUNNING.value == "RUNNING"
        assert RequestState.COMPLETED.value == "COMPLETED"
        assert RequestState.FAILED.value == "FAILED"

    def test_enum_members(self) -> None:
        """Test that enum has exactly four members."""
        assert len(RequestState) == 4
        assert set(RequestState) == {
            RequestState.NEW,
            RequestState.RUNNING,
            RequestState.COMPLETED,
            RequestState.FAILED,
        }

    def test_enum_string_comparison(self) -> None:
        """Test that enum values can be compared with strings."""
        assert RequestState.NEW == "NEW"
        assert RequestState.RUNNING == "RUNNING"
        assert RequestState.COMPLETED == "COMPLETED"
        assert RequestState.FAILED == "FAILED"

    def test_enum_can_be_created_from_string(self) -> None:
        """Test that enum can be instantiated from string values."""
        assert RequestState("NEW") == RequestState.NEW
        assert RequestState("RUNNING") == RequestState.RUNNING
        assert RequestState("COMPLETED") == RequestState.COMPLETED
        assert RequestState("FAILED") == RequestState.FAILED

    def test_enum_invalid_value_raises_error(self) -> None:
        """Test that creating enum with invalid value raises error."""
        with pytest.raises(ValueError):
            RequestState("INVALID")


class TestStoredResponse:
    """Tests for StoredResponse model."""

    def test_instantiation_with_valid_data(self) -> None:
        """Test creating a StoredResponse with valid data."""
        body = b'{"result": "success"}'
        body_b64 = base64.b64encode(body).decode("ascii")

        response = StoredResponse(
            status=200,
            headers={"content-type": "application/json"},
            body_b64=body_b64,
        )

        assert response.status == 200
        assert response.headers == {"content-type": "application/json"}
        assert response.body_b64 == body_b64

    def test_instantiation_with_empty_headers(self) -> None:
        """Test creating a StoredResponse with no headers."""
        body_b64 = base64.b64encode(b"test").decode("ascii")
        response = StoredResponse(status=200, body_b64=body_b64)

        assert response.status == 200
        assert response.headers == {}
        assert response.body_b64 == body_b64

    def test_instantiation_with_explicit_empty_headers(self) -> None:
        """Test creating a StoredResponse with explicit empty headers dict."""
        body_b64 = base64.b64encode(b"test").decode("ascii")
        response = StoredResponse(status=200, headers={}, body_b64=body_b64)

        assert response.headers == {}

    def test_status_code_validation_min(self) -> None:
        """Test that status code must be >= 100."""
        body_b64 = base64.b64encode(b"test").decode("ascii")

        with pytest.raises(ValidationError) as exc_info:
            StoredResponse(status=99, body_b64=body_b64)

        errors = exc_info.value.errors()
        assert any("status" in str(e["loc"]) for e in errors)

    def test_status_code_validation_max(self) -> None:
        """Test that status code must be <= 599."""
        body_b64 = base64.b64encode(b"test").decode("ascii")

        with pytest.raises(ValidationError) as exc_info:
            StoredResponse(status=600, body_b64=body_b64)

        errors = exc_info.value.errors()
        assert any("status" in str(e["loc"]) for e in errors)

    def test_valid_status_codes(self) -> None:
        """Test that common status codes are accepted."""
        body_b64 = base64.b64encode(b"test").decode("ascii")

        for status in [100, 200, 201, 400, 404, 500, 503, 599]:
            response = StoredResponse(status=status, body_b64=body_b64)
            assert response.status == status

    def test_base64_validation_valid(self) -> None:
        """Test that valid base64 strings are accepted."""
        valid_b64_strings = [
            base64.b64encode(b"hello").decode("ascii"),
            base64.b64encode(b"").decode("ascii"),
            base64.b64encode(b'{"json": "data"}').decode("ascii"),
            base64.b64encode(b"\x00\x01\x02\x03").decode("ascii"),
        ]

        for body_b64 in valid_b64_strings:
            response = StoredResponse(status=200, body_b64=body_b64)
            assert response.body_b64 == body_b64

    def test_base64_validation_invalid(self) -> None:
        """Test that invalid base64 strings are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            StoredResponse(status=200, body_b64="not valid base64!!!")

        errors = exc_info.value.errors()
        assert any("body_b64" in str(e["loc"]) for e in errors)

    def test_get_body_bytes(self) -> None:
        """Test decoding the base64 body to bytes."""
        original_body = b'{"result": "success"}'
        body_b64 = base64.b64encode(original_body).decode("ascii")

        response = StoredResponse(status=200, body_b64=body_b64)
        decoded_body = response.get_body_bytes()

        assert decoded_body == original_body

    def test_get_body_bytes_empty(self) -> None:
        """Test decoding an empty body."""
        body_b64 = base64.b64encode(b"").decode("ascii")
        response = StoredResponse(status=204, body_b64=body_b64)

        assert response.get_body_bytes() == b""

    def test_model_dump(self) -> None:
        """Test serializing model to dictionary."""
        body_b64 = base64.b64encode(b"test").decode("ascii")
        response = StoredResponse(
            status=200,
            headers={"x-custom": "value"},
            body_b64=body_b64,
        )

        data = response.model_dump()

        assert data == {
            "status": 200,
            "headers": {"x-custom": "value"},
            "body_b64": body_b64,
        }

    def test_model_dump_json(self) -> None:
        """Test serializing model to JSON string."""
        body_b64 = base64.b64encode(b"test").decode("ascii")
        response = StoredResponse(
            status=200,
            headers={"x-custom": "value"},
            body_b64=body_b64,
        )

        json_str = response.model_dump_json()
        data = json.loads(json_str)

        assert data == {
            "status": 200,
            "headers": {"x-custom": "value"},
            "body_b64": body_b64,
        }

    def test_model_validate(self) -> None:
        """Test deserializing model from dictionary."""
        body_b64 = base64.b64encode(b"test").decode("ascii")
        data = {
            "status": 200,
            "headers": {"x-custom": "value"},
            "body_b64": body_b64,
        }

        response = StoredResponse.model_validate(data)

        assert response.status == 200
        assert response.headers == {"x-custom": "value"}
        assert response.body_b64 == body_b64

    def test_model_validate_json(self) -> None:
        """Test deserializing model from JSON string."""
        body_b64 = base64.b64encode(b"test").decode("ascii")
        json_str = json.dumps(
            {
                "status": 200,
                "headers": {"x-custom": "value"},
                "body_b64": body_b64,
            }
        )

        response = StoredResponse.model_validate_json(json_str)

        assert response.status == 200
        assert response.headers == {"x-custom": "value"}
        assert response.body_b64 == body_b64


class TestIdempotencyRecord:
    """Tests for IdempotencyRecord model."""

    def test_instantiation_with_required_fields(self) -> None:
        """Test creating an IdempotencyRecord with only required fields."""
        created = datetime.now(UTC)
        expires = created + timedelta(hours=24)

        record = IdempotencyRecord(
            key="test-key",
            fingerprint="a" * 64,
            state=RequestState.NEW,
            created_at=created,
            expires_at=expires,
        )

        assert record.key == "test-key"
        assert record.fingerprint == "a" * 64
        assert record.state == RequestState.NEW
        assert record.response is None
        assert record.created_at == created
        assert record.expires_at == expires
        assert record.execution_time_ms is None
        assert record.lease_token is None
        assert record.trace_id is None

    def test_instantiation_with_all_fields(self) -> None:
        """Test creating an IdempotencyRecord with all fields."""
        created = datetime.now(UTC)
        expires = created + timedelta(hours=24)
        lease_token = str(uuid4())
        response = StoredResponse(
            status=200,
            body_b64=base64.b64encode(b"test").decode("ascii"),
        )

        record = IdempotencyRecord(
            key="test-key",
            fingerprint="b" * 64,
            state=RequestState.COMPLETED,
            response=response,
            created_at=created,
            expires_at=expires,
            execution_time_ms=150,
            lease_token=lease_token,
            trace_id="trace-123",
        )

        assert record.key == "test-key"
        assert record.fingerprint == "b" * 64
        assert record.state == RequestState.COMPLETED
        assert record.response == response
        assert record.created_at == created
        assert record.expires_at == expires
        assert record.execution_time_ms == 150
        assert record.lease_token == lease_token
        assert record.trace_id == "trace-123"

    def test_key_validation_empty(self) -> None:
        """Test that empty key is rejected."""
        created = datetime.now(UTC)
        expires = created + timedelta(hours=24)

        with pytest.raises(ValidationError) as exc_info:
            IdempotencyRecord(
                key="",
                fingerprint="a" * 64,
                state=RequestState.NEW,
                created_at=created,
                expires_at=expires,
            )

        errors = exc_info.value.errors()
        assert any("key" in str(e["loc"]) for e in errors)

    def test_key_validation_too_long(self) -> None:
        """Test that key longer than 255 characters is rejected."""
        created = datetime.now(UTC)
        expires = created + timedelta(hours=24)

        with pytest.raises(ValidationError) as exc_info:
            IdempotencyRecord(
                key="x" * 256,
                fingerprint="a" * 64,
                state=RequestState.NEW,
                created_at=created,
                expires_at=expires,
            )

        errors = exc_info.value.errors()
        assert any("key" in str(e["loc"]) for e in errors)

    def test_fingerprint_validation_correct_length(self) -> None:
        """Test that fingerprint must be exactly 64 characters."""
        created = datetime.now(UTC)
        expires = created + timedelta(hours=24)

        # Too short
        with pytest.raises(ValidationError):
            IdempotencyRecord(
                key="test",
                fingerprint="a" * 63,
                state=RequestState.NEW,
                created_at=created,
                expires_at=expires,
            )

        # Too long
        with pytest.raises(ValidationError):
            IdempotencyRecord(
                key="test",
                fingerprint="a" * 65,
                state=RequestState.NEW,
                created_at=created,
                expires_at=expires,
            )

    def test_fingerprint_validation_hex_only(self) -> None:
        """Test that fingerprint must contain only lowercase hex characters."""
        created = datetime.now(UTC)
        expires = created + timedelta(hours=24)

        # Uppercase hex
        with pytest.raises(ValidationError):
            IdempotencyRecord(
                key="test",
                fingerprint="A" * 64,
                state=RequestState.NEW,
                created_at=created,
                expires_at=expires,
            )

        # Non-hex characters
        with pytest.raises(ValidationError):
            IdempotencyRecord(
                key="test",
                fingerprint="g" * 64,
                state=RequestState.NEW,
                created_at=created,
                expires_at=expires,
            )

    def test_fingerprint_validation_valid_hex(self) -> None:
        """Test that valid hex fingerprints are accepted."""
        created = datetime.now(UTC)
        expires = created + timedelta(hours=24)

        valid_fingerprints = [
            "a" * 64,
            "0" * 64,
            "f" * 64,
            "0123456789abcdef" * 4,
        ]

        for fingerprint in valid_fingerprints:
            record = IdempotencyRecord(
                key="test",
                fingerprint=fingerprint,
                state=RequestState.NEW,
                created_at=created,
                expires_at=expires,
            )
            assert record.fingerprint == fingerprint

    def test_lease_token_validation_valid_uuid(self) -> None:
        """Test that valid UUIDs are accepted as lease tokens."""
        created = datetime.now(UTC)
        expires = created + timedelta(hours=24)

        valid_uuids = [
            str(uuid4()),
            "550e8400-e29b-41d4-a716-446655440000",
            "12345678-1234-5678-1234-567812345678",
        ]

        for uuid_str in valid_uuids:
            record = IdempotencyRecord(
                key="test",
                fingerprint="a" * 64,
                state=RequestState.RUNNING,
                created_at=created,
                expires_at=expires,
                lease_token=uuid_str,
            )
            assert record.lease_token == uuid_str

    def test_lease_token_validation_invalid_uuid(self) -> None:
        """Test that invalid UUIDs are rejected as lease tokens."""
        created = datetime.now(UTC)
        expires = created + timedelta(hours=24)

        invalid_uuids = [
            "not-a-uuid",
            "12345678-1234-5678-1234",
            "12345678-1234-5678-1234-56781234567890",
            "",
        ]

        for invalid_uuid in invalid_uuids:
            with pytest.raises(ValidationError) as exc_info:
                IdempotencyRecord(
                    key="test",
                    fingerprint="a" * 64,
                    state=RequestState.RUNNING,
                    created_at=created,
                    expires_at=expires,
                    lease_token=invalid_uuid,
                )

            errors = exc_info.value.errors()
            assert any("lease_token" in str(e["loc"]) for e in errors)

    def test_expires_at_validation_after_created_at(self) -> None:
        """Test that expires_at must be after created_at."""
        created = datetime.now(UTC)

        # expires_at before created_at
        with pytest.raises(ValidationError) as exc_info:
            IdempotencyRecord(
                key="test",
                fingerprint="a" * 64,
                state=RequestState.NEW,
                created_at=created,
                expires_at=created - timedelta(hours=1),
            )

        errors = exc_info.value.errors()
        assert any("expires_at" in str(e["loc"]) for e in errors)

    def test_expires_at_validation_same_as_created_at(self) -> None:
        """Test that expires_at cannot equal created_at."""
        created = datetime.now(UTC)

        with pytest.raises(ValidationError) as exc_info:
            IdempotencyRecord(
                key="test",
                fingerprint="a" * 64,
                state=RequestState.NEW,
                created_at=created,
                expires_at=created,
            )

        errors = exc_info.value.errors()
        assert any("expires_at" in str(e["loc"]) for e in errors)

    def test_execution_time_ms_validation_non_negative(self) -> None:
        """Test that execution_time_ms must be non-negative."""
        created = datetime.now(UTC)
        expires = created + timedelta(hours=24)

        with pytest.raises(ValidationError) as exc_info:
            IdempotencyRecord(
                key="test",
                fingerprint="a" * 64,
                state=RequestState.COMPLETED,
                created_at=created,
                expires_at=expires,
                execution_time_ms=-1,
            )

        errors = exc_info.value.errors()
        assert any("execution_time_ms" in str(e["loc"]) for e in errors)

    def test_execution_time_ms_validation_zero_allowed(self) -> None:
        """Test that execution_time_ms can be zero."""
        created = datetime.now(UTC)
        expires = created + timedelta(hours=24)

        record = IdempotencyRecord(
            key="test",
            fingerprint="a" * 64,
            state=RequestState.COMPLETED,
            created_at=created,
            expires_at=expires,
            execution_time_ms=0,
        )

        assert record.execution_time_ms == 0

    def test_model_dump(self) -> None:
        """Test serializing model to dictionary."""
        created = datetime.now(UTC)
        expires = created + timedelta(hours=24)
        response = StoredResponse(
            status=200,
            body_b64=base64.b64encode(b"test").decode("ascii"),
        )

        record = IdempotencyRecord(
            key="test-key",
            fingerprint="a" * 64,
            state=RequestState.COMPLETED,
            response=response,
            created_at=created,
            expires_at=expires,
            execution_time_ms=100,
            trace_id="trace-123",
        )

        data = record.model_dump()

        assert data["key"] == "test-key"
        assert data["fingerprint"] == "a" * 64
        assert data["state"] == "COMPLETED"
        assert data["response"]["status"] == 200
        assert data["created_at"] == created
        assert data["expires_at"] == expires
        assert data["execution_time_ms"] == 100
        assert data["trace_id"] == "trace-123"

    def test_model_dump_json(self) -> None:
        """Test serializing model to JSON string."""
        created = datetime.now(UTC)
        expires = created + timedelta(hours=24)

        record = IdempotencyRecord(
            key="test-key",
            fingerprint="a" * 64,
            state=RequestState.NEW,
            created_at=created,
            expires_at=expires,
        )

        json_str = record.model_dump_json()
        data = json.loads(json_str)

        assert data["key"] == "test-key"
        assert data["fingerprint"] == "a" * 64
        assert data["state"] == "NEW"
        assert data["response"] is None

    def test_model_validate(self) -> None:
        """Test deserializing model from dictionary."""
        created = datetime.now(UTC)
        expires = created + timedelta(hours=24)

        data = {
            "key": "test-key",
            "fingerprint": "a" * 64,
            "state": "NEW",
            "response": None,
            "created_at": created,
            "expires_at": expires,
            "execution_time_ms": None,
            "lease_token": None,
            "trace_id": None,
        }

        record = IdempotencyRecord.model_validate(data)

        assert record.key == "test-key"
        assert record.fingerprint == "a" * 64
        assert record.state == RequestState.NEW

    def test_model_validate_json(self) -> None:
        """Test deserializing model from JSON string."""
        created = datetime.now(UTC)
        expires = created + timedelta(hours=24)

        json_str = json.dumps(
            {
                "key": "test-key",
                "fingerprint": "a" * 64,
                "state": "COMPLETED",
                "response": {
                    "status": 200,
                    "headers": {},
                    "body_b64": base64.b64encode(b"test").decode("ascii"),
                },
                "created_at": created.isoformat(),
                "expires_at": expires.isoformat(),
                "execution_time_ms": 150,
                "lease_token": str(uuid4()),
                "trace_id": "trace-123",
            }
        )

        record = IdempotencyRecord.model_validate_json(json_str)

        assert record.key == "test-key"
        assert record.state == RequestState.COMPLETED
        assert record.response is not None
        assert record.response.status == 200


class TestLeaseResult:
    """Tests for LeaseResult model."""

    def test_instantiation_success(self) -> None:
        """Test creating a successful LeaseResult."""
        lease_token = str(uuid4())

        result = LeaseResult(
            success=True,
            lease_token=lease_token,
            existing_record=None,
        )

        assert result.success is True
        assert result.lease_token == lease_token
        assert result.existing_record is None

    def test_instantiation_failure(self) -> None:
        """Test creating a failed LeaseResult."""
        created = datetime.now(UTC)
        expires = created + timedelta(hours=24)

        existing_record = IdempotencyRecord(
            key="test-key",
            fingerprint="a" * 64,
            state=RequestState.RUNNING,
            created_at=created,
            expires_at=expires,
        )

        result = LeaseResult(
            success=False,
            lease_token=None,
            existing_record=existing_record,
        )

        assert result.success is False
        assert result.lease_token is None
        assert result.existing_record == existing_record

    def test_validation_success_requires_lease_token(self) -> None:
        """Test that success=True requires a lease_token."""
        with pytest.raises(ValidationError) as exc_info:
            LeaseResult(
                success=True,
                lease_token=None,
                existing_record=None,
            )

        errors = exc_info.value.errors()
        assert any("lease_token" in str(e["loc"]) for e in errors)

    def test_validation_success_cannot_have_existing_record(self) -> None:
        """Test that success=True cannot have an existing_record."""
        created = datetime.now(UTC)
        expires = created + timedelta(hours=24)

        existing_record = IdempotencyRecord(
            key="test-key",
            fingerprint="a" * 64,
            state=RequestState.RUNNING,
            created_at=created,
            expires_at=expires,
        )

        with pytest.raises(ValidationError) as exc_info:
            LeaseResult(
                success=True,
                lease_token=str(uuid4()),
                existing_record=existing_record,
            )

        errors = exc_info.value.errors()
        assert any("existing_record" in str(e["loc"]) for e in errors)

    def test_validation_failure_requires_existing_record(self) -> None:
        """Test that success=False requires an existing_record."""
        with pytest.raises(ValidationError) as exc_info:
            LeaseResult(
                success=False,
                lease_token=None,
                existing_record=None,
            )

        errors = exc_info.value.errors()
        assert any("existing_record" in str(e["loc"]) for e in errors)

    def test_validation_failure_cannot_have_lease_token(self) -> None:
        """Test that success=False cannot have a lease_token."""
        created = datetime.now(UTC)
        expires = created + timedelta(hours=24)

        existing_record = IdempotencyRecord(
            key="test-key",
            fingerprint="a" * 64,
            state=RequestState.RUNNING,
            created_at=created,
            expires_at=expires,
        )

        with pytest.raises(ValidationError) as exc_info:
            LeaseResult(
                success=False,
                lease_token=str(uuid4()),
                existing_record=existing_record,
            )

        errors = exc_info.value.errors()
        assert any("lease_token" in str(e["loc"]) for e in errors)

    def test_model_dump_success(self) -> None:
        """Test serializing a successful LeaseResult to dictionary."""
        lease_token = str(uuid4())

        result = LeaseResult(
            success=True,
            lease_token=lease_token,
            existing_record=None,
        )

        data = result.model_dump()

        assert data["success"] is True
        assert data["lease_token"] == lease_token
        assert data["existing_record"] is None

    def test_model_dump_failure(self) -> None:
        """Test serializing a failed LeaseResult to dictionary."""
        created = datetime.now(UTC)
        expires = created + timedelta(hours=24)

        existing_record = IdempotencyRecord(
            key="test-key",
            fingerprint="a" * 64,
            state=RequestState.RUNNING,
            created_at=created,
            expires_at=expires,
        )

        result = LeaseResult(
            success=False,
            lease_token=None,
            existing_record=existing_record,
        )

        data = result.model_dump()

        assert data["success"] is False
        assert data["lease_token"] is None
        assert data["existing_record"]["key"] == "test-key"

    def test_model_dump_json(self) -> None:
        """Test serializing LeaseResult to JSON string."""
        lease_token = str(uuid4())

        result = LeaseResult(
            success=True,
            lease_token=lease_token,
            existing_record=None,
        )

        json_str = result.model_dump_json()
        data = json.loads(json_str)

        assert data["success"] is True
        assert data["lease_token"] == lease_token
        assert data["existing_record"] is None

    def test_model_validate(self) -> None:
        """Test deserializing LeaseResult from dictionary."""
        lease_token = str(uuid4())
        data = {
            "success": True,
            "lease_token": lease_token,
            "existing_record": None,
        }

        result = LeaseResult.model_validate(data)

        assert result.success is True
        assert result.lease_token == lease_token
        assert result.existing_record is None

    def test_model_validate_json(self) -> None:
        """Test deserializing LeaseResult from JSON string."""
        created = datetime.now(UTC)
        expires = created + timedelta(hours=24)

        json_str = json.dumps(
            {
                "success": False,
                "lease_token": None,
                "existing_record": {
                    "key": "test-key",
                    "fingerprint": "a" * 64,
                    "state": "RUNNING",
                    "response": None,
                    "created_at": created.isoformat(),
                    "expires_at": expires.isoformat(),
                    "execution_time_ms": None,
                    "lease_token": str(uuid4()),
                    "trace_id": None,
                },
            }
        )

        result = LeaseResult.model_validate_json(json_str)

        assert result.success is False
        assert result.lease_token is None
        assert result.existing_record is not None
        assert result.existing_record.key == "test-key"
