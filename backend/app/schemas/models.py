"""Pydantic 数据模型。

统一坐标系约定：所有对外接口一律使用 **BD09（百度经纬度）**，
与百度地图 JS API 点击地图得到的坐标一致，无需在前后端之间反复换算。
"""

from pydantic import BaseModel, Field


class CenterPoint(BaseModel):
    """中心点坐标。"""

    lng: float = Field(..., description="经度（BD09）")
    lat: float = Field(..., description="纬度（BD09）")


# ---------------------------------------------------------------------------
# POI 检索
# ---------------------------------------------------------------------------
class PoiItem(BaseModel):
    """单个兴趣点。"""

    name: str
    address: str = ""
    lng: float
    lat: float
    type: str = Field(default="", description="百度返回的原始 tag")
    category: str = Field(default="", description="归一化后的设施类别")
    distance_m: float | None = Field(default=None, description="到中心点的直线距离（米）")


class PoiSearchRequest(BaseModel):
    """POI 检索请求。"""

    lng: float = Field(..., description="经度（BD09）")
    lat: float = Field(..., description="纬度（BD09）")
    radius: int = Field(default=1000, ge=1, le=50000, description="检索半径（米）")
    categories: list[str] | None = Field(
        default=None, description="只返回指定类别；为空表示全部"
    )


class PoiSearchResponse(BaseModel):
    """POI 检索响应。"""

    center: CenterPoint
    radius: int
    total: int
    poi_list: list[PoiItem]
    category_counts: dict[str, int] = Field(
        default_factory=dict, description="各类别数量统计"
    )


# ---------------------------------------------------------------------------
# 地理编码
# ---------------------------------------------------------------------------
class GeocodeRequest(BaseModel):
    """地理编码请求：地址 -> 坐标。"""

    address: str = Field(..., description="结构化地址，如「东莞理工学院松山湖校区」")
    city: str = Field(default="", description="所在城市，可提升精度，如「东莞市」")


class GeocodeResponse(BaseModel):
    """地理编码响应。"""

    address: str
    lng: float
    lat: float
    confidence: int | None = Field(default=None, description="可信度，0 表示不可信")
    level: str = Field(default="", description="地址类型，如「大学」")


class ReverseGeocodeRequest(BaseModel):
    """逆地理编码请求：坐标 -> 地址。"""

    lng: float
    lat: float


class ReverseGeocodeResponse(BaseModel):
    """逆地理编码响应。"""

    formatted_address: str = ""
    province: str = ""
    city: str = ""
    district: str = ""
    lng: float
    lat: float
