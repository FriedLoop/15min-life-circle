"""健康检查与运行态信息。"""

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(tags=["health"])

# 注意：这里刻意不注册 "/" 路由。
# main.py 把前端静态目录挂载在 "/" 上，而 Starlette 按注册顺序匹配路由；
# 一旦在此注册 "/"，根路径会被先截走，评审访问 http://localhost:8000
# 就只能看到一段 JSON、看不到应用界面。存活探测请用 /api/health。


@router.get("/api/health")
def health() -> dict:
    """健康检查，同时暴露关键配置是否已就绪。"""
    return {
        "status": "ok",
        "ak_configured": bool(settings.BAIDU_SERVER_AK),
        "walk_minutes": settings.WALK_MINUTES,
    }
