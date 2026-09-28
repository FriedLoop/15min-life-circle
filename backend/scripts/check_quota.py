"""百度地图连通性与配额自检脚本。

开工前先跑一次，确认四件事：
    1. .env 里的 AK 已正确配置
    2. 地点检索的「多关键字并集检索」可用（这是节省配额的关键）
    3. 批量算路可用，且能返回步行耗时 duration
    4. 顺带拿到松山湖校区的准确 BD09 坐标

用法（在 backend 目录下）：
    python scripts/check_quota.py                        # 默认测松山湖校区
    python scripts/check_quota.py "东莞理工学院莞城校区"  # 换其它地点测

注意：本脚本会真实消耗少量配额（约 4 次检索 + 3 条算路）。
"""

import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# 让脚本在 backend 目录下也能读到 .env
load_dotenv(BACKEND_DIR / ".env")

import os  # noqa: E402  需要在 load_dotenv 之后读取

AK = os.getenv("BAIDU_SERVER_AK", "")
BASE = "https://api.map.baidu.com"
TIMEOUT = 10.0

# 合并检索的 10 类设施，与 app/core/constants.py 保持一致
QUERY = "$".join(
    [
        "菜市场", "药店", "小学", "幼儿园", "社区卫生服务中心",
        "超市", "公园", "银行", "养老院", "餐饮",
    ]
)

SAMPLE_ADDRESS = "东莞理工学院松山湖校区"


# 常见错误码解释，便于自助排查
ERROR_HINTS = {
    2: "参数错误，检查请求参数",
    210: "APP 服务被禁用：①应用未开通该服务 ②IP 白名单不匹配 ③AK 类型不符",
    211: "APP 不存在：AK 无效或已被删除",
    220: "APP Referer 校验失败：浏览器端 AK 的白名单未包含当前访问域名",
    240: "APP 被管理员禁用",
    302: "配额超限：当日调用次数已用完",
    401: "权限校验失败：服务端接口必须使用「服务端」类型的 AK",
}


def _get(path: str, params: dict) -> dict:
    """同步 GET，返回解析后的 JSON。"""
    resp = httpx.get(f"{BASE}{path}", params={**params, "ak": AK, "output": "json"},
                     timeout=TIMEOUT)
    return resp.json()


def _fail(data: dict) -> None:
    """统一打印失败原因与排查建议。"""
    status = data.get("status")
    print(f"  ✗ 失败：status={status}  message={data.get('message')}")
    hint = ERROR_HINTS.get(status)
    if hint:
        print(f"    → {hint}")


def check_geocoding(address: str) -> tuple[float, float]:
    """地理编码：拿到指定地点的 BD09 坐标。"""
    print(f"\n[1/3] 地理编码：{address}")
    data = _get("/geocoding/v3", {"address": address, "city": "东莞市"})
    if data.get("status") != 0:
        _fail(data)
        return 0.0, 0.0

    result = data["result"]
    loc = result["location"]
    lng, lat = loc["lng"], loc["lat"]
    print(f"  ✓ 坐标(BD09)：{lng:.6f}, {lat:.6f}")
    print(f"    可信度 confidence={result.get('confidence')} level={result.get('level')}")
    return lng, lat


def check_poi(lng: float, lat: float) -> None:
    """地点检索：验证 $ 并集检索是否真的能一次返回多类设施。"""
    print("\n[2/3] 地点检索（多关键字并集）")
    data = _get(
        "/place/v2/search",
        {
            "query": QUERY,
            "location": f"{lat},{lng}",
            "radius": 1000,
            "scope": 2,
            "page_size": 20,
            "page_num": 0,
        },
    )
    if data.get("status") != 0:
        _fail(data)
        return

    results = data.get("results", [])
    print(f"  ✓ 本页返回 {len(results)} 条，服务端总数 total={data.get('total')}")

    # 按 tag 粗分类，确认并集检索确实覆盖了多个类别
    tags: dict[str, int] = {}
    for item in results:
        tag = (item.get("detail_info") or {}).get("tag") or "无tag"
        tags[tag] = tags.get(tag, 0) + 1
    top = sorted(tags.items(), key=lambda kv: kv[1], reverse=True)[:6]
    print(f"    热点 tag：{top}")


def check_routematrix(lng: float, lat: float) -> None:
    """批量算路：确认能拿到步行耗时，这是等时圈算法的数据来源。"""
    print("\n[3/3] 批量算路（步行）")
    # 以中心点为起点，向三个方向各偏移 800 米作为终点
    destinations = [
        f"{lat + 0.0072:.6f},{lng:.6f}",  # 正北
        f"{lat:.6f},{lng + 0.0072:.6f}",  # 正东
        f"{lat - 0.0051:.6f},{lng - 0.0051:.6f}",  # 西南
    ]
    data = _get(
        "/routematrix/v2/walking",
        {"origins": f"{lat:.6f},{lng:.6f}", "destinations": "|".join(destinations)},
    )
    if data.get("status") != 0:
        _fail(data)
        print("    提示：「批量算路」属独立服务，需在控制台单独开通")
        return

    for i, item in enumerate(data.get("result", []), start=1):
        distance = (item.get("distance") or {}).get("value", 0)
        duration = (item.get("duration") or {}).get("value", 0)
        print(f"  ✓ 终点{i}：距离 {distance:.0f} 米，步行 {duration:.0f} 秒")
        if duration == 0:
            print("    ⚠ duration=0 表示该点无法算路，算法中必须剔除这类点")


def main() -> None:
    print("=" * 60)
    print("百度地图连通性自检")
    print("=" * 60)

    if not AK:
        print("\n✗ 未检测到 BAIDU_SERVER_AK")
        print("  请先复制 backend/.env.example 为 backend/.env 并填入 AK")
        sys.exit(1)

    print(f"\nAK 已加载：{AK[:8]}...{AK[-4:]}")

    address = sys.argv[1] if len(sys.argv) > 1 else SAMPLE_ADDRESS
    lng, lat = check_geocoding(address)
    if lng and lat:
        check_poi(lng, lat)
        check_routematrix(lng, lat)
        print("\n" + "-" * 60)
        print("样例点位坐标（可直接用于后续分析与报告）：")
        print(f"  {address}  lng={lng:.6f}  lat={lat:.6f}")
        print("-" * 60)

    print("\n本次自检约消耗：地理编码 1 次 + 地点检索 1 次 + 算路 3 条")


if __name__ == "__main__":
    main()
