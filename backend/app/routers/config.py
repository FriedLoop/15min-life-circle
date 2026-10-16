"""前端配置路由。

把「浏览器端 AK」与「示例点位」下发给前端，解决两个问题：

    1. AK 不再硬编码在前端源码里。
       浏览器端 AK 本质上会暴露给访问者，但写在代码里会被仓库永久记录、
       任何人 clone 下来就能拿去用。改为运行时下发后，
       换 AK 只需改 .env，且仓库里不再出现密钥字符串。

    2. 示例点位集中管理，评审打开应用即可一键加载、复现分析结果。
"""

from fastapi import APIRouter

from app.core import constants
from app.core.config import settings
from app.core.samples import DEFAULT_CENTER, SAMPLE_LOCATIONS

router = APIRouter(prefix="/api", tags=["config"])


@router.get("/config")
async def get_config() -> dict:
    """下发前端配置（AK、默认中心点、示例点位）。"""
    return {
        "baidu_browser_ak": settings.BAIDU_BROWSER_AK,
        "default_center": {
            "lng": DEFAULT_CENTER["lng"],
            "lat": DEFAULT_CENTER["lat"],
        },
        "samples": SAMPLE_LOCATIONS,
        # 设施类别由后端统一定义，前端不再各维护一份，避免失配
        "categories": list(constants.FACILITY_CATEGORIES.keys()),
        "key_categories": list(constants.BLINDSPOT_CATEGORIES),
        # 占位符视为未配置：避免"界面显示已就绪、实际上每个请求都失败"
        "backend_ready": settings.server_ak_ready,
        # 浏览器端 AK 缺失时地图会白屏，必须让前端能提前提示，
        # 否则使用者只会看到一片空白地图，无从判断原因
        "browser_ready": settings.browser_ak_ready,
    }
