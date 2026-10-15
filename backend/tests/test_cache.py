"""进程内缓存的单元测试。

缓存直接关系到 API 配额消耗：命中失效会导致重复扣费，
因此这里重点验证 TTL 过期与 LRU 淘汰两种行为。
"""

import time

from app.utils.cache import TTLCache


def test_get_returns_stored_value():
    cache = TTLCache(max_size=4, ttl_seconds=10)
    cache.set("key", "value")
    assert cache.get("key") == "value"


def test_get_missing_key_returns_none():
    cache = TTLCache(max_size=4, ttl_seconds=10)
    assert cache.get("absent") is None


def test_expired_entry_is_not_returned():
    cache = TTLCache(max_size=4, ttl_seconds=0.05)
    cache.set("key", "value")

    time.sleep(0.12)

    assert cache.get("key") is None


def test_lru_evicts_least_recently_used():
    cache = TTLCache(max_size=2, ttl_seconds=10)
    cache.set("a", 1)
    cache.set("b", 2)

    # 访问 a，使其成为「最近使用」，于是 b 成为淘汰候选
    cache.get("a")
    cache.set("c", 3)

    assert cache.get("a") == 1
    assert cache.get("b") is None
    assert cache.get("c") == 3


def test_clear_empties_cache():
    cache = TTLCache(max_size=4, ttl_seconds=10)
    cache.set("a", 1)
    cache.set("b", 2)

    assert len(cache) == 2

    cache.clear()

    assert len(cache) == 0


def test_max_size_is_respected():
    cache = TTLCache(max_size=3, ttl_seconds=10)
    for i in range(10):
        cache.set(f"k{i}", i)

    assert len(cache) == 3
