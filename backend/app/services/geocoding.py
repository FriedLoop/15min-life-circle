"""地理编码服务。

两个用途：
    1. 把「东莞理工学院松山湖校区」这类地名转成 BD09 坐标，
       省去手工查坐标的麻烦，也避免 GCJ02/WGS84 混用导致的偏移。
    2. 逆地理编码：点击地图后回显该点的行政归属，
       让体检报告能写清「东莞市松山湖 XX 社区」。

配额提示：逆地理编码日配额仅 300 次，不要在循环里调用。
"""

from app.schemas.models import GeocodeResponse, ReverseGeocodeResponse
from app.services.baidu_client import baidu_client


async def geocode(address: str, city: str = "") -> GeocodeResponse:
    """地址 -> 坐标（BD09）。"""
    params: dict[str, str] = {"address": address}
    if city:
        params["city"] = city

    data = await baidu_client.get("/geocoding/v3", params)
    result = data.get("result") or {}
    location = result.get("location") or {}

    return GeocodeResponse(
        address=address,
        lng=location.get("lng", 0.0),
        lat=location.get("lat", 0.0),
        confidence=result.get("confidence"),
        level=result.get("level") or "",
    )


async def reverse_geocode(lng: float, lat: float) -> ReverseGeocodeResponse:
    """坐标（BD09）-> 结构化地址。"""
    data = await baidu_client.get(
        "/reverse_geocoding/v3",
        {"location": f"{lat},{lng}", "extensions_poi": "0"},
    )

    result = data.get("result") or {}
    component = result.get("addressComponent") or {}

    return ReverseGeocodeResponse(
        formatted_address=result.get("formatted_address") or "",
        province=component.get("province") or "",
        city=component.get("city") or "",
        district=component.get("district") or "",
        lng=lng,
        lat=lat,
    )
