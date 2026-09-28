"""POI 检索路由。"""

from fastapi import APIRouter

from app.schemas.models import PoiSearchRequest, PoiSearchResponse
from app.services import poi as poi_service

router = APIRouter(prefix="/api", tags=["poi"])


@router.post("/get_poi", response_model=PoiSearchResponse)
async def get_poi(data: PoiSearchRequest) -> PoiSearchResponse:
    """检索中心点周边的民生设施。

    一次请求即可覆盖菜市场、药店、小学等 10 类设施（并集检索），
    返回值已按类别归一化，并附各类别数量统计。
    """
    return await poi_service.search_nearby(
        lng=data.lng,
        lat=data.lat,
        radius=data.radius,
        categories=data.categories,
    )
