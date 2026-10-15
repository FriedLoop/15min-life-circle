"""15 分钟生活圈体检报告服务。

把三块分析结果聚合成一份「体检报告」：
    等时圈（能走到哪）  →  设施覆盖（有什么）  →  盲区（缺什么）

健康度评分：
    对每个类别统计「可达点中该类可及」的比例作为覆盖率（0~1），
    再按权重加权平均后换算成百分制。
    赛题明确点名的三类（菜市场、药店、小学）权重更高，
    因为它们是盲区判定的硬性指标。

配额说明：
    一份完整报告 = 等时圈算路 + 逐类 POI 检索 + 灰色地带精算 + 1 次逆地理编码。
    结果整体缓存；且复用等时圈结果传给盲区模块，避免重复算路。
"""

from app.core import constants
from app.core.config import settings
from app.schemas.models import PoiItem, ReportResponse
from app.services.blindspot import compute_blindspot
from app.services.geocoding import reverse_geocode
from app.services.isochrone import compute_isochrone
from app.services.poi import search_all_categories
from app.utils.cache import analysis_cache
from app.utils.geo import haversine_distance, quantize_coord


def _category_weight(category: str) -> float:
    """赛题重点关注的类别给更高权重。"""
    if category in constants.BLINDSPOT_CATEGORIES:
        return settings.CATEGORY_WEIGHT_KEY
    return settings.CATEGORY_WEIGHT_NORMAL


def compute_health_score(
    coverage: dict[str, float],
) -> tuple[float, dict[str, float]]:
    """按覆盖率加权计算健康度评分（0~100）。

    Returns:
        (综合得分, 各类别得分明细)
    """
    if not coverage:
        return 0.0, {}

    total_weight = sum(_category_weight(cat) for cat in coverage)
    if total_weight <= 0:
        return 0.0, {}

    weighted = sum(_category_weight(cat) * coverage[cat] for cat in coverage)
    score = 100.0 * weighted / total_weight

    detail = {cat: round(coverage[cat] * 100, 1) for cat in coverage}
    return round(score, 1), detail


def _pois_inside_isochrone(
    pois: list, reachable: list, tolerance_m: float
) -> list:
    """筛出落在等时圈（可达区域）内的设施。

    判定方式：设施到「最近可达点」的直线距离不超过半个网格间隔，
    即认为它落在可达区域覆盖范围内。零 API 成本。

    只回传圈内设施有两层考虑：
        1. 与「圈内设施」这一统计口径保持一致
        2. 检索半径是 2000m，若把范围内设施全部画到地图上，
           图标会铺满整屏、反而盖住热力图本身
    """
    if not reachable:
        return []

    result = []
    for poi in pois:
        nearest = min(
            haversine_distance(poi.lng, poi.lat, p.lng, p.lat) for p in reachable
        )
        if nearest <= tolerance_m:
            result.append(poi)

    return result


async def compute_report(
    lng: float,
    lat: float,
    walk_minutes: int | None = None,
    step_m: int | None = None,
    radius_m: int | None = None,
    categories: list[str] | None = None,
    with_address: bool = True,
) -> ReportResponse:
    """生成 15 分钟生活圈体检报告。

    Args:
        lng / lat: 中心点（BD09）
        walk_minutes: 生活圈时间阈值，默认 15
        step_m: 网格间隔（米）；越小边界越精细，算路调用量按平方增长
        radius_m: 网格覆盖半径（米）
        categories: 关注的设施类别；为空表示全部
        with_address: 是否调用逆地理编码获取地址（消耗 1 次配额）
    """
    minutes = walk_minutes or settings.WALK_MINUTES
    cats = categories or list(constants.FACILITY_CATEGORIES.keys())

    q_lng, q_lat = quantize_coord(lng, lat, settings.CACHE_COORD_PRECISION_M)
    # 网格参数须纳入缓存键，否则换精度后会命中旧精度的结果
    cache_key = (
        "report",
        q_lng,
        q_lat,
        tuple(cats),
        minutes,
        step_m,
        radius_m,
        with_address,
    )
    if settings.CACHE_ENABLED:
        hit = analysis_cache.get(cache_key)
        if hit is not None:
            return hit.model_copy(update={"cached": True})

    # 1. 等时圈
    isochrone = await compute_isochrone(
        lng, lat, walk_minutes=minutes, step_m=step_m, radius_m=radius_m
    )

    # 2. 盲区识别（复用等时圈，避免重复算路）
    blindspot = await compute_blindspot(
        lng,
        lat,
        categories=cats,
        walk_minutes=minutes,
        isochrone=isochrone,
    )

    # 3. 统计设施覆盖（POI 已缓存，不额外消耗配额）
    reachable = [p for p in isochrone.points if p.reachable]

    # 两个判定半径，用途不同：
    tolerance = max(isochrone.step_m / 2, 50.0)   # 「圈内设施」计数：半个网格间隔
    threshold = settings.BLINDSPOT_DISTANCE_M     # 地图标记与覆盖率：阈值(默认1km)

    pois_by_category, _failed_categories = await search_all_categories(lng, lat, cats)

    # 圈内设施：用于「圈内设施」这一计数统计，判定半径取半个网格间隔
    inside_by_category = {
        cat: _pois_inside_isochrone(pois, reachable, tolerance)
        for cat, pois in pois_by_category.items()
    }
    poi_counts = {cat: len(items) for cat, items in inside_by_category.items()}

    # 地图标记范围：以「最外层采样点为圆心、阈值(默认1km)为半径」所覆盖的设施。
    #
    # 为什么不能只标圈内设施：
    #     覆盖率的口径是「可达点 1km 内是否可及」，很多决定覆盖率的设施
    #     恰好落在等时圈外。若把它们全部隐藏，用户会看到「覆盖率 30%」
    #     却在地图上找不到任何相关设施，无从判断该数字是否可信。
    marked_by_category = {
        cat: _pois_inside_isochrone(pois, reachable, threshold)
        for cat, pois in pois_by_category.items()
    }
    all_pois: list[PoiItem] = [
        poi for items in marked_by_category.values() for poi in items
    ]

    # 4. 地址（失败不影响报告主体）
    address = ""
    if with_address:
        try:
            geo = await reverse_geocode(lng, lat)
            address = geo.formatted_address
        except Exception:
            address = ""

    # 5. 健康度评分
    score, detail = compute_health_score(blindspot.category_coverage)

    result = ReportResponse(
        center={"lng": lng, "lat": lat},
        address=address,
        walk_minutes=minutes,
        isochrone=isochrone,
        poi_counts=poi_counts,
        pois=all_pois,
        coverage=blindspot.category_coverage,
        blindspot=blindspot,
        health_score=score,
        score_detail=detail,
    )

    # 同 blindspot：降级结果与「存在检索失败」的结果都不缓存
    if (
        settings.CACHE_ENABLED
        and not isochrone.degraded
        and not blindspot.failed_categories
    ):
        analysis_cache.set(cache_key, result)

    return result
