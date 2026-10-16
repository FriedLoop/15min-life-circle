"""等时圈算法验证脚本。

跑一次真实算路，输出汇总统计（不逐个打印网格点，避免刷屏），
并重复查询同一坐标一次，用于验证缓存是否生效。

可据此判断算法是否工作正常：
    - 网格点数是否符合预期（半径1200m / 间隔200m ≈ 113）
    - 可达比例是否落在合理区间
    - 算路失败率是否过高（水域、无路网区域会失败）
    - 最远可达点的路网距离，验证「15分钟 ≈ 1050m 路网距离」的实测结论

用法（在 backend 目录下）：
    python scripts/test_isochrone.py                          # 松山湖校区，默认间隔
    python scripts/test_isochrone.py 113.745181 23.035585     # 指定坐标（莞城）
    python scripts/test_isochrone.py 113.881641 22.909011 150 # 指定网格间隔，对比精度

注意：脚本会查询同一坐标两次（第二次用于验证缓存），
      实际仅第一次消耗配额，约等于网格点数（默认约 113 条）。
"""

import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_DIR / ".env")

from app.services.isochrone import compute_isochrone  # noqa: E402
from app.utils.geo import haversine_distance  # noqa: E402

# 东莞理工学院松山湖校区（实测 BD09）
DEFAULT_LNG = 113.881641
DEFAULT_LAT = 22.909011


async def run(lng: float, lat: float, step_m: int | None = None) -> None:
    print("=" * 60)
    print("等时圈算法验证")
    print("=" * 60)
    print(f"\n中心点：{lng}, {lat}")
    if step_m:
        print(f"网格间隔：{step_m}m（自定义）")
    print("正在调用批量算路（并发上限 3，需分多批），请稍候...\n")

    result = await compute_isochrone(lng, lat, step_m=step_m)

    print("-" * 60)
    print(f"时间阈值      ：{result.walk_minutes} 分钟（{result.threshold_seconds} 秒）")
    print(f"网格参数      ：半径 {result.radius_m}m / 间隔 {result.step_m}m")
    print(f"网格点总数    ：{result.total_points}")
    print(f"可达点数      ：{result.reachable_points}")
    print(f"算路失败点数  ：{result.failed_points}")
    print(f"降级模式      ：{'是（直线估算）' if result.degraded else '否（真实路网）'}")
    if result.message:
        print(f"说明          ：{result.message}")

    # 耗时分布
    durations = [p.duration for p in result.points if p.duration is not None]
    if durations:
        print("\n步行耗时分布（秒）：")
        print(
            f"  最小 {min(durations)} / 最大 {max(durations)} / "
            f"平均 {sum(durations) // len(durations)}"
        )
        reachable_durations = [p.duration for p in result.points if p.reachable]
        if reachable_durations:
            print(
                f"  可达点内最大耗时：{max(reachable_durations)} 秒"
                f"（应 ≤ {result.threshold_seconds}）"
            )

    # 可达半径：最远可达点到中心的直线距离
    reachable_points = [p for p in result.points if p.reachable]
    if reachable_points:
        farthest = max(
            reachable_points,
            key=lambda p: haversine_distance(lng, lat, p.lng, p.lat),
        )
        straight = haversine_distance(lng, lat, farthest.lng, farthest.lat)
        print(
            f"\n最远可达点：直线 {straight:.0f}m，路网 {farthest.distance_m}m，"
            f"耗时 {farthest.duration}s"
        )
        print(f"  反推步行速度：{farthest.distance_m / farthest.duration:.3f} m/s"
              f"（百度实测约 1.17）")

    # 缓存验证：同一坐标再查一次，应当命中缓存、不再消耗配额
    again = await compute_isochrone(lng, lat, step_m=step_m)

    print("\n" + "-" * 60)
    if again.cached:
        print("缓存验证：[OK] 再次查询命中缓存，未消耗配额")
        print(f"本次实际消耗配额：约 {result.total_points} 条（仅第一次）")
    else:
        print("缓存验证：[WARN] 再次查询未命中，请检查 CACHE_ENABLED 配置")
        print(f"本次消耗配额：约 {result.total_points * 2} 条（两次均真实请求）")
    print("-" * 60)


def main() -> None:
    lng = float(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LNG
    lat = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_LAT
    step_m = int(sys.argv[3]) if len(sys.argv) > 3 else None
    asyncio.run(run(lng, lat, step_m))


if __name__ == "__main__":
    main()
