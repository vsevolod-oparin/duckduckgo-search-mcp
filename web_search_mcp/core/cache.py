"""
core/cache.py

In-memory LRU cache for research results.

Cache key: sha256(query + canonical params)
TTL: configurable, default 1 hour.

Environment variables:
  CACHE_TTL_MEM    In-memory TTL in seconds  (default: 3600)
  CACHE_MAX_SIZE   Max in-memory entries      (default: 128)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from collections import OrderedDict
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------

CACHE_TTL_MEM  = int(os.getenv("CACHE_TTL_MEM",  "3600"))
CACHE_MAX_SIZE = int(os.getenv("CACHE_MAX_SIZE", "128"))


# ---------------------------------------------------------------------------
# Cache key builder
# ---------------------------------------------------------------------------

def make_cache_key(query: str, **params: Any) -> str:
    """Return a stable hex key for (query, params)."""
    payload = json.dumps({"query": query, **params}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


# ---------------------------------------------------------------------------
# In-memory LRU cache
# ---------------------------------------------------------------------------

class _LRUCache:
    """Thread-safe LRU cache with per-entry TTL."""

    def __init__(self, max_size: int, ttl: int) -> None:
        self._max_size = max_size
        self._ttl = ttl
        self._store: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            if key not in self._store:
                return None
            value, expires_at = self._store[key]
            if time.monotonic() > expires_at:
                del self._store[key]
                return None
            # Move to end (most recently used)
            self._store.move_to_end(key)
            return value

    async def set(self, key: str, value: Any) -> None:
        async with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = (value, time.monotonic() + self._ttl)
            if len(self._store) > self._max_size:
                self._store.popitem(last=False)  # evict oldest

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()

    @property
    def size(self) -> int:
        return len(self._store)


# ---------------------------------------------------------------------------
# Unified cache facade
# ---------------------------------------------------------------------------

class ResearchCache:
    """In-memory LRU cache for research results."""

    def __init__(self) -> None:
        self._mem = _LRUCache(CACHE_MAX_SIZE, CACHE_TTL_MEM)

    async def get(self, key: str) -> Optional[Any]:
        value = await self._mem.get(key)
        if value is not None:
            logger.debug("Cache HIT: %s", key[:16])
        else:
            logger.debug("Cache MISS: %s", key[:16])
        return value

    async def set(self, key: str, value: Any) -> None:
        await self._mem.set(key, value)

    async def delete(self, key: str) -> None:
        await self._mem.delete(key)

    async def clear(self) -> None:
        await self._mem.clear()

    @property
    def memory_size(self) -> int:
        return self._mem.size


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_cache: Optional[ResearchCache] = None


def get_cache() -> ResearchCache:
    global _cache
    if _cache is None:
        _cache = ResearchCache()
    return _cache

