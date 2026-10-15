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
