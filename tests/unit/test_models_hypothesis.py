"""Property-based tests for models module using Hypothesis.

This test suite uses property-based testing to verify model validation
and behavior across diverse inputs.
"""

import base64
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st
from pydantic import ValidationError

from idempotent_middleware.models import (
    IdempotencyRecord,
    LeaseResult,
    RequestState,
    StoredResponse,
)

# Strategies for models
status_code_strategy = st.integers(min_value=100, max_value=599)
invalid_status_code_strategy = st.one_of(
    st.integers(max_value=99),
    st.integers(min_value=600, max_value=999),
)

# Valid base64 strings
valid_base64_strategy = st.binary(min_size=0, max_size=10000).map(
    lambda b: base64.b64encode(b).decode("ascii")
)

# Invalid base64 strings (not properly encoded)
invalid_base64_strategy = st.text(
    alphabet=st.characters(
        blacklist_characters="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
    ),
    min_size=1,
    max_size=100,
)

# Headers strategy
headers_strategy = st.dictionaries(
    st.text(min_size=1, max_size=50),
    st.text(min_size=0, max_size=200),
    min_size=0,
    max_size=20,
)

# Fingerprint strategy (64 hex chars)
fingerprint_strategy = st.text(alphabet="0123456789abcdef", min_size=64, max_size=64)

# Invalid fingerprints
invalid_fingerprint_strategy = st.one_of(
    # Wrong length
    st.text(alphabet="0123456789abcdef", min_size=0, max_size=63),
    st.text(alphabet="0123456789abcdef", min_size=65, max_size=100),
    # Contains invalid characters
    st.text(alphabet="0123456789abcdefGHIJKL", min_size=64, max_size=64),
    # Uppercase (should be lowercase)
    st.text(alphabet="0123456789ABCDEF", min_size=64, max_size=64),
)

# Key strategy
key_strategy = st.text(min_size=1, max_size=255)

# Invalid keys
invalid_key_strategy = st.one_of(
    st.just(""),  # Empty
    st.text(min_size=256, max_size=1000),  # Too long
)

# Datetime strategies
datetime_strategy = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
)

# UUID strategy
uuid_strategy = st.builds(lambda: str(uuid4()))

# Invalid UUID strategy
invalid_uuid_strategy = st.one_of(
    st.text(alphabet="0123456789abcdef-", min_size=30, max_size=40),
    st.just("not-a-uuid"),
    st.just(""),
)


