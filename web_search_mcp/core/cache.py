"""
core/cache.py

Two-tier cache for research results:

  Tier 1 — In-memory LRU (always available, resets on process restart)
  Tier 2 — Redis (optional, persists across restarts; enabled via env vars)

Cache key: sha256(query + canonical params)
TTL: configurable, default 1 hour for in-memory, 6 hours for Redis.

Environment variables:
  REDIS_URL        Redis connection URL (e.g. redis://localhost:6379/0)
                   If absent, Redis tier is disabled.
  CACHE_TTL_MEM    In-memory TTL in seconds  (default: 3600)
  CACHE_TTL_REDIS  Redis TTL in seconds       (default: 21600)
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

REDIS_URL       = os.getenv("REDIS_URL", "")
CACHE_TTL_MEM   = int(os.getenv("CACHE_TTL_MEM",   "3600"))
CACHE_TTL_REDIS = int(os.getenv("CACHE_TTL_REDIS", "21600"))
CACHE_MAX_SIZE  = int(os.getenv("CACHE_MAX_SIZE",  "128"))


# ---------------------------------------------------------------------------
# Cache key builder
# ---------------------------------------------------------------------------

def make_cache_key(query: str, **params: Any) -> str:
    """Return a stable hex key for (query, params)."""
    payload = json.dumps({"query": query, **params}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Tier 1: In-memory LRU
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
# Tier 2: Redis (optional)
# ---------------------------------------------------------------------------

class _RedisCache:
    def __init__(self, url: str, ttl: int) -> None:
        self._url = url
        self._ttl = ttl
        self._client: Any = None

    async def _get_client(self) -> Any:
        if self._client is None:
            try:
                import redis.asyncio as aioredis  # type: ignore
                self._client = aioredis.from_url(self._url, decode_responses=True)
                await self._client.ping()
                logger.info("Redis cache connected: %s", self._url)
            except Exception as exc:
                logger.warning("Redis unavailable (%s) — using memory cache only", exc)
                self._client = None
        return self._client

    async def get(self, key: str) -> Optional[Any]:
        client = await self._get_client()
        if client is None:
            return None
        try:
            raw = await client.get(f"wsmcp:{key}")
            return json.loads(raw) if raw else None
        except Exception as exc:
            logger.debug("Redis GET error: %s", exc)
            return None

    async def set(self, key: str, value: Any) -> None:
        client = await self._get_client()
        if client is None:
            return
        try:
            await client.setex(f"wsmcp:{key}", self._ttl, json.dumps(value))
        except Exception as exc:
            logger.debug("Redis SET error: %s", exc)

    async def delete(self, key: str) -> None:
        client = await self._get_client()
        if client is None:
            return
        try:
            await client.delete(f"wsmcp:{key}")
        except Exception as exc:
            logger.debug("Redis DELETE error: %s", exc)

    async def clear(self) -> None:
        client = await self._get_client()
        if client is None:
            return
        try:
            keys = await client.keys("wsmcp:*")
            if keys:
                await client.delete(*keys)
        except Exception as exc:
            logger.debug("Redis CLEAR error: %s", exc)


# ---------------------------------------------------------------------------
# Unified cache facade
# ---------------------------------------------------------------------------

class ResearchCache:
    """
    Unified two-tier cache.

    Read order:  memory → Redis → miss
    Write order: memory + Redis (if available)
    """

    def __init__(self) -> None:
        self._mem   = _LRUCache(CACHE_MAX_SIZE, CACHE_TTL_MEM)
        self._redis = _RedisCache(REDIS_URL, CACHE_TTL_REDIS) if REDIS_URL else None

    async def get(self, key: str) -> Optional[Any]:
        value = await self._mem.get(key)
        if value is not None:
            logger.debug("Cache HIT (memory): %s", key[:16])
            return value
        if self._redis:
            value = await self._redis.get(key)
            if value is not None:
                logger.debug("Cache HIT (redis): %s", key[:16])
                # Backfill memory tier
                await self._mem.set(key, value)
                return value
        logger.debug("Cache MISS: %s", key[:16])
        return None

    async def set(self, key: str, value: Any) -> None:
        await self._mem.set(key, value)
        if self._redis:
            await self._redis.set(key, value)

    async def delete(self, key: str) -> None:
        await self._mem.delete(key)
        if self._redis:
            await self._redis.delete(key)

    async def clear(self) -> None:
        await self._mem.clear()
        if self._redis:
            await self._redis.clear()

    @property
    def memory_size(self) -> int:
        return self._mem.size

    @property
    def redis_enabled(self) -> bool:
        return self._redis is not None


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_cache: Optional[ResearchCache] = None


def get_cache() -> ResearchCache:
    global _cache
    if _cache is None:
        _cache = ResearchCache()
    return _cache
