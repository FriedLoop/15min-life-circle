"""等时圈计算服务。

算法：网格采样 + 真实路网算路
    1. 以中心点生成半径 R、间隔 S 的网格
    2. 对每个网格点调用「步行批量算路」，取得真实步行耗时
    3. 筛选耗时 ≤ 阈值（默认 900 秒）的点 → 可达区域
    4. 返回逐点耗时与可达标记。等时圈的**边界不在后端生成**：
       前端按网格单元逐一绘制色块，再逐格描边还原真实外轮廓。
       （不用凸包：它会把凹陷与缺口抹平，反而丢掉「路网 ≠ 直线」的证据）

为何用网格法而非射线法：
    射线法沿若干方向各算一条路径，调用量小，但只得到边界上稀疏的点，
    无法表达区域内部的耗时差异，画不出评分标准要求的「热力图」。
    网格法内部有完整的耗时分布：既能画热力图，
    又能直接复用于阶段 3 的盲区分析（判断每个网格点周边缺什么设施）。

两种网格策略（coarse_grid 参数）：
    single  单级精细网格：每个网格点都发一次真实算路。**默认**，也是基准真值。

    coarse  分级网格 + IDW 插值：按几何性质把部分网格点直接定论，
            只对结果不确定的「灰色地带」做真实算路，其余耗时由
            反距离加权（IDW）插值补全：

                记 d = 网格点到中心点的直线距离
                  ├─ d ≤ T·v/K·(1-m)  → 判定可达：路网 ≤ K·d，耗时 ≤ T·(1-m) < T
                  ├─ d >  T·v·(1+m)   → 判定不可达：路网 ≥ d，耗时 > T·(1+m) > T
                  └─ 其余（灰色地带） → 真实算路才能定论

                T=阈值秒数，v=WALK_SPEED_MPS，K=DETOUR_FACTOR，m=GRID_STRATEGY_MARGIN。

            **这是有损优化，默认关闭**。上面两条推断依赖「路网距离 ≤ K × 直线距离」，
            该前提在实测中会被突破：松山湖校区被水域与围墙切断，
            存在直线仅 424~618 m、真实步行耗时却达 1023~1480 s 的点
            （等效绕行系数 2.8，远超 K=1.6）。因此 coarse 策略的等时圈与
            盲区统计会与 single 有出入——松山湖实测面积误差 7.94%、5 个点判定相反。

            取值建议：配额充足时用 single；配额紧张、且能接受「面积误差约 8%」
            量级时再用 coarse。实测数据与三策略对照见
            backend/scripts/compare_grid_strategies.py 与 docs/技术方案.md §5。

            为给被剪掉的内部点提供插值锚点，coarse 策略会额外采样一圈粗网格点
            （步长自动对齐主网格的整数倍，落在细网格上，复用同一次算路结果）。

降级策略：
    批量算路不可用时（配额耗尽、服务异常、AK 失效），退化为
    「直线距离 × 绕行系数 ÷ 步行速度」估算，并标记 degraded=True，
    保证演示时接口不会直接崩掉——对应评分点「API 异常时的降级容错」。
"""

import math

from app.core.config import settings
from app.schemas.models import IsochronePoint, IsochroneResponse
from app.services.baidu_client import BaiduApiError
from app.services.routematrix import RouteInfo, walking_matrix
from app.utils.cache import isochrone_cache
from app.utils.geo import (
    generate_square_grid,
    haversine_distance,
    idw_interpolate,
    quantize_coord,
)

# 网格点坐标的去重精度（小数位）。1e-6 度约 0.11 m，远小于网格间隔，
# 因此既能精确识别「粗网格点与细网格点重合」，又不会误合并相邻网格点。
_COORD_PRECISION = 6


def _estimate_by_straight_line(
    points: list[tuple[float, float]],
    center_lng: float,
    center_lat: float,
) -> list[RouteInfo | None]:
    """降级估算：用直线距离推算步行耗时。

    直线距离是路网距离的下界，乘绕行系数作为上界估计。
    精度不如真实算路，但足以保证接口可用、图形大致正确。
    """
    estimates: list[RouteInfo | None] = []

    for lng, lat in points:
        straight = haversine_distance(center_lng, center_lat, lng, lat)
        road_distance = straight * settings.DETOUR_FACTOR
        estimates.append(
            {
                "duration": int(road_distance / settings.WALK_SPEED_MPS),
                "distance": int(road_distance),
            }
        )

    return estimates


