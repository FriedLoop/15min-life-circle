"""POI 检索服务。

检索策略：**按类别分别检索**，而非一次性并集检索。

为什么放弃并集检索：
    百度圆形区域检索支持用 $ 分隔多关键字（最多 10 个），看似一次就能拿到全部类别。
    但实测（莞城老城区，2026-09）发现致命问题：
    接口只返回前 20 条，且按综合相关性排序而非按类别均衡。
    1000m 内各类设施共 104 个，返回的 20 条里 **18 条都是药店**，
    菜市场、小学等类别被直接挤掉。若据此统计覆盖率，
    报告会得出「小学 0 个」这类严重失真的结论。

    改为逐类检索后，每次请求的结果都属于目标类别，统计口径才准确。

配额控制（地点检索日配额仅 100 次，是本项目最紧的资源）：
    1. 结果缓存：坐标量化到 50m，重复查询不消耗配额
    2. 按需检索：调用方可只指定关心的类别（调试时只查 3 类）
    3. 温和降级：个别类别失败不影响其余类别
"""

import asyncio

from app.core import constants
from app.core.config import settings
from app.schemas.models import PoiItem, PoiSearchResponse
from app.services.baidu_client import baidu_client
from app.utils.cache import poi_cache
from app.utils.geo import haversine_distance, quantize_coord


def classify_poi(name: str, tag: str = "") -> str:
    """把 POI 归一化到民生设施类别。

    逐类检索时结果已属于目标类别，此函数主要用于并集检索场景
    或对检索结果做二次校验。匹配顺序即 FACILITY_CATEGORIES 的定义顺序，
    越具体的类别排得越靠前（如「小学」先于「药店」），避免误判。
    """
    text = f"{name or ''}{tag or ''}"
    for category, keywords in constants.FACILITY_CATEGORIES.items():
        if any(keyword in text for keyword in keywords):
            return category
    return "其他"


def _category_query(category: str) -> str:
    """拼出某类别的检索关键词（多关键词用 $ 取并集）。"""
    keywords = constants.FACILITY_CATEGORIES.get(category)
    if not keywords:
        return category
    return "$".join(keywords)


def _extract(
    item: dict,
    center_lng: float,
    center_lat: float,
    radius: int,
    category: str | None = None,
) -> PoiItem | None:
    """把百度返回的原始 POI 转成内部结构，并剔除超出半径的结果。"""
    location = item.get("location") or {}
    lng = location.get("lng")
    lat = location.get("lat")
    if lng is None or lat is None:
        return None

    name = item.get("name") or ""
    tag = (item.get("detail_info") or {}).get("tag", "")

    distance = haversine_distance(center_lng, center_lat, lng, lat)
    # 圆形检索偶尔会返回略超出半径的结果，统一裁掉，保证统计口径一致
    if distance > radius:
        return None

    return PoiItem(
        name=name,
        address=item.get("address") or "",
        lng=lng,
        lat=lat,
        type=tag,
        # 逐类检索时已明确类别，无需再猜；否则按关键词归类
        category=category or classify_poi(name, tag),
        distance_m=round(distance, 1),
    )


async def search_category(
    lng: float,
    lat: float,
    category: str,
    radius: int | None = None,
    max_pages: int | None = None,
) -> list[PoiItem]:
    """检索单个类别的设施（结果带缓存）。

    Args:
        lng / lat: 中心点（BD09）
        category: 目标类别，如「菜市场」
        radius: 检索半径（米），默认取配置 POI_SEARCH_RADIUS_M
        max_pages: 最大翻页数，默认取常量 POI_MAX_PAGES

    Returns:
        该类别的 POI 列表，按到中心点的直线距离由近到远排序。
    """
    radius = radius or settings.POI_SEARCH_RADIUS_M
    max_pages = max_pages or constants.POI_MAX_PAGES

    # 缓存键：坐标量化到 50m，避免轻微拖动导致重复消耗配额
    q_lng, q_lat = quantize_coord(lng, lat, settings.CACHE_COORD_PRECISION_M)
    cache_key = (q_lng, q_lat, radius, category, max_pages)
    if settings.CACHE_ENABLED:
        hit = poi_cache.get(cache_key)
        if hit is not None:
            return hit

    raw_items: list[dict] = []
    for page in range(max_pages):
        data = await baidu_client.get(
            "/place/v2/search",
            {
                "query": _category_query(category),
                "location": f"{lat},{lng}",
                "radius": radius,
                "scope": 2,  # 返回 detail_info 才拿得到 tag
                "page_size": constants.POI_PAGE_SIZE,
                "page_num": page,
            },
        )

        items = data.get("results") or []
        raw_items.extend(items)

        # 不足一页说明已取完，停止翻页以节省配额
        if len(items) < constants.POI_PAGE_SIZE:
            break
        if len(raw_items) >= (data.get("total") or 0):
            break

    pois: list[PoiItem] = []
    for item in raw_items:
        parsed = _extract(item, lng, lat, radius, category=category)
        if parsed is not None:
            pois.append(parsed)

    pois.sort(key=lambda p: p.distance_m or 0.0)

    if settings.CACHE_ENABLED:
        poi_cache.set(cache_key, pois)

    return pois


async def search_all_categories(
    lng: float,
    lat: float,
    categories: list[str] | None = None,
    radius: int | None = None,
) -> tuple[dict[str, list[PoiItem]], list[str]]:
    """按类别分别检索。

    各类别并发请求（baidu_client 内部按并发上限限流）。
    单个类别失败不会中断整体流程，但**必须把失败类别上报**。

    为什么必须上报：
        失败若被当成空列表，下游盲区判定会得出「该区域完全没有此类设施」，
        进而把全部点判为盲区——一个基于失败请求的错误结论，看上去却像真实数据。
        这类静默失败比直接报错危险得多。

    Returns:
        (类别 → POI 列表, 检索失败的类别列表)

    Raises:
        BaiduApiError: 全部类别都失败（通常是配额耗尽或 AK 失效）。
    """
    targets = categories or list(constants.FACILITY_CATEGORIES.keys())

    outcomes = await asyncio.gather(
        *[search_category(lng, lat, cat, radius) for cat in targets],
        return_exceptions=True,
    )

    result: dict[str, list[PoiItem]] = {}
    failed: list[str] = []
    errors: list[Exception] = []

    for category, outcome in zip(targets, outcomes, strict=False):
        if isinstance(outcome, Exception):
            errors.append(outcome)
            failed.append(category)
            result[category] = []
        else:
            result[category] = outcome

    if len(errors) == len(targets) and errors:
        raise errors[0]

    return result, failed


async def search_nearby(
    lng: float,
    lat: float,
    radius: int | None = None,
    categories: list[str] | None = None,
) -> PoiSearchResponse:
    """检索中心点周边的民生设施（对外接口，按类别分别检索）。

    Args:
        lng / lat: 中心点（BD09）
        radius: 检索半径（米）；为空取配置 POI_SEARCH_RADIUS_M
        categories: 只检索指定类别；为空表示全部
    """
    radius = radius or settings.POI_SEARCH_RADIUS_M
    by_category, _failed = await search_all_categories(lng, lat, categories, radius)

    pois: list[PoiItem] = []
    counts: dict[str, int] = {}
    for category, items in by_category.items():
        pois.extend(items)
        counts[category] = len(items)

    pois.sort(key=lambda p: p.distance_m or 0.0)

    return PoiSearchResponse(
        center={"lng": lng, "lat": lat},
        radius=radius,
        total=len(pois),
        poi_list=pois,
        category_counts=counts,
    )
