"""权威名录抽样校验：检验百度 POI 检索的召回率。

为什么要做这件事：
    项目的设施覆盖率、盲区率、健康度分数全部建立在百度 POI 检索之上。
    百度是**商业收录**，理论上可能漏掉真实存在的设施——一旦漏检，
    覆盖率就会虚低、盲区率会虚高，而报告本身看不出任何异常。
    所以必须引入一份**不依赖百度**的基准来交叉验证。

数据来源（政务公开，非商业地图服务）：
    `scripts/authority_benchmark/*.csv`，由 collect_authority_data.py 从
    东莞市医保局 / 教育局 / 民政局 / 市场监管局公开发布的文件采集后冻结。
    每条记录都带地址（学校除外，原表只有镇街，故按名称定位）。

校验方法（三步，全程只围绕「召回」这一个方向）：
    1. 用百度**地理编码**把权威名录里的设施地址解析成 BD09 坐标；
    2. 只保留落在检索半径内的记录——它们「本应」被地点检索发现；
    3. 调百度**地点检索**取该类别结果，按距离配对，统计命中 / 漏检。

    [注意] 配对以**名称**为主判据、位置为辅，原因见下（这是一次实测踩坑的教训）：
        最初只用「距离 ≤ 100 / 300 m」配对，得到的漏检距离密集落在
        372~536 m（莞城药店）、1024~1062 m（莞城小学）——这不是百度没收录，
        而是**地址地理编码只精确到路口**，与 POI 的建筑物入口坐标天然差几百米。
        改用名称配对后，同一批数据被判为「未覆盖」的条目大幅减少
        （实测数字见 docs/技术方案.md §4.5 与 authority_benchmark_result.json）。
        归一化规则与阈值见文件下方 GENERIC_TOKENS / NAME_MIN_COMMON。

        三种命中依据都会分别计数，读者可自行判断结论强度：
            name+distance  名称一致且位置也基本重合（最强）
            name           名称一致、位置有偏差（地址解析精度所致）
            distance       仅位置重合，名称写法差异过大（最弱）

    [注意] 反向结论不成立：名录本身不完整（药店只含医保定点、幼儿园只含公办、
       农贸市场只有星级），因此「百度有、名录无」**不能**算误检，
       脚本对此只展示不判定。

配额消耗（一次性，带磁盘缓存，重跑不重复消耗）：
    地理编码 ≈ 名录记录数（约 300 次，日配额 5000，压力小）
    地点检索 = 样例点位数 × 校验类别数（15 次，日配额 100，**最紧张**）
      → 故默认只跑 3 个内置样例点位、每类最多 2 页，与主流程口径一致。

用法（在 backend 目录下）：
    python scripts/authority_benchmark.py --dry-run   # 先看会消耗多少配额
    python scripts/authority_benchmark.py             # 正式跑（要 AK）
    python scripts/authority_benchmark.py --fresh     # 忽略磁盘缓存重跑
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_DIR / ".env")

from app.core import constants  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.samples import SAMPLE_LOCATIONS  # noqa: E402
from app.services.baidu_client import baidu_client  # noqa: E402
from app.services.geocoding import geocode  # noqa: E402
from app.services.poi import search_category  # noqa: E402
from app.utils.geo import haversine_distance  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent / "authority_benchmark"
RESULT_PATH = Path(__file__).resolve().parent / "authority_benchmark_result.json"
GEO_CACHE_PATH = BACKEND_DIR / ".authority_geocode_cache.json"
POI_CACHE_PATH = BACKEND_DIR / ".authority_poi_cache.json"

# 样例点位 → 所属镇街（权威名录按镇街组织，必须先归位再比对）
POINT_TOWN = {
    "东莞理工学院（松山湖校区）": "松山湖",
    "东莞理工学院（莞城校区）": "莞城",
    "东莞市虎门镇北栅行政小区": "虎门",
}

# 权威名录文件 → 本项目的设施类别
#   file: 文件名（不含 .csv）
#   category: 与服务层 FACILITY_CATEGORIES 一致
#   locate_by: address 用地址地理编码；name 用名称（学校名录无地址字段）
#   scope_note: 名录本身的覆盖范围，必须随结果一起呈现，否则会被误读为「全集」
BENCHMARKS = [
    {
        "file": "dongguan_pharmacy",
        "category": "药店",
        "locate_by": "address",
        "source": "东莞市医疗保障局·市内定点药店查询",
        "scope_note": "仅医保定点药店，非定点药店不在名录内",
    },
    {
        "file": "dongguan_kindergarten",
        "category": "幼儿园",
        "locate_by": "address",
        "source": "东莞市教育局·公办（集体办）幼儿园一览表",
        "scope_note": "仅公办/集体办幼儿园，不含民办",
    },
    {
        "file": "dongguan_school",
        "category": "小学",
        "locate_by": "name",
        "source": "东莞市教育局·义务教育标准化学校名单",
        "scope_note": "仅标准化学校，且原表无地址（按名称定位）",
    },
    {
        "file": "dongguan_elderly_care",
        "category": "养老",
        "locate_by": "address",
        "source": "东莞市民政局·在运营养老机构信息表",
        "scope_note": "在运营机构，样本量极小",
    },
    {
        "file": "dongguan_market",
        "category": "菜市场",
        "locate_by": "address",
        "source": "东莞市市场监督管理局·五星农贸市场名单",
        "scope_note": "全市约 451 个农贸市场，此名录仅 21 家五星市场",
    },
]

# ---------------------------------------------------------------------------
# 匹配口径
# ---------------------------------------------------------------------------
# 教训：最初只用「距离 ≤ 100/300 m」配对，结果莞城药店的漏检距离密集落在
#       372~536 m、莞城小学落在 1024~1062 m —— 这不是百度没收录，而是
#       **地址地理编码只精确到路口**，与 POI 的建筑物入口坐标天然差三四百米。
#       所以主判据必须是**名称**，距离只作辅助与兜底。
#
#   命中条件（任一成立即算命中）：
#     a) 距离 ≤ STRICT_MATCH_M：近到不可能是别家，作为兜底（名称写法差异很大时救回来）
#     b) 归一化名称的最长公共子串 ≥ NAME_MIN_COMMON 且占较短名比例 ≥ NAME_MIN_RATIO
#        例：名录「广东省东莞国药集团仁济堂药业有限公司莞城学院药店」
#            → 归一化「国药仁济堂莞城学院」；POI「东莞国药仁济堂莞城学院药店」
#            → 归一化「国药仁济堂莞城学院」，完全一致 → 命中
#        反例：同公司同镇的「…捷东药店」与「…长德药店」→ 公共子串仅「国药虎门」
#            = 4 字 < 5 且比例不达标 → 不命中（避免了连锁分店互相误配）
STRICT_MATCH_M = 100
NAME_MIN_COMMON = 5
NAME_MIN_RATIO = 0.6

# 归一化时剥离的通用词：公司后缀、行政前缀、业态词。
# 这些都是「同一家公司下面所有分店都有的部分」，保留它们只会掩盖真正的门店标识。
GENERIC_TOKENS = (
    "东莞市", "广东省", "东莞", "广东",
    "有限公司", "有限责任公司", "股份", "分公司", "公司", "集团", "连锁",
    "大药房", "药房", "药业", "医药", "药店", "药堂", "连锁店",
    "（个人独资）", "(个人独资)", "个人独资",
    "街道", "镇", "区",
)

_GEO_CACHE: dict[str, dict | None] = {}
_GEO_DIRTY = False
_GEO_CALLS = 0
_POI_CACHE: dict[str, list[dict]] = {}
_POI_DIRTY = False
_POI_CALLS = 0
_DRY_RUN = False
_DIAGNOSE = False


# ---------------------------------------------------------------------------
# 名称归一化与相似度
# ---------------------------------------------------------------------------
def _normalize_name(name: str) -> str:
    text = name
    for token in GENERIC_TOKENS:
        text = text.replace(token, "")
    return re.sub(r"[\s\-—·()（）\[\]【】,，.。、/\\]", "", text)


def _longest_common_substring(a: str, b: str) -> int:
    """最长公共子串长度（滚动数组，O(len(a)·len(b))，名称都很短）。"""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for ca in a:
        cur = [0] * (len(b) + 1)
        for j, cb in enumerate(b, 1):
            if ca == cb:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best


def _name_hit(auth_name: str, poi_name: str) -> bool:
    left, right = _normalize_name(auth_name), _normalize_name(poi_name)
    if not left or not right:
        return False
    common = _longest_common_substring(left, right)
    return common >= NAME_MIN_COMMON and common / min(len(left), len(right)) >= NAME_MIN_RATIO


# ---------------------------------------------------------------------------
# 地理编码磁盘缓存：地址解析结果与时间无关，值得长期保留
# ---------------------------------------------------------------------------
def _load_geo_cache(fresh: bool) -> None:
    global _GEO_CACHE
    if fresh or not GEO_CACHE_PATH.exists():
        _GEO_CACHE = {}
        return
    try:
        _GEO_CACHE = json.loads(GEO_CACHE_PATH.read_text(encoding="utf-8"))
        located = sum(1 for v in _GEO_CACHE.values() if v)
        print(f"地理编码缓存：{len(_GEO_CACHE)} 条（可定位 {located} 条）")
    except (OSError, ValueError):
        _GEO_CACHE = {}


def _save_geo_cache() -> None:
    global _GEO_DIRTY
    if _GEO_DIRTY and not _DRY_RUN:
        GEO_CACHE_PATH.write_text(
            json.dumps(_GEO_CACHE, ensure_ascii=False), encoding="utf-8"
        )
        _GEO_DIRTY = False


async def _locate(record: dict) -> dict | None:
    """把一条权威记录解析成 BD09 坐标。解析失败返回 None（不计入分母）。"""
    global _GEO_DIRTY, _GEO_CALLS

    query = record["query"]
    if query in _GEO_CACHE:
        cached = _GEO_CACHE[query]
        return dict(cached) if cached else None

    if _DRY_RUN:
        # 不触网：dry-run 下未缓存的记录按「未知」处理
        return None

    _GEO_CALLS += 1
    try:
        result = await geocode(query, city="东莞市")
    except Exception:
        result = None

    payload = (
        {"lng": result.lng, "lat": result.lat, "level": result.level}
        if result and result.lng
        else None
    )
    _GEO_CACHE[query] = payload
    _GEO_DIRTY = True
    return dict(payload) if payload else None


# ---------------------------------------------------------------------------
# 地点检索磁盘缓存：地点检索日配额只有 100 次，是本项目最紧的资源。
# 调匹配规则时反复跑同一批点位不该反复消耗配额，故这里也落盘。
# ---------------------------------------------------------------------------
def _load_poi_cache(fresh: bool) -> None:
    global _POI_CACHE
    if fresh or not POI_CACHE_PATH.exists():
        _POI_CACHE = {}
        return
    try:
        _POI_CACHE = json.loads(POI_CACHE_PATH.read_text(encoding="utf-8"))
        print(f"地点检索缓存：{len(_POI_CACHE)} 组结果")
    except (OSError, ValueError):
        _POI_CACHE = {}


def _save_poi_cache() -> None:
    global _POI_DIRTY
    if _POI_DIRTY and not _DRY_RUN:
        POI_CACHE_PATH.write_text(
            json.dumps(_POI_CACHE, ensure_ascii=False), encoding="utf-8"
        )
        _POI_DIRTY = False


async def _search_pois(lng: float, lat: float, category: str, radius: int) -> list[dict]:
    global _POI_CALLS, _POI_DIRTY

    key = f"{category}|{round(lng, 5)},{round(lat, 5)}|{radius}"
    if key in _POI_CACHE:
        return _POI_CACHE[key]
    if _DRY_RUN:
        return []

    _POI_CALLS += 1
    items = await search_category(lng, lat, category, radius=radius)
    pois = [
        {"name": p.name, "lng": p.lng, "lat": p.lat, "address": p.address} for p in items
    ]
    _POI_CACHE[key] = pois
    _POI_DIRTY = True
    return pois


async def _name_lookup(name: str) -> list[dict]:
    """按名称直查百度 POI 库（不限定位置）。

    用途：把「未覆盖」拆成两种完全不同的原因——
        · 百度库里有这家店，只是没进入我们的类目检索结果 → **是我们的检索口径问题**
          （类目检索每类最多 2 页 40 条，且按相关性而非距离排序，密集区域必然截断）
        · 百度库里也查不到 → 可能确实未收录，或该店已停业 / 名称写法差异过大
    不区分这两者就把责任推给数据源，是不诚实的。
    """
    global _POI_CALLS, _POI_DIRTY

    key = f"name|{name}"
    if key in _POI_CACHE:
        return _POI_CACHE[key]
    if _DRY_RUN:
        return []

    _POI_CALLS += 1
    data = await baidu_client.get(
        "/place/v2/search",
        {
            "query": name,
            "region": "东莞",
            "scope": 2,
            "page_size": 5,
            "page_num": 0,
        },
    )
    pois = [
        {
            "name": item.get("name") or "",
            "lng": (item.get("location") or {}).get("lng"),
            "lat": (item.get("location") or {}).get("lat"),
            "address": item.get("address") or "",
        }
        for item in (data.get("results") or [])
    ]
    _POI_CACHE[key] = pois
    _POI_DIRTY = True
    return pois


# ---------------------------------------------------------------------------
# 名录加载
# ---------------------------------------------------------------------------
def load_benchmark(spec: dict, town: str) -> list[dict]:
    path = DATA_DIR / f"{spec['file']}.csv"
    if not path.exists():
        return []

    with path.open(encoding="utf-8-sig", newline="") as fp:
        rows = list(csv.DictReader(fp))

    records = []
    for row in rows:
        if row.get("镇街", "").strip() != town:
            continue
        name = (row.get("名称") or "").strip()
        address = (row.get("地址") or "").strip()
        # 学校名录无地址 → 用名称定位；带上「东莞」前缀能显著提高解析成功率
        query = address if spec["locate_by"] == "address" and address else f"东莞市{name}"
        if name and query:
            records.append({"name": name, "address": address, "query": query})
    return records


# ---------------------------------------------------------------------------
# 配对与统计
# ---------------------------------------------------------------------------
def _best_gap(auth: dict, pois: list[dict]) -> tuple[float, str]:
    """返回权威记录到最近 POI 的距离及其名称。"""
    best = (float("inf"), "")
    for poi in pois:
        gap = haversine_distance(auth["lng"], auth["lat"], poi["lng"], poi["lat"])
        if gap < best[0]:
            best = (gap, poi["name"])
    return best


def _judge(auth: dict, pois: list[dict]) -> tuple[bool, str, float, str, str]:
    """判定一条权威记录是否被检索结果覆盖。

    Returns:
        (是否命中, 命中依据, 最近距离, 最近 POI 名, 名称命中的 POI 名)
    """
    nearest_gap, nearest_name = _best_gap(auth, pois)
    by_name = next(
        (p["name"] for p in pois if _name_hit(auth["name"], p["name"])), ""
    )

    if by_name and nearest_gap <= STRICT_MATCH_M:
        return True, "name+distance", nearest_gap, nearest_name, by_name
    if by_name:
        # 名称一致但坐标有偏差：地址地理编码只到路口，属正常情况
        return True, "name", nearest_gap, nearest_name, by_name
    if nearest_gap <= STRICT_MATCH_M:
        # 名称写法差异过大但位置几乎重合，仍判为命中（保守起见记下依据）
        return True, "distance", nearest_gap, nearest_name, ""
    return False, "", nearest_gap, nearest_name, ""


async def run_point(point: dict, town: str, specs: list[dict]) -> dict:
    lng, lat = point["lng"], point["lat"]
    print(f"\n{'=' * 78}\n{point['name']}（{town}）  {lng}, {lat}\n{'=' * 78}")

    categories: dict[str, dict] = {}

    for spec in specs:
        category = spec["category"]
        records = load_benchmark(spec, town)
        if not records:
            print(f"  [{category}] 权威名录无该镇街记录，跳过")
            continue

        # 1. 定位
        located: list[dict] = []
        for rec in records:
            coords = await _locate(rec)
            if coords:
                located.append({**rec, **coords})

        # 2. 只留检索半径内的 —— 它们才「本应」被检索到
        radius = settings.POI_SEARCH_RADIUS_M
        in_range = [
            r
            for r in located
            if haversine_distance(lng, lat, r["lng"], r["lat"]) <= radius
        ]
        if not in_range:
            print(
                f"  [{category}] 名录 {len(records)} 条 → 可定位 {len(located)} 条"
                f" → {radius} m 内 0 条，跳过"
            )
            continue

        # 3. 百度地点检索
        if _DRY_RUN:
            print(f"  [{category}] 检索半径内权威 {len(in_range)} 条（dry-run 不检索）")
            pois: list[dict] = []
        else:
            pois = await _search_pois(lng, lat, category, radius)

        by_method: dict[str, int] = {"name+distance": 0, "name": 0, "distance": 0}
        misses: list[dict] = []
        for rec in in_range:
            hit, method, gap, nearest_name, name_hit = _judge(rec, pois)
            if hit:
                by_method[method] += 1
            else:
                misses.append(
                    {
                        "name": rec["name"],
                        "address": rec["address"],
                        "nearest_poi": nearest_name,
                        "nearest_gap_m": round(gap, 1) if gap != float("inf") else None,
                    }
                )

        # 拆解未覆盖原因：百度库里有 → 我们的检索口径问题；库里也没有 → 未收录
        known_by_baidu = 0
        if _DIAGNOSE and misses:
            for miss in misses:
                if _DRY_RUN:
                    break
                hits = await _name_lookup(miss["name"])
                matched = next(
                    (p["name"] for p in hits if _name_hit(miss["name"], p["name"])), ""
                )
                miss["baidu_knows_it"] = bool(matched)
                miss["baidu_matched_name"] = matched
                known_by_baidu += 1 if matched else 0

        total = len(in_range)
        hit_total = sum(by_method.values())
        # 反向数量只作展示：名录不全，不能据此判定误检
        extra = max(0, len(pois) - hit_total)
        # 检索是否触到了分页上限（2 页 × 20 条）——触顶说明密集区域会漏
        capped = len(pois) >= constants.POI_PAGE_SIZE * constants.POI_MAX_PAGES

        categories[category] = {
            "source": spec["source"],
            "scope_note": spec["scope_note"],
            "authority_total": len(records),
            "authority_located": len(located),
            "authority_in_range": total,
            "baidu_poi": len(pois),
            "recall": round(hit_total / total, 4),
            "hits_by_method": by_method,
            "baidu_result_capped": capped,
            "baidu_only_count": extra,
            "uncovered_total": len(misses),
            "uncovered_but_in_baidu_db": known_by_baidu if _DIAGNOSE else None,
            "misses": misses,
        }

        print(
            f"  [{category}] 名录 {len(records)} → 可定位 {len(located)} → "
            f"{radius} m 内 {total} 条 | 百度检出 {len(pois)} 个"
            + ("（触到 40 条翻页上限）" if capped else "")
        )
        print(
            f"      召回率 {hit_total}/{total} = {hit_total / total:.1%}"
            f"（名称命中 {by_method['name']}、名称+位置 {by_method['name+distance']}、"
            f"仅位置 {by_method['distance']}）"
        )
        if _DIAGNOSE and misses:
            print(
                f"      未覆盖 {len(misses)} 条中，{known_by_baidu} 条**百度库里其实有**"
                f"（属我们的检索口径截断），{len(misses) - known_by_baidu} 条名称直查也查不到"
            )
        print(f"      来源：{spec['source']}（{spec['scope_note']}）")
        for miss in misses:
            gap = miss["nearest_gap_m"]
            gap_text = (
                f"最近类目 POI「{miss['nearest_poi']}」相距 {gap:.0f} m"
                if gap
                else "检索结果为空"
            )
            if _DIAGNOSE:
                if miss.get("baidu_knows_it"):
                    gap_text += f"；名称直查命中「{miss['baidu_matched_name']}」→ 口径截断"
                else:
                    gap_text += "；名称直查也未命中"
            print(f"      · 未覆盖：{miss['name']} —— {gap_text}")

    return {
        "point": point["name"],
        "town": town,
        "lng": lng,
        "lat": lat,
        "categories": categories,
    }


async def main() -> int:
    global _DRY_RUN, _DIAGNOSE

    parser = argparse.ArgumentParser(description="权威名录抽样校验（检验 POI 召回率）")
    parser.add_argument("--dry-run", action="store_true", help="只统计将消耗多少配额，不触网")
    parser.add_argument("--fresh", action="store_true", help="忽略磁盘缓存，重新请求")
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="对每条未覆盖记录再按名称直查一次，区分「百度没收录」与「我们检索口径截断」"
        "（每条多消耗 1 次地点检索配额）",
    )
    args = parser.parse_args()
    _DRY_RUN = args.dry_run
    _DIAGNOSE = args.diagnose

    if not settings.BAIDU_SERVER_AK and not _DRY_RUN:
        print("未配置 BAIDU_SERVER_AK，无法校验（可先跑 --dry-run 查看计划）")
        return 2

    _load_geo_cache(args.fresh)
    _load_poi_cache(args.fresh)
    specs = [s for s in BENCHMARKS if (DATA_DIR / f"{s['file']}.csv").exists()]
    print(f"校验类别：{'、'.join(s['category'] for s in specs)}")
    print(f"检索半径：{settings.POI_SEARCH_RADIUS_M} m（与主流程一致）")

    results = []
    for sample in SAMPLE_LOCATIONS:
        town = POINT_TOWN.get(sample["name"])
        if not town:
            continue
        results.append(await run_point(sample, town, specs))

    _save_geo_cache()
    _save_poi_cache()

    if _DRY_RUN:
        print("\n** dry-run：未消耗任何配额，也未写出结果文件 **")
        return 0

    RESULT_PATH.write_text(
        json.dumps(
            {
                "generated_at": "2026-10-16",
                "match_distance_m": STRICT_MATCH_M,
                "name_min_common": NAME_MIN_COMMON,
                "name_min_ratio": NAME_MIN_RATIO,
                "poi_radius_m": settings.POI_SEARCH_RADIUS_M,
                "geocode_calls": _GEO_CALLS,
                "poi_search_calls": _POI_CALLS,
                "points": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"\n{'=' * 78}")
    print(f"地理编码实际发起：{_GEO_CALLS} 次；地点检索实际发起：{_POI_CALLS} 次")
    print("（二者均已落盘缓存，重跑为 0，可离线复现）")
    print(f"明细已写入：{RESULT_PATH.relative_to(BACKEND_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
