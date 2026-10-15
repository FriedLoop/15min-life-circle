"""盲区识别服务。

判定语义：
    对「15 分钟等时圈内的每个可达点」，判断其周边
    threshold（默认 1000m）内能否找到指定的民生设施。
    若某类设施在阈值内不可及，该点在该类别上即属于服务盲区。

算法核心是「直线初筛」，避免对每个点、每个类别都做昂贵的路网算路：

    记 d = 该点到该类最近设施的直线距离
      ├─ 该类在检索范围内完全没有设施    → 必然盲区，免调算路
      ├─ d > threshold(1000m)           → 必然盲区（路网距离 ≥ 直线距离）
      ├─ d < threshold/绕行系数(625m)   → 必然非盲区（路网 ≤ d×1.6 < 1000m）
      └─ 其余（灰色地带 625~1000m）      → 调批量算路取真实路网距离

    前两类结论由几何性质保证成立，无需调用 API；
    按实测数据约八成判定可由初筛直接得出（松山湖 78.6%、莞城 81.3%），
    配额因此大幅降低。

注意：POI 检索半径必须显著大于等时圈半径（见 config.POI_SEARCH_RADIUS_M），
否则边缘点会因「远处明明有设施但没被检索到」而被误判为盲区。
"""

import asyncio

from app.core import constants
from app.core.config import settings
from app.schemas.models import (
    BlindSpotPoint,
    BlindSpotResponse,
    CategoryDistance,
    IsochroneResponse,
)
from app.services.isochrone import compute_isochrone
from app.services.poi import search_all_categories
from app.services.routematrix import walking_matrix
from app.utils.cache import analysis_cache
from app.utils.geo import haversine_distance, quantize_coord


def _category_weight(category: str) -> float:
    """赛题重点关注的类别权重更高。"""
    if category in constants.BLINDSPOT_CATEGORIES:
        return settings.CATEGORY_WEIGHT_KEY
    return settings.CATEGORY_WEIGHT_NORMAL


def _accessibility_score(
    row: dict[str, CategoryDistance],
    cats: list[str],
) -> float:
    """计算某一点的综合设施可达性得分（0~1）。

    语义：该点周边各类民生设施中，「阈值内可及」的类别占比（按权重加权）。
    热力图据此着色——这是「设施可达性」，不是「步行耗时」。

    **切勿改用距离线性衰减**：
        判定阈值本身就是 1000 m，一个距离 900 m 的设施按定义已经可及；
        若用 1 − d/1000 计分，它只得 0.1 分，
        于是即便覆盖率 100% 的区域也会被算成接近 0 而显示为红色，
        与「覆盖率高」这一事实自相矛盾（实测莞城即因此整片发红）。

    因此采用「可及即满分」口径：
        可及 → 1 分；不可及或区域内无此类设施 → 0 分
    """
    total_weight = 0.0
    accumulated = 0.0

    for cat in cats:
        weight = _category_weight(cat)
        if row[cat].covered:
            accumulated += weight
        total_weight += weight

    return accumulated / total_weight if total_weight else 0.0


def _nearest(
    pois: list, lng: float, lat: float, top_n: int
) -> list[tuple[object, float]]:
    """返回距 (lng, lat) 最近的 top_n 个 POI 及其直线距离。"""
    scored = [(poi, haversine_distance(lng, lat, poi.lng, poi.lat)) for poi in pois]
    scored.sort(key=lambda pair: pair[1])
    return scored[:top_n]


def _make_cache_key(
    lng: float,
    lat: float,
    categories: tuple[str, ...],
    judge_categories: tuple[str, ...],
    threshold: int,
    minutes: int,
) -> tuple:
    q_lng, q_lat = quantize_coord(lng, lat, settings.CACHE_COORD_PRECISION_M)
    return (q_lng, q_lat, categories, judge_categories, threshold, minutes)


