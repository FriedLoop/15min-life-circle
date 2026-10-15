"""体检报告与盲区识别验证脚本。

跑一次完整分析，输出：
    - 等时圈摘要
    - 各类设施在圈内的数量与覆盖率
    - 盲区点数量、占比与最常见的缺失类别
    - 健康度评分（0~100）与各类别得分明细
    - 配额消耗估算

用法（在 backend 目录下）：
    python scripts/test_report.py                        # 松山湖校区，全部 10 类
    python scripts/test_report.py 113.779678 23.057248   # 莞城校区
    python scripts/test_report.py 113.881641 22.909011 菜市场,药店,小学   # 只查 3 类，省配额
    python scripts/test_report.py 113.881641 22.909011 "" 300             # 指定网格间隔 300m

注意：完整分析消耗较多配额（等时圈算路 + 逐类 POI 检索 + 灰色地带精算），
      结果已缓存，重复跑同一坐标不会重复消耗。
"""

import asyncio
import sys
from collections import Counter
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_DIR / ".env")

from app.services.report import compute_report  # noqa: E402

# 东莞理工学院松山湖校区（实测 BD09）
DEFAULT_LNG = 113.881641
DEFAULT_LAT = 22.909011


async def run(
    lng: float,
    lat: float,
    categories: list[str] | None = None,
    step_m: int | None = None,
) -> None:
    print("=" * 64)
    print("15 分钟生活圈体检报告")
    print("=" * 64)
    print(f"\n中心点：{lng}, {lat}")
    if categories:
        print(f"关注类别：{', '.join(categories)}")
    else:
        print("关注类别：全部 10 类")
    if step_m:
        print(f"网格间隔：{step_m} m")
    print("\n正在分析（等时圈算路 → 逐类 POI 检索 → 盲区精算），请稍候...\n")

    result = await compute_report(lng, lat, categories=categories, step_m=step_m)

    print("-" * 64)
    if result.address:
        print(f"地址        ：{result.address}")

    iso = result.isochrone
    print(f"\n【等时圈】{result.walk_minutes} 分钟（{iso.threshold_seconds} 秒）")
    print(f"  网格点数 {iso.total_points} / 可达 {iso.reachable_points} / "
          f"算路失败 {iso.failed_points}")
    print(f"  网格参数 ：半径 {iso.radius_m}m，间隔 {iso.step_m}m")
    print(f"  降级模式 ：{'是' if iso.degraded else '否'}")

    print(f"\n【设施覆盖】圈内数量 / 可达点覆盖率")
    for cat in result.coverage:
        count = result.poi_counts.get(cat, 0)
        rate = result.coverage[cat]
        bar = "█" * int(rate * 20)
        print(f"  {cat:<6} {count:>3} 个  {rate * 100:>5.1f}%  {bar}")

    bs = result.blindspot
    blind_rate = bs.blind_points / bs.total_points if bs.total_points else 0
    print(f"\n【服务盲区】阈值 {bs.threshold_m}m")
    if bs.judge_categories:
        print(f"  判定类别：{'、'.join(bs.judge_categories)}"
              f"（其余类别仅统计覆盖率，不参与盲区判定）")

    # 可达性得分分布：热力图据此着色，用于核对颜色是否符合预期
    scores = [p.accessibility for p in bs.points if p.accessibility is not None]
    if scores:
        print(f"  可达性得分：最小 {min(scores):.2f} / 最大 {max(scores):.2f} / "
              f"平均 {sum(scores) / len(scores):.2f}（热力图着色依据）")
    if bs.failed_categories:
        print(f"  ⚠️ 检索失败的类别：{'、'.join(bs.failed_categories)}")
        print("     （这部分覆盖率不可信，多因触及接口限流，建议稍后重试）")
    print(f"  盲区点 {bs.blind_points} / {bs.total_points} "
          f"（{blind_rate * 100:.1f}%）")
    if bs.blind_levels:
        lv = bs.blind_levels
        print(f"  分级：重度(缺3类) {lv.get('severe', 0)} / "
              f"中度(缺2类) {lv.get('medium', 0)} / "
              f"轻度(缺1类) {lv.get('light', 0)}")
    print(f"  灰色地带精算次数：{bs.precise_calls} 次")

    missing: Counter = Counter()
    for point in bs.points:
        missing.update(point.missing_categories)
    if missing:
        print("  最常缺失的类别：")
        for cat, n in missing.most_common(5):
            print(f"    {cat}：{n} 个点缺失")

    print(f"\n【健康度评分】{result.health_score} / 100")
    print("  各类别得分明细：")
    for cat, score in sorted(result.score_detail.items(), key=lambda kv: kv[1]):
        print(f"    {cat:<6} {score:>5.1f}")

    print("\n" + "-" * 64)
    print(f"配额估算：等时圈 {iso.total_points} 条算路 + "
          f"{len(result.coverage)} 次地点检索 + 灰色地带精算 {bs.precise_calls} 次")
    print(f"结果缓存：{len(result.blindspot.points)} 个盲区判定点已缓存")
    print("-" * 64)


def main() -> None:
    lng = float(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LNG
    lat = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_LAT
    categories = None
    if len(sys.argv) > 3 and sys.argv[3].strip():
        categories = [c.strip() for c in sys.argv[3].split(",") if c.strip()]
    step_m = int(sys.argv[4]) if len(sys.argv) > 4 else None

    asyncio.run(run(lng, lat, categories, step_m))


if __name__ == "__main__":
    main()
