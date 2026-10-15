"""进程内结果缓存。

为什么需要：
    批量算路日配额 5000 条，单次等时圈分析的算路条数约等于网格点数
    （默认 150m 间隔为 197 条；200m 间隔为 113 条）。
    开发调试反复调用、前端连续点击、评审反复演示，
    都可能在几分钟内把当天配额烧光，之后所有接口直接不可用。

设计取舍：
    用进程内内存缓存而非 Redis——本项目单实例部署即可满足需求，
    引入 Redis 会增加评审的部署负担，与「一键跑通」的目标冲突。
    代价是重启即失效，对本项目可接受。

双重约束：
    TTL  防止结果长期失真（路网数据会变化）
    LRU  防止内存无界增长
"""

import time
from collections import OrderedDict
from typing import Any, Hashable

from app.core.config import settings


class TTLCache:
    """带过期时间与容量上限的进程内缓存。"""

    def __init__(self, max_size: int = 64, ttl_seconds: float = 3600.0) -> None:
        self._max_size = max(1, max_size)
        self._ttl = ttl_seconds
        self._store: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()

    def get(self, key: Hashable) -> Any | None:
        """读取缓存，不存在或已过期返回 None。"""
        item = self._store.get(key)
        if item is None:
            return None

        expire_at, value = item
        if time.monotonic() >= expire_at:
            del self._store[key]
            return None

        # 命中后移到末尾，维持「最近使用」顺序
        self._store.move_to_end(key)
        return value

    def set(self, key: Hashable, value: Any) -> None:
        """写入缓存，超出容量时淘汰最久未使用的条目。"""
        self._store[key] = (time.monotonic() + self._ttl, value)
        self._store.move_to_end(key)

        while len(self._store) > self._max_size:
            self._store.popitem(last=False)

    def clear(self) -> None:
        """清空缓存。"""
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


# 等时圈结果缓存。坐标相近（默认 50m 内）视为同一位置，避免拖动地图产生大量近似键
isochrone_cache = TTLCache(
    max_size=settings.CACHE_MAX_SIZE,
    ttl_seconds=settings.CACHE_TTL_SECONDS,
)

# POI 检索缓存：日配额仅 100 次，是本项目最紧的资源，必须缓存。
# 容量给得更大，因为单次分析就要查 10 个类别
poi_cache = TTLCache(
    max_size=settings.CACHE_MAX_SIZE * 4,
    ttl_seconds=settings.CACHE_TTL_SECONDS,
)

# 盲区与体检报告缓存：它们由等时圈和 POI 组合而成，开销更大
analysis_cache = TTLCache(
    max_size=settings.CACHE_MAX_SIZE,
    ttl_seconds=settings.CACHE_TTL_SECONDS,
)
