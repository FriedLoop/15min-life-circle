"""全局配置。

所有敏感信息（如百度地图 AK）一律通过环境变量注入，
绝不硬编码进代码库，以保证仓库可直接开源。
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env 固定读取 backend/.env，避免受启动工作目录影响
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


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
    WALK_SPEED_MPS: float = 1.2
    # 网格覆盖半径。实测依据（莞城老城区，2026-09-28）：
    #   百度步行算路采用固定速度 ≈1.17 m/s（三样本反推 1.170~1.174，高度一致）
    #   → 15 分钟(900s) 可走约 1056m 路网距离
    #   → 实测绕行系数 1.33~1.58，对应直线半径约 670~790m；理想直路可达 1056m
    #   取 1200m 覆盖最坏情况并留余量，比原设 1500m 省约 36% 的无谓算路。
    ISOCHRONE_MAX_RADIUS_M: int = 1200
    # 主网格间隔（米）：决定等时圈边界精度（约 ±step/2）与算路调用量
    # 实测对比（松山湖校区，2026-09-29）：
    #   200m → 113 个网格点，可达 36 个，单次约 113 条路线
    #   150m → 197 个网格点，可达 63 个，单次约 197 条路线
    # 两者算出的可达面积仅差 1.4%（1.44 vs 1.42 km²），统计口径已收敛；
    # 加密网格主要提升热力图细腻度与边界精细度，故取 150m。
    # 配额紧张时可在 .env 中设 GRID_STEP_M=200 临时覆盖
    GRID_STEP_M: int = 150
    # 分级网格优化用的粗网格间隔（阶段5 的可选优化，暂未启用）
    GRID_COARSE_STEP_M: int = 500
    # 单次批量算路请求的终点数。百度未公开硬上限，取保守值 20；
    # 调大可减少请求数，跑通后可尝试调到 50
    ROUTEMATRIX_BATCH_SIZE: int = 20

    # 盲区判定参数（阶段3）
    BLINDSPOT_DISTANCE_M: int = 1000
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


@lru_cache
def get_settings() -> Settings:
    """单例读取配置，避免重复解析 .env。"""
    return Settings()


settings = get_settings()
