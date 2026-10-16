"""网格策略对照实验：算路调用量 vs 可达面积误差。

对比三种采样策略（结论写入 docs/技术方案.md）：

    1. 单级精细网格     每个网格点都真实算路 —— 作为**基准真值**
    2. 分级网格 + IDW   先用几何性质剪枝，只对灰色地带算路，其余插值
    3. 扇形采样 + IDW   只沿 N 个方向 × M 个距离采样，全区域靠插值重构

关键设计：先对**全部**网格点做一次真实算路，得到真值；三种策略都在这份
真值上评估，因此调用的增加只来自扇形采样（其采样点不在网格上）。
这样算路配额只花一次，各策略的「面积误差」是在同一把尺子上量的。

可回答两个问题：
    - 分级网格省了多少算路？可达性结论被改变了多少？
      （几何剪枝**不是**无损的：它依赖「路网 <= 绕行系数 × 直线距离」，
        该前提在地形被水域 / 围墙切断处会失效，本脚本正是量化这个偏差）
    - 扇形采样省得更多，但重构出来的可达面积误差有多大？
      （这是它没被选作主算法的量化依据）

用法（在 backend 目录下）：
    python scripts/compare_grid_strategies.py
    python scripts/compare_grid_strategies.py 113.745181 23.035585
    python scripts/compare_grid_strategies.py 113.881641 22.909011 150 15
    python scripts/compare_grid_strategies.py --offline      # 用合成路网跑通流程，不消耗配额

注意：脚本绕过结果缓存，会真实消耗算路配额
      （约 网格点数 + 扇形采样点数，默认约 197 + 121 = 318 条）。
      加 --offline 则不触碰任何接口，仅用于验证脚本逻辑。
"""

import asyncio
import json
import math
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_DIR / ".env")

from app.core.config import settings  # noqa: E402
from app.services import isochrone as isochrone_service  # noqa: E402
from app.services.routematrix import walking_matrix  # noqa: E402
from app.utils.geo import (  # noqa: E402
    generate_square_grid,
    haversine_distance,
    idw_interpolate,
    offset_by_meters,
)

# 东莞理工学院松山湖校区（实测 BD09）
DEFAULT_LNG = 113.881641
DEFAULT_LAT = 22.909011

# 扇形采样参数：方向数 × 距离环数。20 方向 = 每 18 度一条射线。
SECTOR_DIRECTIONS = 20
SECTOR_RADII_M = (200, 400, 600, 800, 1000, 1200)

# 算路结果磁盘缓存：调参时反复跑同一个点位不必反复消耗配额。
# 缓存以「起点|终点」为键——耗时与起点相关，不能只按终点去重。
CACHE_PATH = BACKEND_DIR / ".route_cache.json"
_ROUTE_CACHE: dict[str, dict | None] = {}
_CACHE_DIRTY = False
_OFFLINE = False


def _key(lng: float, lat: float) -> tuple[float, float]:
    return (round(lng, 6), round(lat, 6))


def _cache_key(lng: float, lat: float, point: tuple[float, float]) -> str:
    return f"{lng:.6f},{lat:.6f}|{point[0]:.6f},{point[1]:.6f}"


def _load_route_cache() -> None:
    global _ROUTE_CACHE
    if not CACHE_PATH.is_file():
        return
    try:
        _ROUTE_CACHE = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        print(f"已加载算路缓存：{len(_ROUTE_CACHE)} 条（命中部分不再消耗配额）")
    except (OSError, json.JSONDecodeError):
        _ROUTE_CACHE = {}


def _save_route_cache() -> None:
    global _CACHE_DIRTY
    if not _CACHE_DIRTY:
        return
    CACHE_PATH.write_text(
        json.dumps(_ROUTE_CACHE, ensure_ascii=False), encoding="utf-8"
    )
    _CACHE_DIRTY = False


