"""15分钟生活圈 API 入口。

启动方式（在 backend 目录下）：
    uvicorn main:app --reload --port 8000
"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.routers import config, geocode, health, isochrone, poi, report
from app.services.baidu_client import BaiduApiError

app = FastAPI(
    title="15分钟生活圈 API",
    description="基于百度地图开放能力的 15 分钟步行等时圈智能体检与规划助手",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(BaiduApiError)
async def baidu_api_error_handler(request: Request, exc: BaiduApiError) -> JSONResponse:
    """统一翻译百度接口错误。

    - 接口返回非 0 状态码（参数错误、配额超限、AK 无效）→ 400
    - 网络异常 / AK 未配置 → 503，提示检查配置
    """
    status_code = 400 if exc.status is not None else 503
    return JSONResponse(status_code=status_code, content={"detail": exc.message})


app.include_router(health.router)
app.include_router(config.router)
app.include_router(poi.router)
app.include_router(geocode.router)
app.include_router(isochrone.router)
app.include_router(report.router)

# 挂载前端页面：由后端同时提供静态文件，实现「单端口部署」。
# 评审只需访问 http://localhost:8000 即可看到完整应用，不必另起静态服务。
# 注意：必须放在所有 API 路由注册之后，否则会遮蔽 /api/* 路径。
_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if _FRONTEND_DIR.is_dir():
    app.mount(
        "/",
        StaticFiles(directory=str(_FRONTEND_DIR), html=True),
        name="frontend",
    )
