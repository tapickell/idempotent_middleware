"""Unit tests for custom exceptions.

Tests in this module verify that the exception hierarchy is correctly
defined and that exceptions carry the expected information.
"""

import pytest

from idempotent_middleware.exceptions import (
    ConflictError,
    IdempotencyError,
    LeaseExpiredError,
    StorageError,
)


class TestIdempotencyError:
    """Test suite for the base IdempotencyError exception."""

    def test_idempotency_error_creation(self):
        """IdempotencyError should be created with a message."""
        error = IdempotencyError("Test error message")
        assert str(error) == "Test error message"
        assert error.message == "Test error message"

    def test_idempotency_error_is_exception(self):
        """IdempotencyError should inherit from Exception."""
        error = IdempotencyError("Test error")
        assert isinstance(error, Exception)

    def test_idempotency_error_can_be_raised(self):
        """IdempotencyError should be raisable."""
        with pytest.raises(IdempotencyError) as exc_info:
            raise IdempotencyError("Test error")
        assert str(exc_info.value) == "Test error"

    def test_idempotency_error_can_be_caught_as_exception(self):
        """IdempotencyError should be catchable as Exception."""
        try:
            raise IdempotencyError("Test error")
        except Exception as e:
            assert isinstance(e, IdempotencyError)
            assert str(e) == "Test error"


class TestConflictError:
    """Test suite for the ConflictError exception."""

    def test_conflict_error_creation(self):
        """ConflictError should be created with full details."""
        error = ConflictError(
            message="Fingerprint mismatch",
            key="payment-123",
            stored_fingerprint="a" * 64,
            request_fingerprint="b" * 64,
        )
        assert str(error) == "Fingerprint mismatch"
        assert error.message == "Fingerprint mismatch"
        assert error.key == "payment-123"
        assert error.stored_fingerprint == "a" * 64
        assert error.request_fingerprint == "b" * 64

    def test_conflict_error_inherits_from_idempotency_error(self):
        """ConflictError should inherit from IdempotencyError."""
        error = ConflictError(
            message="Test",
            key="key-1",
            stored_fingerprint="a" * 64,
            request_fingerprint="b" * 64,
        )
        assert isinstance(error, IdempotencyError)
        assert isinstance(error, Exception)

    def test_conflict_error_can_be_raised(self):
        """ConflictError should be raisable."""
        with pytest.raises(ConflictError) as exc_info:
            raise ConflictError(
                message="Conflict detected",
                key="key-1",
                stored_fingerprint="a" * 64,
                request_fingerprint="b" * 64,
            )
        assert str(exc_info.value) == "Conflict detected"
        assert exc_info.value.key == "key-1"

    def test_conflict_error_can_be_caught_as_idempotency_error(self):
        """ConflictError should be catchable as IdempotencyError."""
        try:
            raise ConflictError(
                message="Test conflict",
                key="key-1",
                stored_fingerprint="a" * 64,
                request_fingerprint="b" * 64,
            )
        except IdempotencyError as e:
            assert isinstance(e, ConflictError)
            assert e.key == "key-1"

    def test_conflict_error_attributes_accessible(self):
        """ConflictError attributes should be accessible."""
        error = ConflictError(
            message="Conflict",
            key="test-key",
            stored_fingerprint="1" * 64,
            request_fingerprint="2" * 64,
        )
        # All attributes should be accessible
        assert hasattr(error, "message")
        assert hasattr(error, "key")
        assert hasattr(error, "stored_fingerprint")
        assert hasattr(error, "request_fingerprint")


class TestLeaseExpiredError:
    """Test suite for the LeaseExpiredError exception."""

    def test_lease_expired_error_creation(self):
        """LeaseExpiredError should be created with message and lease token."""
        error = LeaseExpiredError(
            message="Lease has expired",
            lease_token="550e8400-e29b-41d4-a716-446655440000",
        )
        assert str(error) == "Lease has expired"
        assert error.message == "Lease has expired"
        assert error.lease_token == "550e8400-e29b-41d4-a716-446655440000"

    def test_lease_expired_error_inherits_from_idempotency_error(self):
        """LeaseExpiredError should inherit from IdempotencyError."""
        error = LeaseExpiredError(
            message="Test",
            lease_token="550e8400-e29b-41d4-a716-446655440000",
        )
        assert isinstance(error, IdempotencyError)
        assert isinstance(error, Exception)

    def test_lease_expired_error_can_be_raised(self):
        """LeaseExpiredError should be raisable."""
        with pytest.raises(LeaseExpiredError) as exc_info:
            raise LeaseExpiredError(
                message="Lease token invalid",
                lease_token="test-token",
            )
        assert str(exc_info.value) == "Lease token invalid"
        assert exc_info.value.lease_token == "test-token"

    def test_lease_expired_error_can_be_caught_as_idempotency_error(self):
        """LeaseExpiredError should be catchable as IdempotencyError."""
        try:
            raise LeaseExpiredError(
                message="Expired",
                lease_token="token-123",
            )
        except IdempotencyError as e:
            assert isinstance(e, LeaseExpiredError)
            assert e.lease_token == "token-123"

    def test_lease_expired_error_attributes_accessible(self):
        """LeaseExpiredError attributes should be accessible."""
        error = LeaseExpiredError(
            message="Expired",
            lease_token="my-token",
        )
        assert hasattr(error, "message")
        assert hasattr(error, "lease_token")