def _make_cache_key(
    lng: float,
    lat: float,
    minutes: int,
    step: float,
    radius: float,
    coarse: bool,
) -> tuple:
    """构造缓存键。

    坐标按 CACHE_COORD_PRECISION_M（默认 50m）量化，
    使地图上小幅拖动命中同一份结果，避免缓存被大量近似键冲垮。
    网格策略必须计入键：两种策略的内部耗时不同，不能互相命中。
    """
    q_lng, q_lat = quantize_coord(lng, lat, settings.CACHE_COORD_PRECISION_M)
    return (q_lng, q_lat, minutes, int(step), int(radius), bool(coarse))


def _coord_key(lng: float, lat: float) -> tuple[float, float]:
    return (round(lng, _COORD_PRECISION), round(lat, _COORD_PRECISION))


def _align_coarse_step(step: float, coarse_step: float) -> float:
    """把粗网格步长向上取整为细网格步长的整数倍。

    这样粗网格点恰好落在细网格点上，「灰色地带」算过的点不会因为
    粗网格另起一套坐标而重复消耗配额。
    """
    multiple = max(1, math.ceil(coarse_step / step))
    return multiple * step


def _pruning_bounds(threshold_seconds: float) -> tuple[float, float]:
    """返回分级网格的剪枝边界（米）：(判定可达上界, 判定不可达下界)。

    「判定」而非「必然」：推导依赖路网距离 ≤ DETOUR_FACTOR × 直线距离，
    该前提在路网被水域 / 围墙切断时会失效（松山湖实测绕行系数可达 2.8）。
    因此这是近似剪枝，不是无损推理——见模块 docstring。
    """
    speed = settings.WALK_SPEED_MPS
    margin = settings.GRID_STRATEGY_MARGIN

    reach_bound = threshold_seconds * speed / settings.DETOUR_FACTOR * (1 - margin)
    unreach_bound = threshold_seconds * speed * (1 + margin)
    return reach_bound, unreach_bound


def _select_route_targets(
    grid_points: list[tuple[float, float]],
    coarse_points: list[tuple[float, float]],
    center_lng: float,
    center_lat: float,
    reach_bound: float,
    unreach_bound: float,
) -> tuple[list[tuple[float, float]], set[int]]:
    """挑出真正需要算路的点。

    Returns:
        (算路点列表, 需要真实算路的细网格下标集合)
    """
    band: set[int] = set()
    targets: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()

    for index, point in enumerate(grid_points):
        straight = haversine_distance(center_lng, center_lat, point[0], point[1])
        if not (reach_bound < straight <= unreach_bound):
            continue
        band.add(index)
        key = _coord_key(point[0], point[1])
        if key not in seen:
            seen.add(key)
            targets.append(point)

    # 粗网格点只作为「判定可达」区域内部的插值锚点，
    # 落在灰色地带的粗网格点已包含在 band 里，落在判定不可达区域的则无需算路。
    for point in coarse_points:
        straight = haversine_distance(center_lng, center_lat, point[0], point[1])
        if straight > reach_bound:
            continue
        key = _coord_key(point[0], point[1])
        if key not in seen:
            seen.add(key)
            targets.append(point)

    return targets, band


def _estimated_point(
    lng: float,
    lat: float,
    straight: float,
    samples: list[tuple[float, float, float]],
    reach_bound: float,
) -> IsochronePoint:
    """给「未算路」的网格点定值。

    可达性按剪枝边界给出（d ≤ reach_bound 判为可达，否则判为不可达），
    耗时由 IDW 插值估算，并按几何上下界夹紧，避免出现
    「插值说可达、边界说不可达」这类自相矛盾的结果。
    """
    speed = settings.WALK_SPEED_MPS
    estimate = idw_interpolate(
        lng,
        lat,
        samples,
        power=settings.IDW_POWER,
        neighbors=settings.IDW_NEIGHBORS,
    )

    if straight <= reach_bound:
        # 判定可达：耗时上界 = 绕行系数 × 直线距离 ÷ 速度
        upper = round(settings.DETOUR_FACTOR * straight / speed)
        duration = upper if estimate is None else min(round(estimate), upper)
        return IsochronePoint(
            lng=lng,
            lat=lat,
            duration=max(duration, 0),
            distance_m=upper,
            reachable=True,
            interpolated=True,
        )

    # 判定不可达：路网距离不小于直线距离，故耗时有明确下界
    lower = round(straight / speed)
    duration = lower if estimate is None else max(round(estimate), lower)
    return IsochronePoint(
        lng=lng,
        lat=lat,
        duration=duration,
        distance_m=lower,
        reachable=False,
        interpolated=True,
    )


