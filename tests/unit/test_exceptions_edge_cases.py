"""Edge case tests for custom exceptions.

Tests exception behavior, attributes, inheritance, and error messages.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from idempotent_middleware.exceptions import (
    ConflictError,
    IdempotencyError,
    LeaseExpiredError,
    StorageError,
)


class TestIdempotencyErrorBase:
    """Tests for base IdempotencyError exception."""

    def test_can_be_raised(self) -> None:
        """IdempotencyError can be raised."""
        with pytest.raises(IdempotencyError):
            raise IdempotencyError("test error")

    def test_has_message_attribute(self) -> None:
        """IdempotencyError should have message attribute."""
        error = IdempotencyError("test message")
        assert error.message == "test message"

    def test_str_representation(self) -> None:
        """String representation should be the message."""
        error = IdempotencyError("test message")
        assert str(error) == "test message"

    def test_empty_message(self) -> None:
        """Empty message should be handled."""
        error = IdempotencyError("")
        assert error.message == ""
        assert str(error) == ""

    def test_unicode_message(self) -> None:
        """Unicode in message should be preserved."""
        message = "Error: 操作失败 🔥"
        error = IdempotencyError(message)
        assert error.message == message
        assert str(error) == message

    def test_very_long_message(self) -> None:
        """Very long message should be handled."""
        message = "x" * 10000
        error = IdempotencyError(message)
        assert error.message == message

    def test_multiline_message(self) -> None:
        """Multiline message should be preserved."""
        message = "Line 1\nLine 2\nLine 3"
        error = IdempotencyError(message)
        assert error.message == message

    def test_is_exception(self) -> None:
        """IdempotencyError should be an Exception."""
        error = IdempotencyError("test")
        assert isinstance(error, Exception)

    def test_can_catch_as_exception(self) -> None:
        """Can catch IdempotencyError as Exception."""
        with pytest.raises(IdempotencyError):
            raise IdempotencyError("test")

    @given(message=st.text(min_size=0, max_size=1000))
    def test_any_message_works(self, message: str) -> None:
        """Any string message should work."""
        error = IdempotencyError(message)
        assert error.message == message


class TestConflictError:
    """Tests for ConflictError exception."""

    def test_can_be_raised(self) -> None:
        """ConflictError can be raised."""
        with pytest.raises(ConflictError):
            raise ConflictError(
                message="Conflict",
                key="test-key",
                stored_fingerprint="a" * 64,
                request_fingerprint="b" * 64,
            )

    def test_inherits_from_idempotency_error(self) -> None:
        """ConflictError should inherit from IdempotencyError."""
        error = ConflictError(
            message="Conflict",
            key="test-key",
            stored_fingerprint="a" * 64,
            request_fingerprint="b" * 64,
        )
        assert isinstance(error, IdempotencyError)

    def test_can_catch_as_idempotency_error(self) -> None:
        """Can catch ConflictError as IdempotencyError."""
        with pytest.raises(IdempotencyError):
            raise ConflictError(
                message="Conflict",
                key="test-key",
                stored_fingerprint="a" * 64,
                request_fingerprint="b" * 64,
            )

    def test_has_all_attributes(self) -> None:
        """ConflictError should have all required attributes."""
        error = ConflictError(
            message="Test conflict",
            key="my-key",
            stored_fingerprint="a" * 64,
            request_fingerprint="b" * 64,
        )

        assert error.message == "Test conflict"
        assert error.key == "my-key"
        assert error.stored_fingerprint == "a" * 64
        assert error.request_fingerprint == "b" * 64

    def test_empty_key(self) -> None:
        """Empty key should be allowed."""
        error = ConflictError(
            message="Conflict",
            key="",
            stored_fingerprint="a" * 64,
            request_fingerprint="b" * 64,
        )
        assert error.key == ""

    def test_very_long_key(self) -> None:
        """Very long key should be handled."""
        key = "k" * 10000
        error = ConflictError(
            message="Conflict",
            key=key,
            stored_fingerprint="a" * 64,
            request_fingerprint="b" * 64,
        )
        assert error.key == key

    def test_unicode_in_key(self) -> None:
        """Unicode in key should be preserved."""
        key = "key-世界-123"
        error = ConflictError(
            message="Conflict",
            key=key,
            stored_fingerprint="a" * 64,
            request_fingerprint="b" * 64,
        )
        assert error.key == key

    def test_same_fingerprints_allowed(self) -> None:
        """Same fingerprints should be allowed (though semantically wrong)."""
        error = ConflictError(
            message="Conflict",
            key="test-key",
            stored_fingerprint="a" * 64,
            request_fingerprint="a" * 64,  # Same as stored
        )
        assert error.stored_fingerprint == error.request_fingerprint

    def test_invalid_fingerprint_format_allowed(self) -> None:
        """Invalid fingerprint format should be allowed (validation happens elsewhere)."""
        error = ConflictError(
            message="Conflict",
            key="test-key",
            stored_fingerprint="not-a-valid-fingerprint",
            request_fingerprint="also-not-valid",
        )
        assert error.stored_fingerprint == "not-a-valid-fingerprint"

    @given(
        message=st.text(min_size=0, max_size=500),
        key=st.text(min_size=0, max_size=255),
    )
    def test_any_message_and_key_works(self, message: str, key: str) -> None:
        """Any message and key should work."""
        error = ConflictError(
            message=message,
            key=key,
            stored_fingerprint="a" * 64,
            request_fingerprint="b" * 64,
        )
        assert error.message == message
        assert error.key == key


class TestLeaseExpiredError:
    """Tests for LeaseExpiredError exception."""

    def test_can_be_raised(self) -> None:
        """LeaseExpiredError can be raised."""
        with pytest.raises(LeaseExpiredError):
            raise LeaseExpiredError(
                message="Lease expired",
                lease_token="550e8400-e29b-41d4-a716-446655440000",
            )

    def test_inherits_from_idempotency_error(self) -> None:
        """LeaseExpiredError should inherit from IdempotencyError."""
        error = LeaseExpiredError(
            message="Lease expired",
            lease_token="550e8400-e29b-41d4-a716-446655440000",
        )
        assert isinstance(error, IdempotencyError)

    def test_can_catch_as_idempotency_error(self) -> None:
        """Can catch LeaseExpiredError as IdempotencyError."""
        with pytest.raises(IdempotencyError):
            raise LeaseExpiredError(
                message="Lease expired",
                lease_token="550e8400-e29b-41d4-a716-446655440000",
            )

    def test_has_all_attributes(self) -> None:
        """LeaseExpiredError should have all required attributes."""
        token = "550e8400-e29b-41d4-a716-446655440000"
        error = LeaseExpiredError(
            message="Lease has expired",
            lease_token=token,
        )

        assert error.message == "Lease has expired"
        assert error.lease_token == token

    def test_empty_lease_token(self) -> None:
        """Empty lease token should be allowed."""
        error = LeaseExpiredError(
            message="Lease expired",
            lease_token="",
        )
        assert error.lease_token == ""

    def test_invalid_uuid_format_allowed(self) -> None:
        """Invalid UUID format should be allowed (validation happens elsewhere)."""
        error = LeaseExpiredError(
            message="Lease expired",
            lease_token="not-a-valid-uuid",
        )
        assert error.lease_token == "not-a-valid-uuid"

    def test_very_long_lease_token(self) -> None:
        """Very long lease token should be handled."""
        token = "x" * 10000
        error = LeaseExpiredError(
            message="Lease expired",
            lease_token=token,
        )
        assert error.lease_token == token

    def test_unicode_in_lease_token(self) -> None:
        """Unicode in lease token should be preserved."""
        token = "token-世界-123"
        error = LeaseExpiredError(
            message="Lease expired",
            lease_token=token,
        )
        assert error.lease_token == token

    @given(
        message=st.text(min_size=0, max_size=500),
        token=st.text(min_size=0, max_size=255),
    )
    def test_any_message_and_token_works(self, message: str, token: str) -> None:
        """Any message and token should work."""
        error = LeaseExpiredError(
            message=message,
            lease_token=token,
        )
        assert error.message == message
        assert error.lease_token == token


class TestStorageError:
    """Tests for StorageError exception."""

    def test_can_be_raised(self) -> None:
        """StorageError can be raised."""
        with pytest.raises(StorageError):
            raise StorageError("Storage failed")

    def test_inherits_from_idempotency_error(self) -> None:
        """StorageError should inherit from IdempotencyError."""
        error = StorageError("Storage failed")
        assert isinstance(error, IdempotencyError)

    def test_can_catch_as_idempotency_error(self) -> None:
        """Can catch StorageError as IdempotencyError."""
        with pytest.raises(IdempotencyError):
            raise StorageError("Storage failed")

    def test_has_message_attribute(self) -> None:
        """StorageError should have message attribute."""
        error = StorageError("Storage failed")
        assert error.message == "Storage failed"

    def test_without_cause(self) -> None:
        """StorageError without cause should work."""
        error = StorageError("Storage failed")
        assert error.cause is None

    def test_with_cause(self) -> None:
        """StorageError with cause should store it."""
        cause = ValueError("Underlying error")
        error = StorageError("Storage failed", cause=cause)
        assert error.cause is cause

    def test_cause_can_be_any_exception(self) -> None:
        """Cause can be any exception type."""
        cause = RuntimeError("Runtime error")
        error = StorageError("Storage failed", cause=cause)
        assert error.cause is cause
        assert isinstance(error.cause, RuntimeError)

    def test_cause_can_be_custom_exception(self) -> None:
        """Cause can be a custom exception."""

        class CustomError(Exception):
            pass

        cause = CustomError("Custom error")
        error = StorageError("Storage failed", cause=cause)
        assert error.cause is cause

    def test_none_cause_explicitly(self) -> None:
        """Explicitly passing None for cause should work."""
        error = StorageError("Storage failed", cause=None)
        assert error.cause is None

    def test_exception_chaining(self) -> None:
        """StorageError can be raised with exception chaining."""
        try:
            try:
                raise ValueError("Original error")
            except ValueError as e:
                raise StorageError("Storage failed", cause=e) from e
        except StorageError as storage_error:
            assert storage_error.cause is not None
            assert isinstance(storage_error.cause, ValueError)
            assert str(storage_error.cause) == "Original error"
            # Check the chain
            assert storage_error.__cause__ is storage_error.cause

    def test_with_nested_exceptions(self) -> None:
        """StorageError can wrap multiple levels of exceptions."""
        try:
            raise ConnectionError("Network error")
        except ConnectionError:
            try:
                raise TimeoutError("Request timeout")
            except TimeoutError as e2:
                cause2 = e2
                # Use the more recent error as cause
                error = StorageError("Storage failed", cause=cause2)
                assert error.cause is cause2

    @given(message=st.text(min_size=0, max_size=500))
    def test_any_message_works(self, message: str) -> None:
        """Any message should work."""
        error = StorageError(message)
        assert error.message == message


class TestExceptionHierarchy:
    """Tests for exception inheritance and hierarchy."""

    def test_all_inherit_from_idempotency_error(self) -> None:
        """All custom exceptions should inherit from IdempotencyError."""
        assert issubclass(ConflictError, IdempotencyError)
        assert issubclass(LeaseExpiredError, IdempotencyError)
        assert issubclass(StorageError, IdempotencyError)

    def test_all_inherit_from_exception(self) -> None:
        """All custom exceptions should inherit from Exception."""
        assert issubclass(IdempotencyError, Exception)
        assert issubclass(ConflictError, Exception)
        assert issubclass(LeaseExpiredError, Exception)
        assert issubclass(StorageError, Exception)

    def test_can_catch_all_with_idempotency_error(self) -> None:
        """Can catch all custom exceptions with IdempotencyError."""
        exceptions = [
            ConflictError("", "key", "a" * 64, "b" * 64),
            LeaseExpiredError("", "token"),
            StorageError(""),
        ]

        for exc in exceptions:
            with pytest.raises(IdempotencyError):
                raise exc

    def test_specific_catch_doesnt_catch_others(self) -> None:
        """Specific exception catch should not catch other types."""
        # ConflictError should not catch StorageError
        with pytest.raises(StorageError):
            try:
                raise StorageError("test")
            except ConflictError:
                pytest.fail("Should not catch StorageError")

    def test_can_distinguish_between_types(self) -> None:
        """Can distinguish between different exception types."""
        try:
            raise ConflictError("", "key", "a" * 64, "b" * 64)
        except ConflictError as e:
            assert isinstance(e, ConflictError)
            assert not isinstance(e, StorageError)
            assert not isinstance(e, LeaseExpiredError)

    def test_multiple_except_clauses(self) -> None:
        """Multiple except clauses should work correctly."""
        caught = []

        for exc_class in [ConflictError, LeaseExpiredError, StorageError]:
            try:
                if exc_class == ConflictError:
                    raise ConflictError("", "key", "a" * 64, "b" * 64)
                elif exc_class == LeaseExpiredError:
                    raise LeaseExpiredError("", "token")
                else:
                    raise StorageError("")
            except ConflictError:
                caught.append("conflict")
            except LeaseExpiredError:
                caught.append("lease")
            except StorageError:
                caught.append("storage")

        assert caught == ["conflict", "lease", "storage"]


class TestExceptionInErrorHandling:
    """Tests for exceptions in error handling contexts."""

    def test_exception_in_finally_block(self) -> None:
        """Exception in finally block should propagate."""
        with pytest.raises(ConflictError):
            try:
                pass
            finally:
                raise ConflictError("", "key", "a" * 64, "b" * 64)

    def test_exception_in_context_manager(self) -> None:
        """Exception in context manager should work."""

        class Manager:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with pytest.raises(StorageError), Manager():
            raise StorageError("test")

    def test_reraise_preserves_type(self) -> None:
        """Re-raising should preserve exception type."""
        try:
            try:
                raise ConflictError("original", "key", "a" * 64, "b" * 64)
            except IdempotencyError:
                # Catch as base type and re-raise
                raise
        except ConflictError as e:
            # Should still be ConflictError
            assert isinstance(e, ConflictError)
            assert e.message == "original"

    def test_exception_with_traceback(self) -> None:
        """Exception should have traceback information."""
        try:
            raise StorageError("test")
        except StorageError as e:
            import traceback

            tb = traceback.format_exception(type(e), e, e.__traceback__)
            assert len(tb) > 0
            assert "StorageError" in "".join(tb)
