"""盲区识别与体检报告路由。"""

from fastapi import APIRouter

from app.schemas.models import (
    BlindSpotRequest,
    BlindSpotResponse,
    ReportRequest,
    ReportResponse,
)
from app.services import blindspot as blindspot_service
from app.services import report as report_service
from app.services.coordconv import to_bd09_point

router = APIRouter(prefix="/api", tags=["report"])


@router.post("/blindspot", response_model=BlindSpotResponse)
async def blindspot(data: BlindSpotRequest) -> BlindSpotResponse:
    """识别等时圈内的服务盲区。

    对 15 分钟可达范围内的每个网格点，判断其 1km 内
    能否找到菜市场、药店、小学等民生设施；找不到即为盲区。

    为节省配额，「直线距离 > 1km」或「< 625m」的点直接由几何性质定论，
    只有落在灰色地带（625~1000m）的点才调用真实路网算路。

    coord_type 非 bd09 时会先把输入坐标转换为 BD09 再分析。
    """
    lng, lat = to_bd09_point(data.lng, data.lat, data.coord_type)
    return await blindspot_service.compute_blindspot(
        lng=lng,
        lat=lat,
        categories=data.categories,
        blindspot_categories=data.blindspot_categories,
        threshold_m=data.threshold_m,
        walk_minutes=data.walk_minutes,
    )


@router.post("/report", response_model=ReportResponse)
async def report(data: ReportRequest) -> ReportResponse:
    """生成 15 分钟生活圈体检报告。

    聚合等时圈、设施覆盖统计、盲区识别，并给出 0~100 的健康度评分。
    这是本项目的最终输出，前端据此展示完整「体检报告」。

    注意：单次调用会同时消耗等时圈算路、POI 检索与盲区精算配额，
    结果已整体缓存，重复查询不再消耗。
    配额优化：coarse_grid=true 时等时圈改用「分级网格 + IDW 插值」，
    用几何性质剪掉判定可达 / 判定不可达的网格点，只对灰色地带算路；
    真实算路量见 isochrone.routed_points。这是有损近似（实测松山湖面积误差
    7.94%），配额充足时请用默认的 false。

    coord_type 非 bd09 时会先把输入坐标转换为 BD09 再分析。
    """
    lng, lat = to_bd09_point(data.lng, data.lat, data.coord_type)
    return await report_service.compute_report(
        lng=lng,
        lat=lat,
        walk_minutes=data.walk_minutes,
        step_m=data.step_m,
        radius_m=data.radius_m,
        categories=data.categories,
        with_address=data.with_address,
        coarse=data.coarse_grid,
    )
