"""等时圈路由。"""

from fastapi import APIRouter

from app.schemas.models import IsochroneRequest, IsochroneResponse
from app.services import isochrone as isochrone_service
from app.services.coordconv import to_bd09_point

router = APIRouter(prefix="/api", tags=["isochrone"])


@router.post("/isochrone", response_model=IsochroneResponse)
async def isochrone(data: IsochroneRequest) -> IsochroneResponse:
    """计算基于真实路网的 N 分钟步行等时圈。

    采用「网格采样 + 步行批量算路」：对每个网格点取得真实步行耗时，
    而非画一个固定半径的圆——道路并非直线，绕行会显著压缩实际可达范围。

    响应字段用途：
        points        每个网格点的耗时与可达标记。两种热力图都用得到：
                      /api/report 用 blindspot.points[].accessibility 着「设施可达性」，
                      本接口的 duration 着「步行耗时」（前端可切换图层）
        degraded      为 true 表示算路不可用、结果系直线估算
        routed_points 实际消耗的算路条数，用于核对配额优化效果

    等时圈的边界不由本接口输出：前端按网格单元逐格描边还原真实外轮廓
    （凸包会抹平凹陷与缺口，故不采用，也不再返回）。

    配额：默认（coarse_grid=false）每个网格点消耗 1 条算路配额
    （step_m 为空时取配置 GRID_STEP_M，默认 150 → 197 点），
    请留意每日 5000 条的上限。coarse_grid=true 时先用几何性质剪掉
    「判定可达 / 判定不可达」的网格点，只对灰色地带算路，调用量见 routed_points；
    代价是**有损近似**（实测松山湖面积误差 7.94%），配额充足时用默认的 false。

    coord_type 非 bd09 时，会先把输入坐标转换为 BD09 再分析
    （WGS84/GCJ02 被当成 BD09 用会让结果整体平移数百米）。
    """
    lng, lat = to_bd09_point(data.lng, data.lat, data.coord_type)
    return await isochrone_service.compute_isochrone(
        lng=lng,
        lat=lat,
        walk_minutes=data.walk_minutes,
        step_m=data.step_m,
        radius_m=data.radius_m,
        coarse=data.coarse_grid,
    )