class TestStoredResponseProperties:
    """Property-based tests for StoredResponse model."""

    @given(
        status=status_code_strategy,
        headers=headers_strategy,
        body_b64=valid_base64_strategy,
    )
    def test_valid_response_always_accepted(
        self,
        status: int,
        headers: dict[str, str],
        body_b64: str,
    ) -> None:
        """Valid responses should always be accepted."""
        response = StoredResponse(
            status=status,
            headers=headers,
            body_b64=body_b64,
        )

        assert response.status == status
        assert response.headers == headers
        assert response.body_b64 == body_b64

    @given(
        status=invalid_status_code_strategy,
        body_b64=valid_base64_strategy,
    )
    def test_invalid_status_code_rejected(
        self,
        status: int,
        body_b64: str,
    ) -> None:
        """Invalid status codes should be rejected."""
        with pytest.raises(ValidationError):
            StoredResponse(
                status=status,
                headers={},
                body_b64=body_b64,
            )

    @given(status=status_code_strategy, invalid_b64=invalid_base64_strategy)
    def test_invalid_base64_rejected(self, status: int, invalid_b64: str) -> None:
        """Invalid base64 should be rejected."""
        try:
            # Try to decode it first to confirm it's actually invalid
            base64.b64decode(invalid_b64)
            # If it succeeded, skip this test case
            assume(False)
        except Exception:
            # Good, it's actually invalid
            pass

        with pytest.raises(ValidationError) as exc_info:
            StoredResponse(
                status=status,
                headers={},
                body_b64=invalid_b64,
            )

        assert "Invalid base64 encoding" in str(exc_info.value)

    @given(body_b64=valid_base64_strategy)
    def test_get_body_bytes_round_trip(self, body_b64: str) -> None:
        """get_body_bytes should decode correctly."""
        response = StoredResponse(
            status=200,
            headers={},
            body_b64=body_b64,
        )

        decoded = response.get_body_bytes()

        # Should match original bytes
        original = base64.b64decode(body_b64)
        assert decoded == original

    @given(data=st.binary(min_size=0, max_size=10000))
    def test_body_encoding_round_trip(self, data: bytes) -> None:
        """Encoding and decoding body should preserve data."""
        body_b64 = base64.b64encode(data).decode("ascii")

        response = StoredResponse(
            status=200,
            headers={},
            body_b64=body_b64,
        )

        assert response.get_body_bytes() == data

    @given(
        status=status_code_strategy,
        headers=headers_strategy,
        body_b64=valid_base64_strategy,
    )
    def test_model_dump_json_round_trip(
        self,
        status: int,
        headers: dict[str, str],
        body_b64: str,
    ) -> None:
        """Model should serialize and deserialize correctly."""
        response1 = StoredResponse(
            status=status,
            headers=headers,
            body_b64=body_b64,
        )

        # Serialize to JSON
        json_str = response1.model_dump_json()

        # Deserialize
        response2 = StoredResponse.model_validate_json(json_str)

        # Should be equivalent
        assert response1.status == response2.status
        assert response1.headers == response2.headers
        assert response1.body_b64 == response2.body_b64


