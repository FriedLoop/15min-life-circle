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

router = APIRouter(prefix="/api", tags=["report"])


@router.post("/blindspot", response_model=BlindSpotResponse)
async def blindspot(data: BlindSpotRequest) -> BlindSpotResponse:
    """识别等时圈内的服务盲区。

    对 15 分钟可达范围内的每个网格点，判断其 1km 内
    能否找到菜市场、药店、小学等民生设施；找不到即为盲区。

    为节省配额，「直线距离 > 1km」或「< 625m」的点直接由几何性质定论，
    只有落在灰色地带（625~1000m）的点才调用真实路网算路。
    """
    return await blindspot_service.compute_blindspot(
        lng=data.lng,
        lat=data.lat,
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
    """
    return await report_service.compute_report(
        lng=data.lng,
        lat=data.lat,
        walk_minutes=data.walk_minutes,
        step_m=data.step_m,
        radius_m=data.radius_m,
        categories=data.categories,
        with_address=data.with_address,
    )
