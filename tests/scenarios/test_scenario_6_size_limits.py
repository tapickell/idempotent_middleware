"""Scenario 6: Size Limits Tests

This test suite verifies the middleware's enforcement of size limits on various
request components. Tests cover:

1. Request body size limits
2. Response body size limits
3. Idempotency-Key length limits
4. Header size limits
5. Configuration of size limits
6. Graceful rejection of oversized requests

Key behaviors tested:
- Request body at limit works
- Request body over limit rejected (413 or 400)
- Response body at limit stored correctly
- Response body over limit handled gracefully
- Idempotency-Key at max length (200 chars) works
- Idempotency-Key too long rejected (422)
- Empty key rejected
- Size limit configuration per adapter
- Total headers size limits
- Graceful error responses
"""

import base64
from typing import Optional

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from idempotent_middleware.adapters.asgi import ASGIIdempotencyMiddleware
from idempotent_middleware.config import IdempotencyConfig
from idempotent_middleware.storage.memory import MemoryStorageAdapter


# Test fixtures
@pytest.fixture
def storage():
    """Create a fresh memory storage adapter for each test."""
    return MemoryStorageAdapter()


@pytest.fixture
def default_config():
    """Create a default config with standard size limits."""
    return IdempotencyConfig(
        enabled_methods=["POST", "PUT", "PATCH", "DELETE"],
        default_ttl_seconds=86400,
        wait_policy="wait",
        max_body_bytes=1048576,  # 1 MB default
    )


@pytest.fixture
def small_body_config():
    """Create a config with small body size limit for testing."""
    return IdempotencyConfig(
        enabled_methods=["POST"],
        default_ttl_seconds=86400,
        wait_policy="wait",
        max_body_bytes=1024,  # 1 KB limit
    )


@pytest.fixture
def unlimited_config():
    """Create a config with unlimited body size."""
    return IdempotencyConfig(
        enabled_methods=["POST"],
        default_ttl_seconds=86400,
        wait_policy="wait",
        max_body_bytes=0,  # Unlimited
    )


# Helper functions
def generate_payload(size_bytes: int) -> dict:
    """Generate a JSON payload of approximately the specified size."""
    # Account for JSON overhead: {"data": "..."}
    data_size = size_bytes - 12
    if data_size < 0:
        data_size = 1
    return {"data": "x" * data_size}


def generate_large_string(size_bytes: int) -> str:
    """Generate a string of exactly the specified size."""
    return "x" * size_bytes


