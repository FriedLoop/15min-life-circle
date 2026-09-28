"""POI 检索服务。

配额策略：
    个人开发者「地点检索」日配额仅 100 次，是本项目的最大瓶颈。
    百度圆形区域检索支持用 $ 分隔的多关键字并集检索（最多 10 个），
    因此把 10 类民生设施合并为 **一次请求**，
    再由 classify_poi() 按名称/tag 归一化到具体类别。
    原本每分析一个点位需要 3~6 次检索，现在只需 1~3 次。
"""

from app.core import constants
from app.schemas.models import PoiItem, PoiSearchResponse
from app.services.baidu_client import baidu_client
from app.utils.geo import haversine_distance


def classify_poi(name: str, tag: str = "") -> str:
    """把 POI 归一化到民生设施类别。

    并集检索返回的结果是混在一起的，需要按关键词归类。
    匹配顺序即 constants.FACILITY_CATEGORIES 的定义顺序，
    越具体的类别排得越靠前（如「小学」先于「药店」），避免误判。
    """
    text = f"{name or ''}{tag or ''}"
    for category, keywords in constants.FACILITY_CATEGORIES.items():
        if any(keyword in text for keyword in keywords):
            return category
    return "其他"


def _extract(item: dict, center_lng: float, center_lat: float, radius: int) -> PoiItem | None:
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
        category=classify_poi(name, tag),
        distance_m=round(distance, 1),
    )


async def search_nearby(
    lng: float,
    lat: float,
    radius: int = 1000,
    categories: list[str] | None = None,
) -> PoiSearchResponse:
    """检索中心点周边全部民生设施。

    Args:
        lng / lat: 中心点（BD09）
        radius: 检索半径（米）
        categories: 只保留指定类别；为空表示全部

    Raises:
        BaiduApiError: 接口调用失败或配额耗尽。
    """
    raw_items: list[dict] = []

    # 单次最多返回 20 条，翻页会额外消耗配额，因此设上限
    for page in range(constants.POI_MAX_PAGES):
        data = await baidu_client.get(
            "/place/v2/search",
            {
                "query": constants.POI_QUERY,
                "location": f"{lat},{lng}",
                "radius": radius,
                "scope": 2,  # 返回 detail_info，才拿得到 tag 用于分类
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
        parsed = _extract(item, lng, lat, radius)
        if parsed is None:
            continue
        if categories and parsed.category not in categories:
            continue
        pois.append(parsed)

    # 按距离由近到远排序，便于前端展示与盲区算法取最近设施
    pois.sort(key=lambda p: p.distance_m or 0.0)

    counts: dict[str, int] = {}
    for poi in pois:
        counts[poi.category] = counts.get(poi.category, 0) + 1

    return PoiSearchResponse(
        center={"lng": lng, "lat": lat},
        radius=radius,
        total=len(pois),
        poi_list=pois,
        category_counts=counts,
    )
