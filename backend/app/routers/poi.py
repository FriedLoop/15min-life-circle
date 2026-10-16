"""POI 检索路由。"""

from fastapi import APIRouter

from app.schemas.models import PoiSearchRequest, PoiSearchResponse
from app.services import poi as poi_service
from app.services.coordconv import to_bd09_point

router = APIRouter(prefix="/api", tags=["poi"])


@router.post("/get_poi", response_model=PoiSearchResponse)
async def get_poi(data: PoiSearchRequest) -> PoiSearchResponse:
    """检索中心点周边的民生设施。

    内部**按类别分别检索**（10 类共 10 次地点检索请求），而非一次并集检索——
    并集检索只返回前 20 条且按相关性排序，会把菜市场、小学这类稀疏类别挤掉。
    返回值已按类别归一化，并附各类别数量统计。

    coord_type 非 bd09 时会先把输入坐标转换为 BD09。
    """
    lng, lat = to_bd09_point(data.lng, data.lat, data.coord_type)
    return await poi_service.search_nearby(
        lng=lng,
        lat=lat,
        radius=data.radius,
        categories=data.categories,
    )
