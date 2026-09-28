"""地理编码路由。"""

from fastapi import APIRouter

from app.schemas.models import (
    GeocodeRequest,
    GeocodeResponse,
    ReverseGeocodeRequest,
    ReverseGeocodeResponse,
)
from app.services import geocoding

router = APIRouter(prefix="/api", tags=["geocode"])


@router.post("/geocode", response_model=GeocodeResponse)
async def geocode(data: GeocodeRequest) -> GeocodeResponse:
    """地名/地址 -> BD09 坐标。

    样例点位（如「东莞理工学院松山湖校区」）应通过本接口换算，
    避免直接引用公开资料里的 GCJ02/WGS84 坐标造成数百米偏移。
    """
    return await geocoding.geocode(address=data.address, city=data.city)


@router.post("/reverse_geocode", response_model=ReverseGeocodeResponse)
async def reverse_geocode(data: ReverseGeocodeRequest) -> ReverseGeocodeResponse:
    """BD09 坐标 -> 结构化地址，用于报告中标注行政归属。"""
    return await geocoding.reverse_geocode(lng=data.lng, lat=data.lat)
