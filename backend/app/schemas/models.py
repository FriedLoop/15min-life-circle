"""Pydantic 数据模型。

坐标系约定：
    所有对外接口的**输出**统一为 **BD09（百度经纬度）**，与百度地图 JS API
    点击地图得到的坐标一致，前后端之间无需反复换算。

    输入侧可通过 `coord_type` 声明来源坐标系（bd09 / gcj02 / wgs84），
    后端先转换为 BD09 再分析。这一步不能省：WGS84（GPS）或 GCJ02（高德/腾讯）
    的坐标若被当成 BD09 直接使用，会造成数百米整体偏移，
    等时圈形状与盲区结论会全部失真。
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

# 支持的输入坐标系；非 BD09 时由后端统一转换
CoordType = Annotated[
    Literal["bd09", "gcj02", "wgs84"],
    Field(
        description="输入坐标所属坐标系：bd09（默认，百度）、"
        "gcj02（高德/腾讯）、wgs84（GPS / GeoJSON）。非 BD09 时先转换为 BD09 再分析"
    ),
]


class CenterPoint(BaseModel):
    """中心点坐标。"""

    lng: float = Field(..., description="经度（BD09）")
    lat: float = Field(..., description="纬度（BD09）")


# ---------------------------------------------------------------------------
# 坐标转换
# ---------------------------------------------------------------------------
class ConvertPoint(BaseModel):
    """一个经纬度坐标点。"""

    lng: float
    lat: float


class ConvertRequest(BaseModel):
    """坐标转换请求：把其它坐标系坐标转为 BD09。"""

    points: list[ConvertPoint] = Field(
        ..., min_length=1, max_length=100, description="待转换坐标，单次最多 100 个"
    )
    coord_type: CoordType = "wgs84"
    use_api: bool = Field(
        default=True,
        description="是否调用百度 geoconv 接口（结果与百度地图渲染完全一致）；"
        "设为 false 则走本地算法，不消耗配额",
    )


class ConvertResponse(BaseModel):
    """坐标转换响应。"""

    source: str = Field(..., description="输入坐标系")
    target: str = Field(default="bd09", description="输出坐标系")
    method: str = Field(..., description="api=百度 geoconv 接口；local=本地算法兜底")
    points: list[ConvertPoint]
    message: str = Field(default="", description="降级或异常说明")


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
    coord_type: CoordType = "bd09"
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
    coord_type: CoordType = "bd09"


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

    两种着色口径都有数据来源：
        BlindSpotPoint.accessibility  设施可达性（「到了之后有没有东西用」）
        本类的 duration               步行耗时（「这段路走起来多费劲」）
    前端可在两种图层间切换，因此两个字段都必须如实回传。

    duration 在启用分级网格时可能是**插值估算值**（用 interpolated 标记）：
    几何性质已能定论的点不再消耗算路配额，其耗时由 IDW 插值补全。
    """

    lng: float
    lat: float
    duration: int | None = Field(
        default=None, description="步行耗时（秒）；None 表示该点算路失败"
    )
    distance_m: int | None = Field(default=None, description="路网距离（米）")
    reachable: bool = Field(default=False, description="是否在时间阈值内可达")
    interpolated: bool = Field(
        default=False,
        description="duration 是否为插值估算值（未消耗算路配额）。"
        "仅在分级网格策略下出现；等时圈边界判定不依赖该值",
    )


class IsochroneRequest(BaseModel):
    """等时圈计算请求。"""

    lng: float = Field(..., description="中心点经度（BD09）")
    lat: float = Field(..., description="中心点纬度（BD09）")
    coord_type: CoordType = "bd09"
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
    coarse_grid: bool = Field(
        default=False,
        description="是否启用「分级网格 + IDW 插值」：用几何性质剪枝、只对灰色地带"
        "做真实算路，可显著降低算路调用量（见响应的 routed_points）。"
        "注意这是**有损近似**：路网被水域/围墙切断时剪枝可能误判，"
        "实测松山湖面积误差 7.94%、5 个点判定相反；配额充足时请用默认的 false",
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
    # ---- 网格策略与配额实证：让「省了多少算路」可被直接核对 ----
    strategy: str = Field(
        default="single", description="网格策略：single=单级精细网格；coarse=分级网格+IDW 插值"
    )
    coarse_step_m: int = Field(default=0, description="粗网格间隔（米）；0 表示未启用分级网格")
    routed_points: int = Field(
        default=0, description="实际发起批量算路的终点数（含粗网格采样与灰色地带精算）"
    )
    interpolated_points: int = Field(
        default=0, description="耗时由 IDW 插值补全的网格点数（未消耗算路配额）"
    )


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
    coord_type: CoordType = "bd09"
    threshold_m: int = Field(default=1000, ge=100, le=5000, description="判定阈值（米）")
    walk_minutes: int = Field(default=15, ge=1, le=60, description="生活圈时间阈值")


class BlindSpotResponse(BaseModel):
    """盲区识别响应。"""

    center: CenterPoint
    categories: list[str] = Field(..., description="参与覆盖率统计的类别")
    judge_categories: list[str] = Field(
        default_factory=list,
        description="实际用于判定「是否盲区」的类别。**为空表示本次未做盲区判定**"
        "（用户把关键三类全取消勾选），此时 blind_points 恒为 0，"
        "调用方必须按此字段区分「没有盲区」与「未判定」",
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
    coord_type: CoordType = "bd09"
    coarse_grid: bool = Field(
        default=False,
        description="是否启用「分级网格 + IDW 插值」的算路配额优化。"
        "这是有损近似：剪枝依赖「路网 <= 绕行系数 × 直线距离」，"
        "在地形被切断处会误判（实测松山湖面积误差 7.94%）。"
        "真实算路量见 isochrone.routed_points",
    )
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
