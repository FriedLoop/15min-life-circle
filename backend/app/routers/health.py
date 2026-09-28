"""健康检查与运行态信息。"""

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/")
def root() -> dict:
    """服务根路径，用于快速确认后端是否存活。"""
    return {"msg": "15分钟生活圈后端服务正常运行"}


@router.get("/api/health")
def health() -> dict:
    """健康检查，同时暴露关键配置是否已就绪。"""
    return {
        "status": "ok",
        "ak_configured": bool(settings.BAIDU_SERVER_AK),
        "walk_minutes": settings.WALK_MINUTES,
    }