class TestIdempotencyRecordProperties:
    """Property-based tests for IdempotencyRecord model."""

    @given(
        key=key_strategy,
        fingerprint=fingerprint_strategy,
        created_at=datetime_strategy,
        ttl_seconds=st.integers(min_value=1, max_value=604800),
    )
    def test_valid_record_accepted(
        self,
        key: str,
        fingerprint: str,
        created_at: datetime,
        ttl_seconds: int,
    ) -> None:
        """Valid records should always be accepted."""
        expires_at = created_at + timedelta(seconds=ttl_seconds)

        record = IdempotencyRecord(
            key=key,
            fingerprint=fingerprint,
            state=RequestState.NEW,
            response=None,
            created_at=created_at,
            expires_at=expires_at,
        )

        assert record.key == key
        assert record.fingerprint == fingerprint
        assert record.state == RequestState.NEW
        assert record.created_at == created_at
        assert record.expires_at == expires_at

    @given(invalid_key=invalid_key_strategy, fingerprint=fingerprint_strategy)
    def test_invalid_key_rejected(self, invalid_key: str, fingerprint: str) -> None:
        """Invalid keys should be rejected."""
        now = datetime.utcnow()

        with pytest.raises(ValidationError):
            IdempotencyRecord(
                key=invalid_key,
                fingerprint=fingerprint,
                state=RequestState.NEW,
                response=None,
                created_at=now,
                expires_at=now + timedelta(hours=1),
            )

    @given(key=key_strategy, invalid_fp=invalid_fingerprint_strategy)
    def test_invalid_fingerprint_rejected(self, key: str, invalid_fp: str) -> None:
        """Invalid fingerprints should be rejected."""
        now = datetime.utcnow()

        with pytest.raises(ValidationError):
            IdempotencyRecord(
                key=key,
                fingerprint=invalid_fp,
                state=RequestState.NEW,
                response=None,
                created_at=now,
                expires_at=now + timedelta(hours=1),
            )

    @given(
        key=key_strategy,
        fingerprint=fingerprint_strategy,
        created_at=datetime_strategy,
    )
    def test_expires_at_must_be_after_created_at(
        self,
        key: str,
        fingerprint: str,
        created_at: datetime,
    ) -> None:
        """expires_at must be after created_at."""
        # Try with same time - should fail
        with pytest.raises(ValidationError) as exc_info:
            IdempotencyRecord(
                key=key,
                fingerprint=fingerprint,
                state=RequestState.NEW,
                response=None,
                created_at=created_at,
                expires_at=created_at,
            )

        assert "expires_at must be after created_at" in str(exc_info.value)

        # Try with earlier time - should fail
        with pytest.raises(ValidationError):
            IdempotencyRecord(
                key=key,
                fingerprint=fingerprint,
                state=RequestState.NEW,
                response=None,
                created_at=created_at,
                expires_at=created_at - timedelta(seconds=1),
            )

    @given(
        key=key_strategy,
        fingerprint=fingerprint_strategy,
        uuid_str=uuid_strategy,
    )
    def test_valid_lease_token_accepted(
        self,
        key: str,
        fingerprint: str,
        uuid_str: str,
    ) -> None:
        """Valid UUID lease tokens should be accepted."""
        now = datetime.utcnow()

        record = IdempotencyRecord(
            key=key,
            fingerprint=fingerprint,
            state=RequestState.RUNNING,
            response=None,
            created_at=now,
            expires_at=now + timedelta(hours=1),
            lease_token=uuid_str,
        )

        assert record.lease_token == uuid_str

    @given(
        key=key_strategy,
        fingerprint=fingerprint_strategy,
        invalid_uuid=invalid_uuid_strategy,
    )
    def test_invalid_lease_token_rejected(
        self,
        key: str,
        fingerprint: str,
        invalid_uuid: str,
    ) -> None:
        """Invalid UUID lease tokens should be rejected."""
        now = datetime.utcnow()

        with pytest.raises(ValidationError) as exc_info:
            IdempotencyRecord(
                key=key,
                fingerprint=fingerprint,
                state=RequestState.RUNNING,
                response=None,
                created_at=now,
                expires_at=now + timedelta(hours=1),
                lease_token=invalid_uuid,
            )

        assert "Invalid UUID format" in str(exc_info.value)

    @given(
        key=key_strategy,
        fingerprint=fingerprint_strategy,
        exec_time=st.integers(min_value=0, max_value=1000000),
    )
    def test_non_negative_execution_time(
        self,
        key: str,
        fingerprint: str,
        exec_time: int,
    ) -> None:
        """Execution time must be non-negative."""
        now = datetime.utcnow()

        record = IdempotencyRecord(
            key=key,
            fingerprint=fingerprint,
            state=RequestState.COMPLETED,
            response=None,
            created_at=now,
            expires_at=now + timedelta(hours=1),
            execution_time_ms=exec_time,
        )

        assert record.execution_time_ms == exec_time

    @given(
        key=key_strategy,
        fingerprint=fingerprint_strategy,
        negative_time=st.integers(max_value=-1),
    )
    def test_negative_execution_time_rejected(
        self,
        key: str,
        fingerprint: str,
        negative_time: int,
    ) -> None:
        """Negative execution time should be rejected."""
        now = datetime.utcnow()

        with pytest.raises(ValidationError):
            IdempotencyRecord(
                key=key,
                fingerprint=fingerprint,
                state=RequestState.COMPLETED,
                response=None,
                created_at=now,
                expires_at=now + timedelta(hours=1),
                execution_time_ms=negative_time,
            )