class TestStorageError:
    """Test suite for the StorageError exception."""

    def test_storage_error_creation_with_message_only(self):
        """StorageError should be created with just a message."""
        error = StorageError(message="Storage backend unavailable")
        assert str(error) == "Storage backend unavailable"
        assert error.message == "Storage backend unavailable"
        assert error.cause is None

    def test_storage_error_creation_with_cause(self):
        """StorageError should be created with message and cause."""
        cause = ValueError("Connection failed")
        error = StorageError(
            message="Failed to connect to Redis",
            cause=cause,
        )
        assert str(error) == "Failed to connect to Redis"
        assert error.message == "Failed to connect to Redis"
        assert error.cause is cause

    def test_storage_error_inherits_from_idempotency_error(self):
        """StorageError should inherit from IdempotencyError."""
        error = StorageError(message="Test")
        assert isinstance(error, IdempotencyError)
        assert isinstance(error, Exception)

    def test_storage_error_can_be_raised(self):
        """StorageError should be raisable."""
        with pytest.raises(StorageError) as exc_info:
            raise StorageError(message="Backend error")
        assert str(exc_info.value) == "Backend error"

    def test_storage_error_can_be_raised_with_cause(self):
        """StorageError should be raisable with a cause."""
        cause = ConnectionError("Network timeout")
        with pytest.raises(StorageError) as exc_info:
            raise StorageError(message="Storage failed", cause=cause)
        assert str(exc_info.value) == "Storage failed"
        assert exc_info.value.cause is cause

    def test_storage_error_can_be_caught_as_idempotency_error(self):
        """StorageError should be catchable as IdempotencyError."""
        try:
            raise StorageError(message="Storage issue")
        except IdempotencyError as e:
            assert isinstance(e, StorageError)
            assert str(e) == "Storage issue"

    def test_storage_error_attributes_accessible(self):
        """StorageError attributes should be accessible."""
        cause = RuntimeError("Test cause")
        error = StorageError(message="Error", cause=cause)
        assert hasattr(error, "message")
        assert hasattr(error, "cause")
        assert error.cause is cause

    def test_storage_error_cause_is_optional(self):
        """StorageError cause should be optional."""
        error = StorageError(message="Test")
        assert error.cause is None


class TestExceptionHierarchy:
    """Test suite for the overall exception hierarchy."""

    def test_all_custom_exceptions_inherit_from_idempotency_error(self):
        """All custom exceptions should inherit from IdempotencyError."""
        conflict = ConflictError(
            message="test", key="k", stored_fingerprint="a" * 64, request_fingerprint="b" * 64
        )
        lease_expired = LeaseExpiredError(message="test", lease_token="token")
        storage = StorageError(message="test")

        assert isinstance(conflict, IdempotencyError)
        assert isinstance(lease_expired, IdempotencyError)
        assert isinstance(storage, IdempotencyError)

    def test_catch_all_with_base_exception(self):
        """Base IdempotencyError should catch all custom exceptions."""
        exceptions_to_test = [
            ConflictError(
                message="conflict",
                key="k",
                stored_fingerprint="a" * 64,
                request_fingerprint="b" * 64,
            ),
            LeaseExpiredError(message="expired", lease_token="token"),
            StorageError(message="storage"),
        ]

        for exc in exceptions_to_test:
            try:
                raise exc
            except IdempotencyError as e:
                # Should catch all types
                assert isinstance(e, IdempotencyError)

    def test_exception_types_are_distinct(self):
        """Different exception types should be distinguishable."""
        conflict = ConflictError(
            message="test", key="k", stored_fingerprint="a" * 64, request_fingerprint="b" * 64
        )
        lease_expired = LeaseExpiredError(message="test", lease_token="token")
        storage = StorageError(message="test")

        assert not isinstance(conflict, LeaseExpiredError)
        assert not isinstance(conflict, StorageError)
        assert not isinstance(lease_expired, ConflictError)
        assert not isinstance(lease_expired, StorageError)
        assert not isinstance(storage, ConflictError)
        assert not isinstance(storage, LeaseExpiredError)

    def test_selective_exception_catching(self):
        """Different exception types should be catchable selectively."""
        # Test that we can catch specific exception types
        with pytest.raises(ConflictError):
            raise ConflictError(
                message="test", key="k", stored_fingerprint="a" * 64, request_fingerprint="b" * 64
            )

        with pytest.raises(LeaseExpiredError):
            raise LeaseExpiredError(message="test", lease_token="token")

        with pytest.raises(StorageError):
            raise StorageError(message="test")
