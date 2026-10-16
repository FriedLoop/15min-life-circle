"""API 与「单端口部署」的冒烟测试。

重点守护一个曾踩过的坑：根路径 "/" 必须返回前端页面，而不能被后端路由截走
——否则评审按 README 访问 http://localhost:8000 只能看到一段 JSON，
会误判项目没有跑起来。
"""

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health_endpoint_reports_ok():
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["walk_minutes"] > 0


def test_root_serves_frontend_page():
    """根路径必须返回前端 HTML，而不是 JSON（单端口部署的约定）。"""
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<html" in response.text.lower()


def test_static_index_is_served():
    """显式访问 /index.html 同样应返回前端页面。"""
    response = client.get("/index.html")

    assert response.status_code == 200
    assert "<html" in response.text.lower()


def test_report_endpoint_forwards_coord_type_and_coarse_grid(monkeypatch):
    """接口层必须把 coord_type 与 coarse_grid 透传到服务层，并回传配额实证字段。

    这条用例守护的是「前端界面上的开关确实接到了后端」：
    coord_type 若不生效，GCJ02 坐标会被当 BD09 用，结论整体平移数百米；
    coarse_grid 若不生效，用户以为省了算路，实际仍是单级网格。
    """
    from app.schemas.models import (
        BlindSpotResponse,
        CenterPoint,
        IsochronePoint,
        IsochroneResponse,
        ReportResponse,
    )
    from app.services import report as report_service

    captured: dict = {}

    isochrone = IsochroneResponse(
        center=CenterPoint(lng=113.88, lat=22.90),
        walk_minutes=15,
        threshold_seconds=900,
        radius_m=1200,
        step_m=150,
        total_points=197,
        reachable_points=63,
        points=[IsochronePoint(lng=113.88, lat=22.90, duration=100, reachable=True)],
        strategy="coarse",
        coarse_step_m=450,
        routed_points=125,
        interpolated_points=72,
    )
    blindspot = BlindSpotResponse(
        center=CenterPoint(lng=113.88, lat=22.90),
        categories=["药店"],
        judge_categories=["药店"],
        threshold_m=1000,
        total_points=1,
        blind_points=0,
        points=[],
        category_coverage={"药店": 1.0},
        category_counts={"药店": 1},
    )

    async def fake_report(**kwargs):
        captured.update(kwargs)
        return ReportResponse(
            center=CenterPoint(lng=113.88, lat=22.90),
            walk_minutes=15,
            isochrone=isochrone,
            blindspot=blindspot,
            health_score=88.0,
        )

    monkeypatch.setattr(report_service, "compute_report", fake_report)

    response = client.post(
        "/api/report",
        json={
            "lng": 113.779678,
            "lat": 23.057248,
            "coord_type": "gcj02",
            "coarse_grid": True,
        },
    )

    assert response.status_code == 200
    # 请求侧：GCJ02 必须先转成 BD09，不能原样当 BD09 分析
    assert captured["lng"] != 113.779678
    assert captured["coarse"] is True

    body = response.json()
    assert body["isochrone"]["strategy"] == "coarse"
    assert body["isochrone"]["routed_points"] == 125
    assert body["isochrone"]["interpolated_points"] == 72


def test_report_endpoint_rejects_unknown_coord_type():
    """未知坐标系必须被参数校验拦下，而不是悄悄按 BD09 处理。"""
    response = client.post(
        "/api/report",
        json={"lng": 113.88, "lat": 22.90, "coord_type": "mars"},
    )

    assert response.status_code == 422


def test_placeholder_ak_is_reported_as_unconfigured(monkeypatch):
    """模板占位符必须报告为「未配置」，不能显示「已就绪」。

    端到端回归：`.env.example` 里的 `your_baidu_server_ak_here` 是非空字符串，
    若只做非空判断，使用者忘填 AK 时界面会显示「后端已就绪」，
    但每一个分析请求都会失败——"说好了却报错"是最难自查的一类问题。
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "BAIDU_SERVER_AK", "your_baidu_server_ak_here")
    monkeypatch.setattr(settings, "BAIDU_BROWSER_AK", "your_baidu_browser_ak_here")

    health = client.get("/api/health").json()
    assert health["ak_configured"] is False
    assert health["browser_ak_configured"] is False

    page_config = client.get("/api/config").json()
    assert page_config["backend_ready"] is False
    # 浏览器端 AK 单独判定：缺它会导致地图白屏而不是接口报错
    assert page_config["browser_ready"] is False


def test_browser_ak_is_judged_separately_from_server_ak(monkeypatch):
    """只配了服务端 AK 时，仍要明确告知地图不可用。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "BAIDU_SERVER_AK", "Ab3Kd9XmQ2Lp7Rs1Zt5Yv8Nc")
    monkeypatch.setattr(settings, "BAIDU_BROWSER_AK", "")

    page_config = client.get("/api/config").json()
    assert page_config["backend_ready"] is True
    assert page_config["browser_ready"] is False