class TestLeaseResultProperties:
    """Property-based tests for LeaseResult model."""

    @given(uuid_str=uuid_strategy)
    def test_successful_lease_result(self, uuid_str: str) -> None:
        """Successful lease result should have token and no existing record."""
        result = LeaseResult(
            success=True,
            lease_token=uuid_str,
            existing_record=None,
        )

        assert result.success is True
        assert result.lease_token == uuid_str
        assert result.existing_record is None

    @given(
        key=key_strategy,
        fingerprint=fingerprint_strategy,
    )
    def test_failed_lease_result(self, key: str, fingerprint: str) -> None:
        """Failed lease result should have existing record and no token."""
        now = datetime.utcnow()

        existing = IdempotencyRecord(
            key=key,
            fingerprint=fingerprint,
            state=RequestState.RUNNING,
            response=None,
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )

        result = LeaseResult(
            success=False,
            lease_token=None,
            existing_record=existing,
        )

        assert result.success is False
        assert result.lease_token is None
        assert result.existing_record is not None

    @given(uuid_str=uuid_strategy)
    def test_success_requires_lease_token(self, uuid_str: str) -> None:
        """Success=True requires lease_token to be present."""
        # Valid case
        result = LeaseResult(
            success=True,
            lease_token=uuid_str,
            existing_record=None,
        )
        assert result.success is True

        # Invalid case - success without token
        with pytest.raises(ValidationError) as exc_info:
            LeaseResult(
                success=True,
                lease_token=None,
                existing_record=None,
            )

        assert "lease_token must be provided when success is True" in str(exc_info.value)

    @given(
        key=key_strategy,
        fingerprint=fingerprint_strategy,
    )
    def test_failure_requires_existing_record(
        self,
        key: str,
        fingerprint: str,
    ) -> None:
        """Success=False requires existing_record to be present."""
        now = datetime.utcnow()

        existing = IdempotencyRecord(
            key=key,
            fingerprint=fingerprint,
            state=RequestState.RUNNING,
            response=None,
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )

        # Valid case
        result = LeaseResult(
            success=False,
            lease_token=None,
            existing_record=existing,
        )
        assert result.success is False

        # Invalid case - failure without existing record
        with pytest.raises(ValidationError) as exc_info:
            LeaseResult(
                success=False,
                lease_token=None,
                existing_record=None,
            )

        assert "existing_record must be provided when success is False" in str(exc_info.value)

    @given(
        uuid_str=uuid_strategy,
        key=key_strategy,
        fingerprint=fingerprint_strategy,
    )
    def test_success_cannot_have_existing_record(
        self,
        uuid_str: str,
        key: str,
        fingerprint: str,
    ) -> None:
        """Success=True cannot have existing_record."""
        now = datetime.utcnow()

        existing = IdempotencyRecord(
            key=key,
            fingerprint=fingerprint,
            state=RequestState.RUNNING,
            response=None,
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )

        with pytest.raises(ValidationError) as exc_info:
            LeaseResult(
                success=True,
                lease_token=uuid_str,
                existing_record=existing,
            )

        assert "existing_record must be None when success is True" in str(exc_info.value)

    @given(uuid_str=uuid_strategy)
    def test_failure_cannot_have_lease_token(self, uuid_str: str) -> None:
        """Success=False cannot have lease_token."""
        now = datetime.utcnow()

        existing = IdempotencyRecord(
            key="test-key",
            fingerprint="a" * 64,
            state=RequestState.RUNNING,
            response=None,
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )

        with pytest.raises(ValidationError) as exc_info:
            LeaseResult(
                success=False,
                lease_token=uuid_str,
                existing_record=existing,
            )

        assert "lease_token must be None when success is False" in str(exc_info.value)


class TestRequestStateEnum:
    """Property-based tests for RequestState enum."""

    def test_all_states_are_strings(self) -> None:
        """All RequestState values should be strings."""
        for state in RequestState:
            assert isinstance(state.value, str)

    def test_state_names_match_values(self) -> None:
        """State names should match their string values."""
        for state in RequestState:
            assert state.name == state.value

    @given(state=st.sampled_from(list(RequestState)))
    def test_state_can_be_used_in_model(self, state: RequestState) -> None:
        """Any RequestState should work in a model."""
        now = datetime.utcnow()

        record = IdempotencyRecord(
            key="test-key",
            fingerprint="a" * 64,
            state=state,
            response=None,
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )

        assert record.state == state

    def test_state_comparison(self) -> None:
        """RequestState should support comparison."""
        assert RequestState.NEW == RequestState.NEW
        assert RequestState.NEW != RequestState.RUNNING
        assert RequestState.NEW.value == "NEW"
