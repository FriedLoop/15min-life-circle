"""等时圈路由。"""

from fastapi import APIRouter

from app.schemas.models import IsochroneRequest, IsochroneResponse
from app.services import isochrone as isochrone_service

router = APIRouter(prefix="/api", tags=["isochrone"])


@router.post("/isochrone", response_model=IsochroneResponse)
async def isochrone(data: IsochroneRequest) -> IsochroneResponse:
    """计算基于真实路网的 N 分钟步行等时圈。

    采用「网格采样 + 步行批量算路」：对每个网格点取得真实步行耗时，
    而非画一个固定半径的圆——道路并非直线，绕行会显著压缩实际可达范围。

    响应字段用途：
        points  每个网格点的耗时，用于绘制热力图
        polygon 可达区域的凸包外轮廓，用于描边
        degraded 为 true 表示算路不可用、结果系直线估算

    注意：单次分析会消耗约「网格点数」条算路配额（默认约 137 条），
    请留意每日 5000 条的上限。
    """
    return await isochrone_service.compute_isochrone(
        lng=data.lng,
        lat=data.lat,
        walk_minutes=data.walk_minutes,
        step_m=data.step_m,
        radius_m=data.radius_m,
    )
