"""报告聚合链路的测试（全部外部接口均被 mock）。

这一层存在的意义：
    捕获「变量名写错、参数漏传」这类只在运行时才暴露的错误。
    例如曾经出现过的 `NameError: name 'threshold' is not defined`——
    静态检查发现不了，只有真正把 compute_report 跑一遍才会暴露。

所有地图接口都在这里被替换，因此运行这些用例**不消耗任何 API 配额**。
"""

import asyncio

from app.core import constants
from app.schemas.models import (
    BlindSpotPoint,
    BlindSpotResponse,
    CategoryDistance,
    IsochronePoint,
    IsochroneResponse,
    PoiItem,
)
from app.services import report as report_service

LNG = 113.881641
LAT = 22.909011
ALL_CATS = list(constants.FACILITY_CATEGORIES.keys())


class _FakeGeo:
    formatted_address = "广东省东莞市（测试地址）"


def _fake_isochrone() -> IsochroneResponse:
    return IsochroneResponse(
        center={"lng": LNG, "lat": LAT},
        walk_minutes=15,
        threshold_seconds=900,
        radius_m=1200,
        step_m=150,
        total_points=1,
        reachable_points=1,
        points=[
            IsochronePoint(
                lng=LNG, lat=LAT, duration=120, distance_m=140, reachable=True
            )
        ],
    )


def _fake_blindspot() -> BlindSpotResponse:
    point = BlindSpotPoint(
        lng=LNG,
        lat=LAT,
        blind=False,
        missing_categories=[],
        categories={
            cat: CategoryDistance(category=cat, covered=True, distance_m=100)
            for cat in ALL_CATS
        },
        accessibility=1.0,
    )

    return BlindSpotResponse(
        center={"lng": LNG, "lat": LAT},
        categories=ALL_CATS,
        judge_categories=list(constants.BLINDSPOT_CATEGORIES),
        threshold_m=1000,
        total_points=1,
        blind_points=0,
        points=[point],
        category_coverage={cat: 1.0 for cat in ALL_CATS},
        category_counts={cat: 1 for cat in ALL_CATS},
        blind_levels={"light": 0, "medium": 0, "severe": 0},
        precise_calls=0,
    )


def _fake_pois() -> dict[str, list[PoiItem]]:
    return {
        "药店": [
            PoiItem(name="测试药店", lng=LNG + 0.0002, lat=LAT, category="药店")
        ],
        "小学": [
            PoiItem(name="测试小学", lng=LNG + 0.05, lat=LAT, category="小学")
        ],
    }


def test_compute_report_runs_end_to_end(monkeypatch):
    """跑通整条报告生成链路。

    这是本套测试中最重要的用例：任何变量未定义、参数漏传、
    mock 之外的逻辑错误，都会在这里立刻失败，
    而不必等到用户在网页上点按钮才发现。
    """
    monkeypatch.setattr(report_service.settings, "CACHE_ENABLED", False)

    async def fake_isochrone(*args, **kwargs):
        return _fake_isochrone()

    async def fake_blindspot(*args, **kwargs):
        return _fake_blindspot()

    async def fake_search(*args, **kwargs):
        return _fake_pois(), []

    async def fake_geocode(*args, **kwargs):
        return _FakeGeo()

    monkeypatch.setattr(report_service, "compute_isochrone", fake_isochrone)
    monkeypatch.setattr(report_service, "compute_blindspot", fake_blindspot)
    monkeypatch.setattr(report_service, "search_all_categories", fake_search)
    monkeypatch.setattr(report_service, "reverse_geocode", fake_geocode)

    result = asyncio.run(report_service.compute_report(LNG, LAT))

    assert result.center.lng == LNG
    assert result.center.lat == LAT
    assert result.walk_minutes == 15
    assert 0 <= result.health_score <= 100
    assert "测试地址" in result.address


def test_compute_report_without_address(monkeypatch):
    """关闭逆地理编码时不应报错，地址留空即可。"""
    monkeypatch.setattr(report_service.settings, "CACHE_ENABLED", False)

    async def fake_isochrone(*args, **kwargs):
        return _fake_isochrone()

    async def fake_blindspot(*args, **kwargs):
        return _fake_blindspot()

    async def fake_search(*args, **kwargs):
        return _fake_pois(), []

    monkeypatch.setattr(report_service, "compute_isochrone", fake_isochrone)
    monkeypatch.setattr(report_service, "compute_blindspot", fake_blindspot)
    monkeypatch.setattr(report_service, "search_all_categories", fake_search)

    result = asyncio.run(
        report_service.compute_report(LNG, LAT, with_address=False)
    )

    assert result.address == ""


def test_health_score_empty_input():
    assert report_service.compute_health_score({}) == (0.0, {})


def test_health_score_full_coverage_is_hundred():
    score, detail = report_service.compute_health_score({"菜市场": 1.0, "药店": 1.0})

    assert score == 100.0
    assert detail["菜市场"] == 100.0


def test_health_score_zero_coverage():
    score, _ = report_service.compute_health_score({"菜市场": 0.0})
    assert score == 0.0


def test_pois_inside_isochrone_filters_by_tolerance():
    reachable = [IsochronePoint(lng=LNG, lat=LAT, reachable=True)]
    near = PoiItem(name="近处药店", lng=LNG + 0.0002, lat=LAT, category="药店")
    far = PoiItem(name="远处小学", lng=LNG + 0.05, lat=LAT, category="小学")

    inside = report_service._pois_inside_isochrone([near, far], reachable, 100)

    assert near in inside
    assert far not in inside


def test_pois_inside_isochrone_without_reachable_points():
    poi = PoiItem(name="某设施", lng=LNG, lat=LAT, category="药店")
    assert report_service._pois_inside_isochrone([poi], [], 100) == []
