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

    # 等时圈参数（阶段2）
    WALK_MINUTES: int = 15
    WALK_SPEED_MPS: float = 1.2
    # 网格覆盖半径。实测依据（莞城老城区，2026-09）：
    #   直线 800m → 路网 1068~1169m（绕行系数 1.33~1.46），步行 910~998 秒
    #   故 15 分钟约可走 1080m 路网距离，对应直线半径仅 750~820m。
    #   取 1200m 留足余量（新区路网规整、绕行更小），比 1500m 少约 36% 的无谓算路。
    ISOCHRONE_MAX_RADIUS_M: int = 1200
    GRID_COARSE_STEP_M: int = 500
    GRID_FINE_STEP_M: int = 150

    # 盲区判定参数（阶段3）
    BLINDSPOT_DISTANCE_M: int = 1000
    # 路网绕行系数上限，用于盲区「直线初筛」：
    # 直线距离 × 该系数 < 阈值时，可判定必然不是盲区，从而免去昂贵的算路调用
    DETOUR_FACTOR: float = 1.4

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