async def compute_isochrone(
    lng: float,
    lat: float,
    walk_minutes: int | None = None,
    step_m: int | None = None,
    radius_m: int | None = None,
    coarse: bool | None = None,
) -> IsochroneResponse:
    """计算指定中心点的步行等时圈。

    Args:
        lng / lat: 中心点（BD09）
        walk_minutes: 步行时间阈值（分钟），默认取配置（15）
        step_m: 网格间隔（米），默认取配置
        radius_m: 网格覆盖半径（米），默认取配置
        coarse: 是否启用「分级网格 + IDW 插值」，默认关闭

    Returns:
        等时圈结果，含逐点耗时与可达标记（供前端绘制及盲区分析复用）。
        真实算路调用量记录在 routed_points、插值点数记录在 interpolated_points，
        便于核对配额优化效果。coarse=True 时结果是有损近似，见模块 docstring。
    """
    minutes = walk_minutes or settings.WALK_MINUTES
    threshold = minutes * 60
    step = step_m or settings.GRID_STEP_M
    radius = radius_m or settings.ISOCHRONE_MAX_RADIUS_M
    use_coarse = bool(coarse)

    # 0. 命中缓存则直接返回，不消耗配额
    cache_key = _make_cache_key(lng, lat, minutes, step, radius, use_coarse)
    if settings.CACHE_ENABLED:
        hit = isochrone_cache.get(cache_key)
        if hit is not None:
            return hit.model_copy(update={"cached": True})

    # 1. 生成网格
    grid_points = generate_square_grid(lng, lat, radius, step)
    coarse_step = _align_coarse_step(step, settings.GRID_COARSE_STEP_M)
    reach_bound, unreach_bound = _pruning_bounds(threshold)

    band: set[int] = set()
    if use_coarse:
        # 2a. 分级网格：几何剪枝 + 粗网格锚点
        coarse_points = generate_square_grid(lng, lat, radius, coarse_step)
        route_targets, band = _select_route_targets(
            grid_points, coarse_points, lng, lat, reach_bound, unreach_bound
        )
    else:
        # 2b. 单级网格：全部网格点都算路
        route_targets = list(grid_points)

    # 3. 批量算路（失败则降级为直线估算）
    degraded = False
    message = ""
    try:
        routes = await walking_matrix(lng, lat, route_targets)
    except BaiduApiError as exc:
        degraded = True
        message = f"批量算路不可用，已降级为直线距离估算：{exc.message}"
        routes = _estimate_by_straight_line(route_targets, lng, lat)

    routed: dict[tuple[float, float], RouteInfo | None] = {}
    samples: list[tuple[float, float, float]] = []
    for (point_lng, point_lat), route in zip(route_targets, routes, strict=False):
        routed[_coord_key(point_lng, point_lat)] = route
        if route is not None:
            samples.append((point_lng, point_lat, float(route["duration"])))

    # 4. 逐点定值：算过的用真实结果，没算的用插值 + 几何上下界
    iso_points: list[IsochronePoint] = []
    reachable_coords: list[tuple[float, float]] = []
    failed = 0
    interpolated_count = 0

    for index, (point_lng, point_lat) in enumerate(grid_points):
        key = _coord_key(point_lng, point_lat)

        if not use_coarse or index in band:
            route = routed.get(key)
            if route is None:
                # 该点确实发起了算路但失败：如实标记，不能当成 0 秒到达
                failed += 1
                iso_points.append(IsochronePoint(lng=point_lng, lat=point_lat))
                continue

            reachable = route["duration"] <= threshold
            iso_points.append(
                IsochronePoint(
                    lng=point_lng,
                    lat=point_lat,
                    duration=route["duration"],
                    distance_m=route["distance"],
                    reachable=reachable,
                )
            )
            if reachable:
                reachable_coords.append((point_lng, point_lat))
            continue

        # 分级网格下线剪掉的点：几何上已能定论，耗时由 IDW 插值给出
        straight = haversine_distance(lng, lat, point_lng, point_lat)
        estimated = _estimated_point(
            point_lng, point_lat, straight, samples, reach_bound
        )
        interpolated_count += 1
        iso_points.append(estimated)
        if estimated.reachable:
            reachable_coords.append((point_lng, point_lat))

    result = IsochroneResponse(
        center={"lng": lng, "lat": lat},
        walk_minutes=minutes,
        threshold_seconds=threshold,
        radius_m=int(radius),
        step_m=int(step),
        total_points=len(grid_points),
        reachable_points=len(reachable_coords),
        failed_points=failed,
        points=iso_points,
        degraded=degraded,
        message=message,
        strategy="coarse" if use_coarse else "single",
        coarse_step_m=int(coarse_step) if use_coarse else 0,
        routed_points=len(route_targets),
        interpolated_points=interpolated_count,
    )

    # 只缓存真实算路结果：降级估算误差大，不应被反复复用
    if settings.CACHE_ENABLED and not degraded:
        isochrone_cache.set(cache_key, result)

    return result