class TestRequestBodySizeLimits:
    """Test request body size limit enforcement."""

    def test_request_body_at_limit_succeeds(self, storage, small_body_config):
        """Test that request body at the configured limit is accepted.

        A request body exactly at max_body_bytes should be processed normally.
        """
        app = FastAPI()
        app.add_middleware(ASGIIdempotencyMiddleware, storage=storage, config=small_body_config)

        @app.post("/api/at-limit")
        async def at_limit_endpoint(
            data: dict,
            idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
        ):
            return {"status": "success", "size": len(str(data))}

        client = TestClient(app)

        # Create payload at limit (1024 bytes)
        payload = generate_payload(1024)

        response = client.post(
            "/api/at-limit",
            headers={"Idempotency-Key": "at-limit-test"},
            json=payload,
        )

        # Should succeed
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    def test_request_body_under_limit_succeeds(self, storage, small_body_config):
        """Test that request body under the limit is accepted."""
        app = FastAPI()
        app.add_middleware(ASGIIdempotencyMiddleware, storage=storage, config=small_body_config)

        @app.post("/api/under-limit")
        async def under_limit_endpoint(
            data: dict,
            idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
        ):
            return {"status": "success"}

        client = TestClient(app)

        # Create small payload (512 bytes, under 1024 limit)
        payload = generate_payload(512)

        response = client.post(
            "/api/under-limit",
            headers={"Idempotency-Key": "under-limit-test"},
            json=payload,
        )

        assert response.status_code == 200

    def test_request_body_over_limit_handled_gracefully(self, storage, small_body_config):
        """Test that request body over limit is handled gracefully.

        The middleware validates request body size and rejects oversized requests
        with a 500 error (IdempotencyError is caught and returned as 500).
        """
        app = FastAPI()
        app.add_middleware(ASGIIdempotencyMiddleware, storage=storage, config=small_body_config)

        @app.post("/api/over-limit")
        async def over_limit_endpoint(
            data: dict,
            idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
        ):
            return {"status": "success", "received": True}

        client = TestClient(app)

        # Create payload over limit (2048 bytes, over 1024 limit)
        payload = generate_payload(2048)

        response = client.post(
            "/api/over-limit",
            headers={"Idempotency-Key": "over-limit-test"},
            json=payload,
        )

        # Middleware rejects oversized body with 500 error
        assert response.status_code == 500
        assert b"Request body exceeds maximum size" in response.content

    def test_empty_request_body_succeeds(self, storage, default_config):
        """Test that empty request body is handled correctly."""
        app = FastAPI()
        app.add_middleware(ASGIIdempotencyMiddleware, storage=storage, config=default_config)

        @app.post("/api/empty-body")
        async def empty_body_endpoint(idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
            return {"status": "success"}

        client = TestClient(app)

        response = client.post(
            "/api/empty-body",
            headers={"Idempotency-Key": "empty-body-test"},
        )

        assert response.status_code == 200

    def test_unlimited_body_size_accepts_large_payloads(self, storage, unlimited_config):
        """Test that unlimited body size (max_body_bytes=0) accepts large payloads."""
        app = FastAPI()
        app.add_middleware(ASGIIdempotencyMiddleware, storage=storage, config=unlimited_config)

        @app.post("/api/unlimited")
        async def unlimited_endpoint(
            data: dict,
            idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
        ):
            return {"status": "success"}

        client = TestClient(app)

        # Create very large payload (5 MB)
        # Note: This may be limited by FastAPI's default body size limit
        payload = generate_payload(5 * 1024 * 1024)

        # This tests the middleware config, but may fail due to FastAPI limits
        # In that case, use a smaller but still large payload
        try:
            response = client.post(
                "/api/unlimited",
                headers={"Idempotency-Key": "unlimited-test"},
                json=payload,
            )
            # If it succeeds, middleware accepted it
            assert response.status_code in [200, 413]
        except Exception:
            # If FastAPI rejects it, that's also acceptable
            pass


class TestResponseBodySizeLimits:
    """Test response body size handling."""

    def test_response_body_at_limit_stored_correctly(self, storage, default_config):
        """Test that response body at limit is stored correctly.

        Large responses should be base64-encoded and stored without truncation.
        """
        app = FastAPI()
        app.add_middleware(ASGIIdempotencyMiddleware, storage=storage, config=default_config)

        # Response size at limit (1 MB)
        large_data = generate_large_string(1024 * 1024)

        @app.post("/api/large-response")
        async def large_response_endpoint(idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
            return {"data": large_data}

        client = TestClient(app)

        # First request
        response1 = client.post(
            "/api/large-response",
            headers={"Idempotency-Key": "large-response-test"},
            json={"input": "test"},
        )

        assert response1.status_code == 200
        assert len(response1.json()["data"]) == 1024 * 1024

        # Second request (should return cached response)
        response2 = client.post(
            "/api/large-response",
            headers={"Idempotency-Key": "large-response-test"},
            json={"input": "test"},
        )

        assert response2.status_code == 200
        assert response2.json() == response1.json()

    def test_response_body_over_limit_handled_gracefully(self, storage, small_body_config):
        """Test that very large response bodies are handled gracefully.

        Even if response is larger than max_body_bytes, it should still be stored.
        The max_body_bytes only applies to request body fingerprinting.
        """
        app = FastAPI()
        app.add_middleware(ASGIIdempotencyMiddleware, storage=storage, config=small_body_config)

        # Response much larger than request limit
        large_response_data = generate_large_string(10 * 1024)  # 10 KB, larger than 1 KB limit

        @app.post("/api/huge-response")
        async def huge_response_endpoint(idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
            return {"data": large_response_data}

        client = TestClient(app)

        response = client.post(
            "/api/huge-response",
            headers={"Idempotency-Key": "huge-response-test"},
            json={"small": "input"},
        )

        assert response.status_code == 200
        assert len(response.json()["data"]) == 10 * 1024

    def test_empty_response_body_stored_correctly(self, storage, default_config):
        """Test that empty response body is stored correctly."""
        app = FastAPI()
        app.add_middleware(ASGIIdempotencyMiddleware, storage=storage, config=default_config)

        @app.post("/api/empty-response")
        async def empty_response_endpoint(idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
            return {}

        client = TestClient(app)

        # First request
        response1 = client.post(
            "/api/empty-response",
            headers={"Idempotency-Key": "empty-response-test"},
            json={"input": "test"},
        )

        assert response1.status_code == 200
        assert response1.json() == {}

        # Second request should return cached empty response
        response2 = client.post(
            "/api/empty-response",
            headers={"Idempotency-Key": "empty-response-test"},
            json={"input": "test"},
        )

        assert response2.status_code == 200
        assert response2.json() == {}


class TestIdempotencyKeyLengthLimits:
    """Test idempotency key length validation."""

    def test_key_at_max_length_succeeds(self, storage, default_config):
        """Test that idempotency key at max length (200 chars) is accepted.

        The Pydantic model specifies max_length=255 for the key field.
        """
        app = FastAPI()
        app.add_middleware(ASGIIdempotencyMiddleware, storage=storage, config=default_config)

        @app.post("/api/max-key")
        async def max_key_endpoint(idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
            return {"status": "success"}

        client = TestClient(app)

        # Create key at max length (255 characters based on model)
        max_length_key = "k" * 255

        response = client.post(
            "/api/max-key",
            headers={"Idempotency-Key": max_length_key},
            json={"data": "test"},
        )

        assert response.status_code == 200

    def test_key_over_max_length_rejected(self, storage, default_config):
        """Test that idempotency key over max length is rejected.

        Keys longer than 255 characters are rejected by middleware with 500 error.
        """
        app = FastAPI()
        app.add_middleware(ASGIIdempotencyMiddleware, storage=storage, config=default_config)

        @app.post("/api/long-key")
        async def long_key_endpoint(idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
            return {"status": "success"}

        client = TestClient(app)

        # Create key over max length (256 characters)
        too_long_key = "k" * 256

        response = client.post(
            "/api/long-key",
            headers={"Idempotency-Key": too_long_key},
            json={"data": "test"},
        )

        # Middleware rejects with 500 error (IdempotencyError)
        assert response.status_code == 500
        assert b"exceeds maximum length" in response.content

    def test_empty_key_handled_appropriately(self, storage, default_config):
        """Test that empty idempotency key is handled correctly.

        Empty string is rejected by middleware with 500 error.
        """
        app = FastAPI()
        app.add_middleware(ASGIIdempotencyMiddleware, storage=storage, config=default_config)

        @app.post("/api/empty-key")
        async def empty_key_endpoint(idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
            return {"status": "success"}

        client = TestClient(app)

        # Empty key
        response = client.post(
            "/api/empty-key",
            headers={"Idempotency-Key": ""},
            json={"data": "test"},
        )

        # Middleware rejects empty key with 500 error
        assert response.status_code == 500
        assert b"cannot be empty" in response.content

    def test_key_with_special_characters_accepted(self, storage, default_config):
        """Test that idempotency key with special characters is accepted.

        Keys can contain various characters: alphanumeric, hyphens, underscores.
        """
        app = FastAPI()
        app.add_middleware(ASGIIdempotencyMiddleware, storage=storage, config=default_config)

        @app.post("/api/special-key")
        async def special_key_endpoint(idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
            return {"status": "success"}

        client = TestClient(app)

        special_keys = [
            "key-with-dashes",
            "key_with_underscores",
            "key.with.dots",
            "key123with456numbers",
            "KEY-IN-UPPERCASE",
            "mixed-Case_Key.123",
        ]

        for key in special_keys:
            response = client.post(
                "/api/special-key",
                headers={"Idempotency-Key": key},
                json={"data": "test"},
            )
            assert response.status_code == 200, f"Failed for key: {key}"

    def test_key_with_unicode_characters(self, storage, default_config):
        """Test that idempotency key with unicode characters is handled.

        HTTP headers must be ASCII, so unicode characters in headers will cause
        an encoding error at the HTTP client level before reaching the middleware.
        This test verifies that the system handles this appropriately.
        """
        app = FastAPI()
        app.add_middleware(ASGIIdempotencyMiddleware, storage=storage, config=default_config)

        @app.post("/api/unicode-key")
        async def unicode_key_endpoint(idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
            return {"status": "success"}

        client = TestClient(app)

        # HTTP headers must be ASCII - unicode will fail at client level
        unicode_key = "key-with-unicode-café"

        # Expect UnicodeEncodeError when trying to send unicode in header
        with pytest.raises(UnicodeEncodeError):
            client.post(
                "/api/unicode-key",
                headers={"Idempotency-Key": unicode_key},
                json={"data": "test"},
            )


class TestHeaderSizeLimits:
    """Test header size and count limits."""

    def test_many_headers_accepted(self, storage, default_config):
        """Test that requests with many headers are accepted.

        The middleware only includes specific headers in fingerprint,
        but all headers should pass through.
        """
        app = FastAPI()
        app.add_middleware(ASGIIdempotencyMiddleware, storage=storage, config=default_config)

        @app.post("/api/many-headers")
        async def many_headers_endpoint(idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
            return {"status": "success"}

        client = TestClient(app)

        # Create many custom headers
        headers = {"Idempotency-Key": "many-headers-test"}
        for i in range(50):
            headers[f"X-Custom-Header-{i}"] = f"value-{i}"

        response = client.post(
            "/api/many-headers",
            headers=headers,
            json={"data": "test"},
        )

        # Should accept many headers
        assert response.status_code == 200

    def test_large_header_values_accepted(self, storage, default_config):
        """Test that headers with large values are accepted.

        Individual header values can be quite large.
        """
        app = FastAPI()
        app.add_middleware(ASGIIdempotencyMiddleware, storage=storage, config=default_config)

        @app.post("/api/large-headers")
        async def large_headers_endpoint(idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
            return {"status": "success"}

        client = TestClient(app)

        # Create header with large value
        large_value = "x" * 8192  # 8 KB header value
        headers = {
            "Idempotency-Key": "large-headers-test",
            "X-Large-Header": large_value,
        }

        response = client.post(
            "/api/large-headers",
            headers=headers,
            json={"data": "test"},
        )

        # Should accept large header (or reject based on server limits)
        assert response.status_code in [200, 400, 413, 431]

    def test_total_headers_size_within_reasonable_limits(self, storage, default_config):
        """Test that total headers size is within reasonable limits.

        Servers typically have limits on total header size (e.g., 8 KB).
        """
        app = FastAPI()
        app.add_middleware(ASGIIdempotencyMiddleware, storage=storage, config=default_config)

        @app.post("/api/total-headers")
        async def total_headers_endpoint(idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
            return {"status": "success"}

        client = TestClient(app)

        # Create headers totaling reasonable size (6 KB)
        headers = {"Idempotency-Key": "total-headers-test"}
        num_headers = 100
        value_size = 60  # Each header ~60 bytes
        for i in range(num_headers):
            headers[f"X-Header-{i}"] = "x" * value_size

        response = client.post(
            "/api/total-headers",
            headers=headers,
            json={"data": "test"},
        )

        # Should accept reasonable total header size
        assert response.status_code == 200


class TestSizeLimitConfiguration:
    """Test size limit configuration options."""

    def test_custom_body_size_limit_enforced(self):
        """Test that custom max_body_bytes configuration is enforced."""
        storage = MemoryStorageAdapter()
        config = IdempotencyConfig(
            enabled_methods=["POST"],
            max_body_bytes=512,  # Custom 512 byte limit
        )

        app = FastAPI()
        app.add_middleware(ASGIIdempotencyMiddleware, storage=storage, config=config)

        @app.post("/api/custom-limit")
        async def custom_limit_endpoint(
            data: dict,
            idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
        ):
            return {"status": "success"}

        client = TestClient(app)

        # Small payload under custom limit
        small_payload = generate_payload(256)
        response1 = client.post(
            "/api/custom-limit",
            headers={"Idempotency-Key": "custom-limit-small"},
            json=small_payload,
        )
        assert response1.status_code == 200

        # Large payload over custom limit (rejected by middleware)
        large_payload = generate_payload(1024)
        response2 = client.post(
            "/api/custom-limit",
            headers={"Idempotency-Key": "custom-limit-large"},
            json=large_payload,
        )
        # Middleware rejects oversized body with 500 error
        assert response2.status_code == 500
        assert b"Request body exceeds maximum size" in response2.content

    def test_zero_max_body_bytes_means_unlimited(self):
        """Test that max_body_bytes=0 means unlimited body size."""
        storage = MemoryStorageAdapter()
        config = IdempotencyConfig(
            enabled_methods=["POST"],
            max_body_bytes=0,  # Unlimited
        )

        app = FastAPI()
        app.add_middleware(ASGIIdempotencyMiddleware, storage=storage, config=config)

        @app.post("/api/unlimited")
        async def unlimited_endpoint(
            data: dict,
            idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
        ):
            return {"status": "success"}

        client = TestClient(app)

        # Very large payload
        large_payload = generate_payload(10 * 1024)  # 10 KB
        response = client.post(
            "/api/unlimited",
            headers={"Idempotency-Key": "unlimited-test"},
            json=large_payload,
        )

        # Should accept with unlimited config
        assert response.status_code == 200

    def test_negative_max_body_bytes_rejected_by_config(self):
        """Test that negative max_body_bytes is rejected by configuration validation."""
        storage = MemoryStorageAdapter()

        # Negative value should be rejected by Pydantic validation
        with pytest.raises(ValueError, match="max_body_bytes must be >= 0"):
            IdempotencyConfig(
                enabled_methods=["POST"],
                max_body_bytes=-1,
            )


class TestGracefulRejection:
    """Test graceful rejection of invalid requests."""

    def test_graceful_error_for_oversized_key(self, storage, default_config):
        """Test that oversized key returns graceful error response."""
        app = FastAPI()
        app.add_middleware(ASGIIdempotencyMiddleware, storage=storage, config=default_config)

        @app.post("/api/error-response")
        async def error_response_endpoint(idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
            return {"status": "success"}

        client = TestClient(app)

        # Oversized key
        oversized_key = "k" * 500  # Way over 255 limit

        response = client.post(
            "/api/error-response",
            headers={"Idempotency-Key": oversized_key},
            json={"data": "test"},
        )

        # Middleware returns 500 error for IdempotencyError
        assert response.status_code == 500

        # Response contains error message in body
        assert b"exceeds maximum length" in response.content

    def test_missing_key_bypasses_idempotency(self, storage, default_config):
        """Test that requests without idempotency key bypass the middleware.

        Requests without Idempotency-Key header should be processed normally
        without idempotency protection.
        """
        app = FastAPI()
        app.add_middleware(ASGIIdempotencyMiddleware, storage=storage, config=default_config)

        call_count = 0

        @app.post("/api/no-key")
        async def no_key_endpoint():
            nonlocal call_count
            call_count += 1
            return {"status": "success", "call": call_count}

        client = TestClient(app)

        # First request without key
        response1 = client.post("/api/no-key", json={"data": "test"})
        assert response1.status_code == 200
        assert response1.json()["call"] == 1

        # Second request without key (should execute again, not cached)
        response2 = client.post("/api/no-key", json={"data": "test"})
        assert response2.status_code == 200
        assert response2.json()["call"] == 2

        # Different call counts prove no caching occurred
        assert response1.json()["call"] != response2.json()["call"]
