"""Storage adapters for idempotency middleware.

This package provides storage backend implementations for persisting
idempotency records. All adapters implement the StorageAdapter protocol
defined in base.py.

Available Adapters:
    - MemoryStorageAdapter: In-memory storage with asyncio concurrency
    - (Future) FileStorageAdapter: File-based JSON storage
    - (Future) RedisStorageAdapter: Redis-based distributed storage
"""

from idempotent_middleware.storage.base import StorageAdapter
from idempotent_middleware.storage.memory import MemoryStorageAdapter

__all__ = [
    "StorageAdapter",
    "MemoryStorageAdapter",
]
