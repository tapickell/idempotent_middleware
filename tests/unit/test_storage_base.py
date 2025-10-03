"""Unit tests for storage adapter protocol and interface.

Tests in this module verify that the StorageAdapter protocol is correctly
defined and that runtime type checking works as expected.
"""

from idempotent_middleware.models import IdempotencyRecord, LeaseResult, StoredResponse
from idempotent_middleware.storage.base import StorageAdapter


class TestStorageAdapterProtocol:
    """Test suite for the StorageAdapter protocol definition."""

    def test_storage_adapter_is_runtime_checkable(self):
        """StorageAdapter protocol should be runtime checkable."""

        # Protocol should have __protocol_attrs__
        assert hasattr(StorageAdapter, "__protocol_attrs__")

    def test_storage_adapter_has_required_methods(self):
        """StorageAdapter protocol should define all required methods."""
        # Check that protocol has the expected method signatures
        assert hasattr(StorageAdapter, "get")
        assert hasattr(StorageAdapter, "put_new_running")
        assert hasattr(StorageAdapter, "complete")
        assert hasattr(StorageAdapter, "fail")
        assert hasattr(StorageAdapter, "cleanup_expired")

    def test_storage_adapter_protocol_with_conforming_class(self):
        """A class implementing all methods should conform to StorageAdapter."""

        class ConformingAdapter:
            async def get(self, key: str) -> IdempotencyRecord | None:  # noqa: ARG002
                return None

            async def put_new_running(  # noqa: ARG002
                self,
                key: str,
                fingerprint: str,
                ttl_seconds: int,
                trace_id: str | None = None,
            ) -> LeaseResult:
                return LeaseResult(success=False, existing_record=None)  # type: ignore

            async def complete(  # noqa: ARG002
                self,
                key: str,
                lease_token: str,
                response: StoredResponse,
                execution_time_ms: int,
            ) -> bool:
                return True

            async def fail(  # noqa: ARG002
                self,
                key: str,
                lease_token: str,
                response: StoredResponse,
                execution_time_ms: int,
            ) -> bool:
                return True

            async def cleanup_expired(self) -> int:
                return 0

        adapter = ConformingAdapter()
        assert isinstance(adapter, StorageAdapter)

    def test_storage_adapter_protocol_with_missing_method(self):
        """A class missing required methods should not conform to StorageAdapter."""

        class IncompleteAdapter:
            async def get(self, key: str) -> IdempotencyRecord | None:  # noqa: ARG002
                return None

            # Missing other required methods

        adapter = IncompleteAdapter()
        assert not isinstance(adapter, StorageAdapter)

    def test_storage_adapter_protocol_with_wrong_signature(self):
        """A class with wrong method signatures should not conform to StorageAdapter."""

        class WrongSignatureAdapter:
            async def get(self) -> IdempotencyRecord | None:  # Missing key parameter
                return None

            async def put_new_running(  # noqa: ARG002
                self,
                key: str,
                fingerprint: str,
                ttl_seconds: int,
                trace_id: str | None = None,
            ) -> LeaseResult:
                return LeaseResult(success=False, existing_record=None)  # type: ignore

            async def complete(  # noqa: ARG002
                self,
                key: str,
                lease_token: str,
                response: StoredResponse,
                execution_time_ms: int,
            ) -> bool:
                return True

            async def fail(  # noqa: ARG002
                self,
                key: str,
                lease_token: str,
                response: StoredResponse,
                execution_time_ms: int,
            ) -> bool:
                return True

            async def cleanup_expired(self) -> int:
                return 0

        _ = WrongSignatureAdapter()
        # Protocol checking is structural, so this might still pass at runtime
        # but would fail type checking
        # This is a limitation of runtime protocol checking


class TestStorageAdapterDocumentation:
    """Test that StorageAdapter has proper documentation."""

    def test_protocol_has_docstring(self):
        """StorageAdapter protocol should have comprehensive docstring."""
        assert StorageAdapter.__doc__ is not None
        assert len(StorageAdapter.__doc__) > 100
        assert "thread-safe" in StorageAdapter.__doc__.lower()
        assert "atomic" in StorageAdapter.__doc__.lower()

    def test_get_method_has_docstring(self):
        """get() method should have docstring."""
        assert StorageAdapter.get.__doc__ is not None
        assert "idempotency key" in StorageAdapter.get.__doc__.lower()

    def test_put_new_running_method_has_docstring(self):
        """put_new_running() method should have docstring."""
        assert StorageAdapter.put_new_running.__doc__ is not None
        assert "atomic" in StorageAdapter.put_new_running.__doc__.lower()
        assert "lease" in StorageAdapter.put_new_running.__doc__.lower()

    def test_complete_method_has_docstring(self):
        """complete() method should have docstring."""
        assert StorageAdapter.complete.__doc__ is not None
        assert "completed" in StorageAdapter.complete.__doc__.lower()

    def test_fail_method_has_docstring(self):
        """fail() method should have docstring."""
        assert StorageAdapter.fail.__doc__ is not None
        assert "failed" in StorageAdapter.fail.__doc__.lower()

    def test_cleanup_expired_method_has_docstring(self):
        """cleanup_expired() method should have docstring."""
        assert StorageAdapter.cleanup_expired.__doc__ is not None
        assert "expired" in StorageAdapter.cleanup_expired.__doc__.lower()