async def _route(
    lng: float, lat: float, points: list[tuple[float, float]]
) -> list:
    """带磁盘缓存的批量算路，返回与 points 等长的结果列表。"""
    global _CACHE_DIRTY

    if _OFFLINE:
        return await walking_matrix(lng, lat, points)

    missing = [p for p in points if _cache_key(lng, lat, p) not in _ROUTE_CACHE]
    if not missing:
        print(f"  全部命中缓存：{len(points)} 条（未消耗配额）")
        return [_ROUTE_CACHE[_cache_key(lng, lat, p)] for p in points]

    print(f"  实际发出算路请求：{len(missing)} / {len(points)} 条")
    # 分块串行发送并在每块之后落盘：百度对瞬时并发很敏感，
    # 一次把几百条全压上去容易被限流；分块还能保证被限流时已算的部分不丢。
    chunk_size = settings.ROUTEMATRIX_BATCH_SIZE
    for start in range(0, len(missing), chunk_size):
        chunk = missing[start : start + chunk_size]
        routes = await walking_matrix(lng, lat, chunk)
        for point, route in zip(chunk, routes, strict=False):
            _ROUTE_CACHE[_cache_key(lng, lat, point)] = route
        _CACHE_DIRTY = True
        _save_route_cache()
        done = min(start + chunk_size, len(missing))
        print(f"    已完成 {done} / {len(missing)} 条")

    return [_ROUTE_CACHE[_cache_key(lng, lat, p)] for p in points]


def _sector_points(
    lng: float, lat: float, directions: int, radii: tuple[int, ...]
) -> list[tuple[float, float]]:
    """沿 directions 个方向、radii 个距离取样，构成星形（扇形）采样点集。"""
    points: list[tuple[float, float]] = []
    for i in range(directions):
        angle = 2 * math.pi * i / directions
        east_unit, north_unit = math.cos(angle), math.sin(angle)
        for radius in radii:
            points.append(
                offset_by_meters(
                    lng, lat, east_unit * radius, north_unit * radius
                )
            )
    return points


