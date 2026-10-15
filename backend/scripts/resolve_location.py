"""地点解析工具：把地名解析为精确坐标。

为什么需要它：
    地理编码（geocoding）对大型园区、学校这类「面状地物」的定位
    可能偏差数百米甚至上公里（它往往落在园区边界或某条道路上）；
    而地点检索（place）返回的是该地点在地图上的实际标注点，通常更精确。

    本项目所有分析都以中心点坐标为基础，坐标偏了报告就全错，
    因此开工前必须交叉验证：两者若相差较大，应以地点检索结果为准。

用法（在 backend 目录下）：
    python scripts/resolve_location.py 东莞理工学院松山湖校区
    python scripts/resolve_location.py 东莞理工学院莞城校区

消耗：每次 1 次地理编码 + 1 次地点检索（这两个服务配额充足）。
"""

import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_DIR / ".env")

from app.services.baidu_client import baidu_client  # noqa: E402
from app.services.geocoding import geocode  # noqa: E402
from app.utils.geo import haversine_distance  # noqa: E402

DEFAULT_ADDRESS = "东莞理工学院松山湖校区"
# 超过这个距离就认为地理编码不可靠，应改用地点检索结果
WARN_DISTANCE_M = 300


async def resolve(address: str, city: str = "东莞市") -> None:
    print("=" * 64)
    print(f"地点解析：{address}")
    print("=" * 64)

    # 1. 地理编码
    geo = await geocode(address, city)
    print(f"\n[地理编码] {geo.lng:.6f}, {geo.lat:.6f}")
    print(f"            level={geo.level}  confidence={geo.confidence}")

    # 2. 地点检索（POI 标注点，通常更准）
    data = await baidu_client.get(
        "/place/v2/search",
        {"query": address, "region": city, "page_size": 5, "scope": 2},
    )

    results = data.get("results") or []
    print(f"\n[地点检索] 共 {data.get('total', 0)} 条，前 {len(results)} 条：")
    for item in results:
        loc = item.get("location") or {}
        print(
            f"  {item.get('name')}  "
            f"{loc.get('lng', 0):.6f},{loc.get('lat', 0):.6f}  "
            f"{item.get('address', '')}"
        )

    # 3. 交叉对比
    if not results:
        print("\n⚠️ 地点检索无结果，请换更具体的关键词重试")
        return

    top = results[0]
    top_loc = top.get("location") or {}
    poi_lng, poi_lat = top_loc.get("lng", 0.0), top_loc.get("lat", 0.0)

    gap = haversine_distance(geo.lng, geo.lat, poi_lng, poi_lat)
    print(f"\n{'-' * 64}")
    print(f"两条路径相距：{gap:.0f} 米")

    if gap > WARN_DISTANCE_M:
        print(f"⚠️ 差异超过 {WARN_DISTANCE_M}m，地理编码可能不准")
        print(f"   建议改用【地点检索】坐标：{poi_lng:.6f}, {poi_lat:.6f}")
    else:
        print("✅ 两者接近，坐标可信")
        print(f"   推荐坐标：{poi_lng:.6f}, {poi_lat:.6f}")
    print("-" * 64)


def main() -> None:
    address = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADDRESS
    city = sys.argv[2] if len(sys.argv) > 2 else "东莞市"
    asyncio.run(resolve(address, city))


if __name__ == "__main__":
    main()
