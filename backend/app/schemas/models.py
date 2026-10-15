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


# ---------------------------------------------------------------------------
# 等时圈
# ---------------------------------------------------------------------------
class IsochronePoint(BaseModel):
    """单个网格点的可达性结果。

    注意：前端热力图**不是**用这里的 duration 着色，而是用
    BlindSpotPoint.accessibility（设施可达性）。duration 只用于判定
    reachable，以及在降级/诊断场景中展示。
    """

    lng: float
    lat: float
    duration: int | None = Field(
        default=None, description="步行耗时（秒）；None 表示该点算路失败"
    )
    distance_m: int | None = Field(default=None, description="路网距离（米）")
    reachable: bool = Field(default=False, description="是否在时间阈值内可达")


class IsochroneRequest(BaseModel):
    """等时圈计算请求。"""

    lng: float = Field(..., description="中心点经度（BD09）")
    lat: float = Field(..., description="中心点纬度（BD09）")
    walk_minutes: int = Field(
        default=15, ge=1, le=60, description="步行时间阈值（分钟）"
    )
    step_m: int | None = Field(
        default=None,
        ge=50,
        le=1000,
        description="网格间隔（米）；为空取配置 GRID_STEP_M（默认 150）",
    )
    radius_m: int | None = Field(
        default=None, ge=100, le=5000, description="网格覆盖半径（米）；为空取配置值"
    )


class IsochroneResponse(BaseModel):
    """等时圈计算响应。"""

    center: CenterPoint
    walk_minutes: int
    threshold_seconds: int
    radius_m: int
    step_m: int
    total_points: int = Field(..., description="参与计算的网格点总数")
    reachable_points: int = Field(..., description="阈值内可达的点数")
    failed_points: int = Field(default=0, description="算路失败的点数")
    points: list[IsochronePoint]
    degraded: bool = Field(default=False, description="是否为降级估算结果")
    cached: bool = Field(default=False, description="结果是否来自缓存（未消耗配额）")
    message: str = Field(default="", description="降级或异常说明")


# ---------------------------------------------------------------------------
# 盲区识别
# ---------------------------------------------------------------------------
class CategoryDistance(BaseModel):
    """单个设施类别的距离判定结果。"""

    category: str
    distance_m: float | None = Field(
        default=None, description="到最近设施的距离（米）：优先路网，其次直线估算"
    )
    straight_m: float | None = Field(default=None, description="直线距离（米）")
    road_m: float | None = Field(
        default=None, description="路网距离（米）；仅灰色地带精算后才会有值"
    )
    covered: bool = Field(default=False, description="阈值内是否可及该类设施")
    precise: bool = Field(default=False, description="distance_m 是否为真实路网距离")


class BlindSpotPoint(BaseModel):
    """单个可达点的盲区判定与可达性结果。"""

    lng: float
    lat: float
    blind: bool = Field(default=False, description="是否为服务盲区（存在任一缺失类别）")
    missing_categories: list[str] = Field(default_factory=list)
    categories: dict[str, CategoryDistance] = Field(default_factory=dict)
    accessibility: float = Field(
        default=0.0,
        description="综合设施可达性得分 0~1，1 表示最便利。"
        "热力图据此着色：绿=可达性好，红=配套匮乏",
    )


class BlindSpotRequest(BaseModel):
    """盲区识别请求。"""

    lng: float = Field(..., description="中心点经度（BD09）")
    lat: float = Field(..., description="中心点纬度（BD09）")
    categories: list[str] | None = Field(
        default=None, description="检索并统计覆盖率的类别；为空表示全部"
    )
    blindspot_categories: list[str] | None = Field(
        default=None,
        description="用于判定盲区的类别；为空则取赛题点名的三类（菜市场/药店/小学）。"
        "与 categories 分开，是因为用全部 10 类判定时，"
        "养老这类普遍稀缺的设施会把盲区率推向 100%，失去区分度",
    )
    threshold_m: int = Field(default=1000, ge=100, le=5000, description="判定阈值（米）")
    walk_minutes: int = Field(default=15, ge=1, le=60, description="生活圈时间阈值")


class BlindSpotResponse(BaseModel):
    """盲区识别响应。"""

    center: CenterPoint
    categories: list[str] = Field(..., description="参与覆盖率统计的类别")
    judge_categories: list[str] = Field(
        default_factory=list, description="实际用于判定「是否盲区」的类别"
    )
    threshold_m: int
    total_points: int = Field(..., description="参与判定的可达点数")
    blind_points: int = Field(..., description="被判定为盲区的点数")
    points: list[BlindSpotPoint]
    category_coverage: dict[str, float] = Field(
        default_factory=dict, description="各类设施覆盖率 0~1"
    )
    category_counts: dict[str, int] = Field(
        default_factory=dict, description="检索范围内各类设施数量"
    )
    failed_categories: list[str] = Field(
        default_factory=list,
        description="检索失败的类别（如被限流）。非空时其覆盖率不可信，需重试",
    )
    blind_levels: dict[str, int] = Field(
        default_factory=dict,
        description="盲区分级统计：light=缺1类 / medium=缺2类 / severe=缺≥3类"
        "（判定类别默认仅菜市场/药店/小学三类，故 severe 即三类全缺）",
    )
    precise_calls: int = Field(default=0, description="灰色地带实际发起的路网精算次数")
    cached: bool = Field(default=False, description="结果是否来自缓存")


# ---------------------------------------------------------------------------
# 综合体检报告
# ---------------------------------------------------------------------------
class ReportRequest(BaseModel):
    """体检报告请求。"""

    lng: float = Field(..., description="中心点经度（BD09）")
    lat: float = Field(..., description="中心点纬度（BD09）")
    walk_minutes: int = Field(default=15, ge=1, le=60, description="步行时间阈值（分钟）")
    step_m: int | None = Field(
        default=None,
        ge=50,
        le=600,
        description="网格间隔（米）。越小边界越精细，但算路调用量按平方增长。"
        "为空取默认值 150",
    )
    radius_m: int | None = Field(
        default=None, ge=300, le=5000, description="网格覆盖半径（米），为空取默认值"
    )
    categories: list[str] | None = None
    with_address: bool = Field(
        default=True, description="是否调用逆地理编码获取地址（消耗 1 次配额）"
    )


class ReportResponse(BaseModel):
    """15分钟生活圈体检报告。"""

    center: CenterPoint
    address: str = Field(default="", description="中心点的结构化地址")
    walk_minutes: int
    isochrone: IsochroneResponse = Field(..., description="等时圈计算结果")
    poi_counts: dict[str, int] = Field(
        default_factory=dict, description="各类设施数量"
    )
    pois: list[PoiItem] = Field(
        default_factory=list, description="检索到的设施点位，供地图直接标注展示"
    )
    coverage: dict[str, float] = Field(
        default_factory=dict, description="各类设施覆盖率 0~1"
    )
    blindspot: BlindSpotResponse = Field(..., description="盲区识别结果")
    health_score: float = Field(default=0.0, description="生活圈健康度评分 0~100")
    score_detail: dict[str, float] = Field(
        default_factory=dict, description="各类别的得分明细（0~100）"
    )
    cached: bool = Field(default=False, description="结果是否来自缓存")