async def compute_blindspot(
    lng: float,
    lat: float,
    categories: list[str] | None = None,
    blindspot_categories: list[str] | None = None,
    threshold_m: int | None = None,
    walk_minutes: int | None = None,
    isochrone: IsochroneResponse | None = None,
) -> BlindSpotResponse:
    """识别等时圈内的服务盲区。

    两个类别参数的分工：
        categories           检索并统计覆盖率的类别（默认全部 10 类）
        blindspot_categories 实际判定「是否盲区」的类别（默认赛题点名的三类）

    分开的原因：若用全部 10 类做判定，养老这类普遍稀缺的设施
    会让几乎所有点都命中「缺失」，盲区率被推向 100%，失去区分度。
    赛题原话是「1 公里内没有菜市场、药店或小学」，判定应只针对这三类。

    Args:
        lng / lat: 中心点（BD09）
        categories: 检索与统计的类别；为空表示全部
        blindspot_categories: 判定盲区的类别；为空表示赛题三类
        threshold_m: 判定阈值（米），默认 1000
        walk_minutes: 生活圈时间阈值，默认 15
        isochrone: 已算好的等时圈；传入可避免重复计算（报告聚合时用）

    Returns:
        盲区识别结果，含逐点判定与各类别覆盖率。
    """
    threshold = threshold_m or settings.BLINDSPOT_DISTANCE_M
    minutes = walk_minutes or settings.WALK_MINUTES

    cats = categories or list(constants.FACILITY_CATEGORIES.keys())
    judge_cats = blindspot_categories or list(constants.BLINDSPOT_CATEGORIES)

    # 判定类别必须落在检索范围内，否则查不到数据
    for cat in judge_cats:
        if cat not in cats:
            cats.append(cat)

    # 缓存
    cache_key = _make_cache_key(
        lng, lat, tuple(cats), tuple(judge_cats), threshold, minutes
    )
    if settings.CACHE_ENABLED and isochrone is None:
        hit = analysis_cache.get(cache_key)
        if hit is not None:
            return hit.model_copy(update={"cached": True})

    # 1. 等时圈（复用传入结果，避免报告流程重复消耗配额）
    if isochrone is None:
        isochrone = await compute_isochrone(lng, lat, walk_minutes=minutes)

    reachable = [p for p in isochrone.points if p.reachable]
    if not reachable:
        return BlindSpotResponse(
            center={"lng": lng, "lat": lat},
            categories=cats,
            judge_categories=judge_cats,
            threshold_m=threshold,
            total_points=0,
            blind_points=0,
            points=[],
            category_coverage={cat: 0.0 for cat in cats},
            category_counts={cat: 0 for cat in cats},
        )

    # 2. 按类别检索 POI（半径需覆盖「最远可达点 + 阈值」）
    #    失败的类别会被记录下来，避免被误当成「该区域没有此类设施」
    pois_by_category, failed_categories = await search_all_categories(lng, lat, cats)

    # 3. 直线初筛
    certain_safe = threshold / settings.DETOUR_FACTOR
    results: list[dict[str, CategoryDistance]] = [{} for _ in reachable]
    pending: list[tuple[int, str, list]] = []

    for i, point in enumerate(reachable):
        for cat in cats:
            pois = pois_by_category.get(cat) or []

            if not pois:
                # 检索范围内该类设施为零，所有点都是该类盲区
                results[i][cat] = CategoryDistance(
                    category=cat, covered=False, precise=True
                )
                continue

            nearest = _nearest(pois, point.lng, point.lat, settings.GREY_ZONE_CANDIDATES)
            d_min = nearest[0][1]

            if d_min > threshold:
                # 直线都已超出阈值，路网只会更远 → 必然盲区
                results[i][cat] = CategoryDistance(
                    category=cat,
                    distance_m=round(d_min, 1),
                    straight_m=round(d_min, 1),
                    covered=False,
                    precise=True,
                )
            elif d_min < certain_safe:
                # 即便按最大绕行系数也够得着 → 必然非盲区（距离用直线估计）
                results[i][cat] = CategoryDistance(
                    category=cat,
                    distance_m=round(d_min, 1),
                    straight_m=round(d_min, 1),
                    covered=True,
                    precise=False,
                )
            else:
                # 灰色地带：需真实路网距离才能定论
                pending.append((i, cat, [poi for poi, _ in nearest]))
                results[i][cat] = CategoryDistance(
                    category=cat,
                    distance_m=round(d_min, 1),
                    straight_m=round(d_min, 1),
                    covered=False,
                    precise=False,
                )

    # 4. 灰色地带精算（并发，由 baidu_client 统一限流）
    precise_calls = 0
    if pending:
        outcomes = await asyncio.gather(
            *[
                walking_matrix(
                    reachable[i].lng,
                    reachable[i].lat,
                    [(poi.lng, poi.lat) for poi in candidates],
                )
                for (i, _cat, candidates) in pending
            ],
            return_exceptions=True,
        )

        for (i, cat, _candidates), outcome in zip(pending, outcomes, strict=False):
            precise_calls += 1

            if isinstance(outcome, Exception) or not outcome:
                # 精算失败：退回直线判定，并标记结果不精确
                d = results[i][cat].straight_m or threshold
                results[i][cat].covered = d <= threshold
                continue

            road_distances = [r["distance"] for r in outcome if r is not None]
            if not road_distances:
                results[i][cat].covered = False
                results[i][cat].precise = True
                continue

            road_min = min(road_distances)
            results[i][cat].road_m = road_min
            results[i][cat].distance_m = road_min
            results[i][cat].covered = road_min <= threshold
            results[i][cat].precise = True

    # 5. 汇总
    points: list[BlindSpotPoint] = []
    blind_count = 0
    covered_count = {cat: 0 for cat in cats}
    # 分级统计：仅报「盲区率」区分度太低（常接近 100%），按缺失类别数分级才有信息量
    levels = {"light": 0, "medium": 0, "severe": 0}

    for i, point in enumerate(reachable):
        # 判定只看「判定类别」；其余类别仅参与覆盖率统计，不影响是否记为盲区
        missing = [cat for cat in judge_cats if not results[i][cat].covered]
        for cat in cats:
            if results[i][cat].covered:
                covered_count[cat] += 1
        if missing:
            blind_count += 1
            if len(missing) >= 3:
                levels["severe"] += 1
            elif len(missing) == 2:
                levels["medium"] += 1
            else:
                levels["light"] += 1

        points.append(
            BlindSpotPoint(
                lng=point.lng,
                lat=point.lat,
                blind=bool(missing),
                missing_categories=missing,
                categories=results[i],
                # 热力图着色依据：可达性（可及类别占比），而非步行耗时
                accessibility=round(_accessibility_score(results[i], cats), 3),
            )
        )

    total = len(reachable)
    response = BlindSpotResponse(
        center={"lng": lng, "lat": lat},
        categories=cats,
        judge_categories=judge_cats,
        threshold_m=threshold,
        total_points=total,
        blind_points=blind_count,
        points=points,
        category_coverage={
            cat: round(covered_count[cat] / total, 3) for cat in cats
        },
        category_counts={cat: len(pois_by_category.get(cat) or []) for cat in cats},
        failed_categories=failed_categories,
        blind_levels=levels,
        precise_calls=precise_calls,
    )

    # 两类结果不写入缓存：
    #   1. 降级结果（直线估算）误差大
    #   2. 存在类别检索失败的结果——其覆盖率不可信，
    #      一旦缓存，后续调用会一直复用这个错误结论
    if (
        settings.CACHE_ENABLED
        and not isochrone.degraded
        and not failed_categories
    ):
        analysis_cache.set(cache_key, response)

    return response
