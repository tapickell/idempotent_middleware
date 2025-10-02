"""
Pytest configuration and shared fixtures for idempotent_middleware tests.
"""


import pytest


@pytest.fixture
def sample_idempotency_key() -> str:
    """Provide a sample idempotency key for tests."""
    return "test-key-12345"


@pytest.fixture
def sample_request_body() -> bytes:
    """Provide a sample request body for tests."""
    return b'{"data": "test"}'


# Additional shared fixtures will be added as needed