async def measure(lng: float, lat: float, step: int, minutes: int) -> dict:
    """跑一次对照实验，返回可序列化的结果。"""
    threshold = minutes * 60
    radius = settings.ISOCHRONE_MAX_RADIUS_M

    grid = generate_square_grid(lng, lat, radius, step)
    print(f"细网格：{len(grid)} 点（半径 {radius} m / 间隔 {step} m）")

    # ---- 基准真值：全部网格点真实算路 ----
    print("正在基准算路（全部网格点）...")
    truth_routes = await _route(lng, lat, grid)
    truth: dict[tuple[float, float], int] = {}
    for point, route in zip(grid, truth_routes, strict=False):
        if route is not None:
            truth[_key(point[0], point[1])] = route["duration"]

    base_reachable = {k for k, duration in truth.items() if duration <= threshold}
    print(
        f"  基准：可达 {len(base_reachable)} 点，"
        f"失败 {len(grid) - len(truth)} 点"
    )

    # ---- 策略二：分级网格 + IDW（几何剪枝，采样点是网格点的子集）----
    coarse_step = isochrone_service._align_coarse_step(
        step, settings.GRID_COARSE_STEP_M
    )
    reach_bound, unreach_bound = isochrone_service._pruning_bounds(threshold)
    coarse_points = generate_square_grid(lng, lat, radius, coarse_step)
    targets, band = isochrone_service._select_route_targets(
        grid, coarse_points, lng, lat, reach_bound, unreach_bound
    )
    coarse_samples = [
        (p[0], p[1], float(truth[_key(p[0], p[1])]))
        for p in targets
        if _key(p[0], p[1]) in truth
    ]

    routed_keys = {_key(p[0], p[1]) for p in targets}
    coarse_reachable: set[tuple[float, float]] = set()
    # 插值误差按两类分开统计：内部点（耗时梯度平缓）与外部点（本就深红、
    # 只要求判定为不可达）对精度的要求完全不同，混在一起会掩盖真实水平
    errors_inside: list[float] = []
    errors_outside: list[float] = []

    for point in grid:
        key = _key(point[0], point[1])
        if key in routed_keys:
            # 真实算路过的点：直接用真值判定
            if truth.get(key, threshold + 1) <= threshold:
                coarse_reachable.add(key)
            continue

        # 被几何剪枝的点：判定完全由几何性质决定，耗时由 IDW 插值给出
        straight = haversine_distance(lng, lat, point[0], point[1])
        estimated = isochrone_service._estimated_point(
            point[0], point[1], straight, coarse_samples, reach_bound
        )
        if estimated.reachable:
            coarse_reachable.add(key)
        # 插值精度：与真值比较（真值来自基准那次全量算路，不额外消耗配额）
        if key in truth and estimated.duration is not None:
            error = abs(estimated.duration - truth[key])
            if straight <= reach_bound:
                errors_inside.append(error)
            else:
                errors_outside.append(error)

    def _median(values: list[float]) -> int | None:
        return int(sorted(values)[len(values) // 2]) if values else None

    # ---- 诊断：几何剪枝的判定与真实路网不一致的点 ----
    # 这是判断「剪枝边界是否足够保守」的唯一硬证据：
    # 若某点直线距离 <= 必然可达上界、真实算路却超时，说明绕行系数上界被突破，
    # 必须加大 GRID_STRATEGY_MARGIN（或承认该优化是有误差的近似）。
    mismatches: list[dict] = []
    for point in grid:
        key = _key(point[0], point[1])
        if key not in truth:
            continue
        straight = haversine_distance(lng, lat, point[0], point[1])
        truth_reachable = truth[key] <= threshold
        if (key in coarse_reachable) != truth_reachable:
            mismatches.append(
                {
                    "lng": round(point[0], 6),
                    "lat": round(point[1], 6),
                    "straight_m": round(straight, 1),
                    "truth_duration_s": truth[key],
                    "zone": "certain_reach"
                    if straight <= reach_bound
                    else "certain_unreach",
                    "truth": "reachable" if truth_reachable else "unreachable",
                }
            )

    # ---- 策略三：扇形采样 + IDW（采样点不在网格上，需要额外算路）----
    sector_points = _sector_points(lng, lat, SECTOR_DIRECTIONS, SECTOR_RADII_M)
    print(f"正在扇形采样算路（{len(sector_points)} 点）...")
    sector_routes = await _route(lng, lat, sector_points)
    sector_samples = [
        (point[0], point[1], float(route["duration"]))
        for point, route in zip(sector_points, sector_routes, strict=False)
        if route is not None
    ]

    sector_reachable: set[tuple[float, float]] = set()
    for point in grid:
        key = _key(point[0], point[1])
        value = idw_interpolate(
            point[0],
            point[1],
            sector_samples,
            power=settings.IDW_POWER,
            neighbors=settings.IDW_NEIGHBORS,
        )
        if value is not None and value <= threshold:
            sector_reachable.add(key)

    cell_area_m2 = step * step

    def area(cells: set) -> float:
        return len(cells) * cell_area_m2 / 1e6  # km2

    def iou(a: set, b: set) -> float:
        union = a | b
        return len(a & b) / len(union) if union else 0.0

    base_area = area(base_reachable)
    coarse_area = area(coarse_reachable)
    sector_area = area(sector_reachable)

    return {
        "center": {"lng": lng, "lat": lat},
        "step_m": step,
        "minutes": minutes,
        "grid_points": len(grid),
        "pruning": {
            "reach_bound_m": round(reach_bound, 1),
            "unreach_bound_m": round(unreach_bound, 1),
            "coarse_step_m": int(coarse_step),
        },
        "baseline": {
            "strategy": "single",
            "calls": len(grid),
            "reachable_points": len(base_reachable),
            "area_km2": round(base_area, 3),
            "area_error_pct": 0.0,
            "iou": 1.0,
        },
        "coarse": {
            "strategy": "coarse+idw",
            "calls": len(targets),
            "saving_pct": round((1 - len(targets) / len(grid)) * 100, 1),
            "reachable_points": len(coarse_reachable),
            "area_km2": round(coarse_area, 3),
            "area_error_pct": round(
                abs(coarse_area - base_area) / base_area * 100, 2
            )
            if base_area
            else 0.0,
            "iou": round(iou(base_reachable, coarse_reachable), 4),
            "interpolated_points": len(grid) - len(routed_keys),
            "mismatch_count": len(mismatches),
            "mismatches": mismatches,
            "idw_inside_samples": len(errors_inside),
            "idw_inside_median_s": _median(errors_inside),
            "idw_inside_max_s": int(max(errors_inside)) if errors_inside else None,
            "idw_outside_samples": len(errors_outside),
            "idw_outside_median_s": _median(errors_outside),
        },
        "sector": {
            "strategy": "sector+idw",
            "directions": SECTOR_DIRECTIONS,
            "radii_m": list(SECTOR_RADII_M),
            "calls": len(sector_points),
            "saving_pct": round((1 - len(sector_points) / len(grid)) * 100, 1),
            "reachable_points": len(sector_reachable),
            "area_km2": round(sector_area, 3),
            "area_error_pct": round(
                abs(sector_area - base_area) / base_area * 100, 2
            )
            if base_area
            else 0.0,
            "iou": round(iou(base_reachable, sector_reachable), 4),
        },
    }


def _print_report(result: dict) -> None:
    base = result["baseline"]
    coarse = result["coarse"]
    sector = result["sector"]

    print("\n" + "=" * 74)
    print("网格策略对照实验结果")
    print("=" * 74)
    print(f"中心点    ：{result['center']['lng']}, {result['center']['lat']}")
    print(
        f"网格参数  ：半径 {settings.ISOCHRONE_MAX_RADIUS_M} m / 间隔 {result['step_m']} m "
        f"/ {result['minutes']} 分钟"
    )
    print(
        f"剪枝边界  ：必然可达 <= {result['pruning']['reach_bound_m']} m，"
        f"必然不可达 > {result['pruning']['unreach_bound_m']} m，"
        f"粗网格 {result['pruning']['coarse_step_m']} m"
    )

    print("\n" + "-" * 74)
    print(f"{'策略':<18}{'算路调用':>9}{'省配额':>9}{'可达点':>8}{'面积km2':>10}{'面积误差':>10}{'IoU':>8}")
    print("-" * 74)
    rows = [
        ("单级精细网格", base, "0.0%"),
        ("分级网格+IDW", coarse, f"{coarse['saving_pct']}%"),
        ("扇形采样+IDW", sector, f"{sector['saving_pct']}%"),
    ]
    for name, item, saving in rows:
        print(
            f"{name:<18}{item['calls']:>9}{saving:>9}{item['reachable_points']:>8}"
            f"{item['area_km2']:>10}{str(item['area_error_pct']) + '%':>10}"
            f"{item['iou']:>8}"
        )
    print("-" * 74)

    if coarse.get("idw_inside_samples"):
        print(
            f"\n分级网格的 IDW 插值精度（对照基准真值）："
            f"\n  必然可达区（{coarse['idw_inside_samples']} 点）耗时误差中位数 "
            f"{coarse['idw_inside_median_s']} 秒、最大 {coarse['idw_inside_max_s']} 秒"
            f"\n  必然不可达区（{coarse['idw_outside_samples']} 点）耗时误差中位数 "
            f"{coarse['idw_outside_median_s']} 秒（该区只要求判定为不可达，"
            f"耗时仅供热力图着色）"
        )
    if coarse.get("mismatch_count"):
        print(
            f"\n[注意] 分级网格的几何剪枝与真实路网有 {coarse['mismatch_count']} 个点判定不一致："
        )
        for item in coarse["mismatches"][:10]:
            print(
                f"  直线 {item['straight_m']} m（{item['zone']}）"
                f" 真实耗时 {item['truth_duration_s']} 秒 → 实际{item['truth']}"
            )
        print("  说明绕行系数 1.6 的上界被突破，需加大 GRID_STRATEGY_MARGIN")
    else:
        print("\n分级网格的几何剪枝与真实路网判定完全一致（剪枝是无损的）")

    print(
        "\n说明：分级网格的判定来自几何性质，剪枝边界内的点不再算路；"
        "扇形采样省得更多，\n"
        "      但可达面积完全靠插值重构，误差即其代价。"
    )
    print("=" * 74)


def _install_synthetic_road(center_lng: float, center_lat: float) -> None:
    """把批量算路换成一个合成路网，用于离线跑通流程（不消耗任何配额）。

    模型：路网距离 = 直线距离 × 1.4，步行速度取配置值。
    该模型满足剪枝所需的前提（绕行 <= DETOUR_FACTOR），因此离线结果只用于
    验证脚本与算法链路，不能当作实测数字写进文档。
    """
    global walking_matrix, _OFFLINE

    _OFFLINE = True

    async def fake(lng, lat, destinations, batch_size=None):
        results = []
        for point in destinations:
            straight = haversine_distance(lng, lat, point[0], point[1])
            distance = straight * 1.4
            results.append(
                {
                    "duration": max(1, int(distance / settings.WALK_SPEED_MPS)),
                    "distance": int(distance),
                }
            )
        return results

    walking_matrix = fake
    print("[离线模式] 使用合成路网（路网距离 = 直线 x 1.4），不消耗配额\n")


def main() -> None:
    argv = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    offline = "--offline" in sys.argv

    lng = float(argv[0]) if len(argv) > 0 else DEFAULT_LNG
    lat = float(argv[1]) if len(argv) > 1 else DEFAULT_LAT
    step = int(argv[2]) if len(argv) > 2 else settings.GRID_STEP_M
    minutes = int(argv[3]) if len(argv) > 3 else settings.WALK_MINUTES

    if offline:
        _install_synthetic_road(lng, lat)
    else:
        _load_route_cache()

    result = asyncio.run(measure(lng, lat, step, minutes))
    _print_report(result)

    name = "grid_strategy_result_offline.json" if offline else "grid_strategy_result.json"
    out = BACKEND_DIR / "scripts" / name
    out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n明细已写入：{out.relative_to(BACKEND_DIR.parent)}")


if __name__ == "__main__":
    main()
