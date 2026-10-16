"""全局配置。

所有敏感信息（如百度地图 AK）一律通过环境变量注入，
绝不硬编码进代码库，以保证仓库可直接开源。
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env 固定读取 backend/.env，避免受启动工作目录影响
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

# 模板里用于提示"此处填写"的写法。真实百度 AK 是随机字母数字串，
# 不会以 your 开头、不含尖括号、也不会全是 x/下划线，因此下面这几条不会误判。
_UNFILLED_PREFIXES = ("your", "your_", "your-")
_UNFILLED_SUBSTRINGS = ("填入", "填写", "替换", "placeholder", "改成")


def _looks_unfilled(value: str) -> bool:
    """判断某个配置值是否仍是模板占位符（或为空）。

    存在的意义：`.env.example` 里的占位符非空，若只做非空判断，
    使用者忘填时界面会显示"已就绪"，却在每个请求上失败——这类
    "说好了却报错"的问题最难自查，所以要提前识别。
    """
    text = (value or "").strip()
    if not text:
        return True
    lowered = text.lower()
    if lowered.startswith(_UNFILLED_PREFIXES):
        return True
    if any(char in text for char in "<>{}"):
        return True
    # 形如 xxx / xxx_xxx / ---- 的纯占位
    if set(lowered) <= set("x_-·. "):
        return True
    return any(word in text for word in _UNFILLED_SUBSTRINGS)


class Settings(BaseSettings):
    """应用配置，字段名即环境变量名。"""

    # 百度地图服务端 AK（Web 服务 API：地点检索 / 批量算路 / 地理编码）
    BAIDU_SERVER_AK: str = ""
    # 百度地图浏览器端 AK（前端 JS API，必须在控制台配置 Referer 白名单）
    BAIDU_BROWSER_AK: str = ""

    BAIDU_API_BASE: str = "https://api.map.baidu.com"

    # HTTP 行为：个人开发者并发上限为 3，超出会被限流
    HTTP_TIMEOUT: float = 10.0
    HTTP_MAX_CONCURRENCY: int = 3
    HTTP_RETRIES: int = 2

    # 结果缓存：避免重复查询同一位置反复消耗配额
    # 批量算路日配额 5000 条，单次等时圈约 113 条，调试阶段极易耗尽
    CACHE_ENABLED: bool = True
    CACHE_TTL_SECONDS: int = 3600
    CACHE_MAX_SIZE: int = 64
    # 坐标量化粒度（米）：邻近坐标视为同一位置，避免拖动地图产生大量近似缓存键
    CACHE_COORD_PRECISION_M: int = 50

    # 等时圈参数（阶段2）
    WALK_MINUTES: int = 15
    # 步行速度（m/s）。实测反推（莞城老城区，2026-09-28）：
    #   百度步行算路采用固定速度 ≈1.17 m/s（三样本反推 1.170~1.174，高度一致）
    # 该值不是「随便取的步行常识值」：分级网格的剪枝推理要求
    # WALK_SPEED_MPS ≥ 算路接口的实际速度，取 1.17 与实测对齐，误差由
    # GRID_STRATEGY_MARGIN 兜底（详见 services/isochrone.py 的剪枝推导）。
    WALK_SPEED_MPS: float = 1.17
    # 网格覆盖半径。实测依据（莞城老城区，2026-09-28）：
    #   → 15 分钟(900s) 可走约 1053m 路网距离
    #   → 实测绕行系数 1.33~1.58，对应直线半径约 670~790m；理想直路可达 1053m
    #   取 1200m 覆盖最坏情况并留余量，比原设 1500m 省约 36% 的无谓算路。
    ISOCHRONE_MAX_RADIUS_M: int = 1200
    # 主网格间隔（米）：决定等时圈边界精度（约 ±step/2）与算路调用量
    # 实测对比（松山湖校区，2026-09-29）：
    #   200m → 113 个网格点，可达 36 个，单次约 113 条路线
    #   150m → 197 个网格点，可达 63 个，单次约 197 条路线
    # 两者算出的可达面积仅差 1.4%（1.44 vs 1.42 km2），统计口径已收敛；
    # 加密网格主要提升热力图细腻度与边界精细度，故取 150m。
    # 配额紧张时可在 .env 中设 GRID_STEP_M=200 临时覆盖
    GRID_STEP_M: int = 150
    # 分级网格优化（coarse_grid=true 时启用，见 services/isochrone.py）。
    # 粗网格间隔（米），默认 450 = 3 × 主网格步长 150：
    # 运行时会向上取整到主网格步长的整数倍，使粗网格点恰好落在细网格点上，
    # 从而复用同一次算路结果、不产生重复调用（实测 450 与 600 算路量相同）。
    GRID_COARSE_STEP_M: int = 450
    # 剪枝边界余量（比例）。分级网格用几何性质代替部分算路：
    #   直线距离 ≤ 阈值 × 速度 / 绕行系数 × (1-margin) → 判为可达
    #   直线距离 >  阈值 × 速度            × (1+margin) → 判为不可达
    # 余量只吸收「算路实际速度略小于配置值」与取整误差，
    # **无法**兜住「路网被水域 / 围墙切断导致绕行系数远超 DETOUR_FACTOR」的情形：
    # 实测（松山湖校区，2026-10-15）直线 424~618 m 处存在真实耗时 1023~1480 s 的点，
    # 等效绕行系数 2.8。要消除这类误判只能把这些点也真实算路，
    # 或直接把 margin 提到 0.36 以上（实测会让省配额从 36.5% 掉到约 10%，不划算）。
    # 因此分级网格定位为「可接受的近似优化」，默认关闭。
    GRID_STRATEGY_MARGIN: float = 0.05
    # 单次批量算路请求的终点数。
    # 百度文档未公开硬上限（HarmonyOS 侧文档提到「起点数 × 终点数 < 100」），
    # 取 50 是安全值：197 个网格点只需 4 个请求，明显缩短等待时间。
    # 若报参数错误，可降回 20
    ROUTEMATRIX_BATCH_SIZE: int = 50
    # IDW（反距离加权）插值参数：用于把未采样网格点的耗时估算出来
    IDW_POWER: float = 2.0
    IDW_NEIGHBORS: int = 8

    # ---------------------------------------------------------------
    # 盲区判定参数（阶段3）
    # ---------------------------------------------------------------
    BLINDSPOT_DISTANCE_M: int = 1000

    # POI 检索半径：必须显著大于等时圈半径。
    # 原因：盲区判定的是「每个可达点周边 1km」，而最远可达点距中心约 764m，
    # 它 1km 内的设施可能位于距中心 1764m 处。若只按 1000m 检索，
    # 边缘点会被误判为盲区（远处明明有设施却没检索到）。
    POI_SEARCH_RADIUS_M: int = 2000

    # 灰色地带（625~1000m）精算时，对每个点取最近的几个候选设施做路网算路。
    # 取 3 个是精度与配额的平衡：只取 1 个可能因「直线最近≠路网最近」而误判
    GREY_ZONE_CANDIDATES: int = 3

    # 健康度评分权重：赛题重点关注的 3 类给更高权重
    CATEGORY_WEIGHT_KEY: float = 1.5
    CATEGORY_WEIGHT_NORMAL: float = 1.0
    # 路网绕行系数上限，用于盲区「直线初筛」：
    #   直线距离 × 该系数 < 阈值 → 判定必然不是盲区，免去昂贵的算路调用
    # 实测绕行系数（莞城老城区，2026-09-28）：
    #   正北 801.5m 直线 → 1068m 路网，系数 1.33
    #   正东 737.6m 直线 → 1169m 路网，系数 1.58
    #   西南 771.5m 直线 → 1153m 路网，系数 1.49
    # 取 1.6 留余量：系数偏小会把盲区误判为「非盲区」（漏报），后果比多算几个点严重
    DETOUR_FACTOR: float = 1.6

    # 允许跨域的来源，逗号分隔
    CORS_ORIGINS: str = "*"

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origins(self) -> list[str]:
        """把逗号分隔的 CORS 配置解析成列表。"""
        return [item.strip() for item in self.CORS_ORIGINS.split(",") if item.strip()]

    @property
    def server_ak_ready(self) -> bool:
        """服务端 AK 是否**真的可用**（而非只是非空）。

        只用 `bool(AK)` 判断会踩一个很难排查的坑：`.env.example` 里的占位符是
        `your_baidu_server_ak_here`，它非空，于是 /api/health 报告"已配置"、
        前端顶上显示"后端已就绪"，但随后**每一个分析请求都会失败**
        （百度返回 AK 参数错误）。使用者看到的是"界面说好了、一点就报错"。

        因此这里把占位符也视为「未配置」，让界面如实提示"后端缺 AK 配置"。
        判定只针对模板里的固定写法，不会误伤真实 AK（百度 AK 是随机字母数字串）。
        """
        return not _looks_unfilled(self.BAIDU_SERVER_AK)

    @property
    def browser_ak_ready(self) -> bool:
        """浏览器端 AK 是否可用。未配置时地图会白屏，需要提前告知。"""
        return not _looks_unfilled(self.BAIDU_BROWSER_AK)


@lru_cache
def get_settings() -> Settings:
    """单例读取配置，避免重复解析 .env。"""
    return Settings()


settings = get_settings()
