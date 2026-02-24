"""Tests for core/cache.py"""
import asyncio
import pytest
from duckduckgo_search_mcp.core.cache import _LRUCache, make_cache_key, ResearchCache


@pytest.mark.asyncio
async def test_lru_set_get():
    cache = _LRUCache(max_size=10, ttl=60)
    await cache.set("key1", {"data": "value1"})
    result = await cache.get("key1")
    assert result == {"data": "value1"}


@pytest.mark.asyncio
async def test_lru_miss():
    cache = _LRUCache(max_size=10, ttl=60)
    result = await cache.get("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_lru_eviction():
    cache = _LRUCache(max_size=3, ttl=60)
    for i in range(4):
        await cache.set(f"key{i}", i)
    # key0 should have been evicted (LRU)
    assert await cache.get("key0") is None
    assert await cache.get("key3") == 3


@pytest.mark.asyncio
async def test_lru_ttl_expiry():
    cache = _LRUCache(max_size=10, ttl=0)  # TTL=0 means immediately expired
    await cache.set("key1", "value1")
    # Manually expire by setting past time
    import time
    cache._store["key1"] = ("value1", time.monotonic() - 1)
    result = await cache.get("key1")
    assert result is None


@pytest.mark.asyncio
async def test_lru_delete():
    cache = _LRUCache(max_size=10, ttl=60)
    await cache.set("key1", "value1")
    await cache.delete("key1")
    assert await cache.get("key1") is None


@pytest.mark.asyncio
async def test_lru_clear():
    cache = _LRUCache(max_size=10, ttl=60)
    await cache.set("key1", "v1")
    await cache.set("key2", "v2")
    await cache.clear()
    assert cache.size == 0


def test_cache_key_stable():
    key1 = make_cache_key("python tips", search_results=50, fetch_count=0)
    key2 = make_cache_key("python tips", fetch_count=0, search_results=50)
    assert key1 == key2  # order of kwargs shouldn't matter


def test_cache_key_different_queries():
    key1 = make_cache_key("python tips")
    key2 = make_cache_key("javascript tips")
    assert key1 != key2


@pytest.mark.asyncio
async def test_research_cache_memory_only():
    """ResearchCache uses in-memory LRU."""
    rc = ResearchCache()
    assert rc.memory_size == 0
    await rc.set("k", {"result": 42})
    assert await rc.get("k") == {"result": 42}
    assert rc.memory_size == 1
    await rc.clear()
    assert await rc.get("k") is None
    assert rc.memory_size == 0
