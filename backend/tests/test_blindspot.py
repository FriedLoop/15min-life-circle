"""盲区判定：可达性得分、类别权重、判定类别的派生规则。

可达性得分直接决定热力图配色，语义是「可及类别的加权占比」——
刻意不使用距离线性衰减（那样会让覆盖率高的区域反而显示为红色）。
"""

import asyncio

import pytest

from app.core import constants
from app.schemas.models import CategoryDistance, IsochronePoint, IsochroneResponse
from app.services import blindspot as blindspot_service
from app.services.blindspot import _accessibility_score, _category_weight

KEY_CATS = list(constants.BLINDSPOT_CATEGORIES)

LNG = 113.881641
LAT = 22.909011


def _build_row(spec: dict[str, bool]) -> dict[str, CategoryDistance]:
    """按 {类别: 是否可及} 构造判定行。"""
    return {
        cat: CategoryDistance(
            category=cat,
            covered=covered,
            distance_m=0 if covered else None,
        )
        for cat, covered in spec.items()
    }


def test_key_categories_weigh_more_than_ordinary():
    ordinary = next(
        c
        for c in constants.FACILITY_CATEGORIES
        if c not in constants.BLINDSPOT_CATEGORIES
    )
    assert _category_weight(KEY_CATS[0]) > _category_weight(ordinary)


def test_accessibility_all_covered_is_one():
    row = _build_row({c: True for c in KEY_CATS})
    assert _accessibility_score(row, KEY_CATS) == 1.0


def test_accessibility_none_covered_is_zero():
    row = _build_row({c: False for c in KEY_CATS})
    assert _accessibility_score(row, KEY_CATS) == 0.0


def test_accessibility_partial_coverage_is_between():
    row = _build_row({"菜市场": True, "药店": True, "小学": False})
    score = _accessibility_score(row, KEY_CATS)
    assert 0.0 < score < 1.0


def test_accessibility_ignores_distance_when_covered():
    """可及即满分——距离远近不改变「已覆盖」这一事实。

    若改回距离线性衰减，900m 外的设施只得 0.1 分，
    覆盖率 100% 的区域会被画成红色，与事实矛盾。
    """
    near = _build_row({"菜市场": True, "药店": True, "小学": True})
    far = {
        cat: CategoryDistance(category=cat, covered=True, distance_m=900)
        for cat in KEY_CATS
    }

    assert _accessibility_score(near, KEY_CATS) == _accessibility_score(far, KEY_CATS)


def test_accessibility_empty_returns_zero():
    assert _accessibility_score({}, []) == 0.0


# ---------------------------------------------------------------------------
# 判定类别的派生规则
# ---------------------------------------------------------------------------
def _isochrone(*points: tuple[float, float, bool]) -> IsochroneResponse:
    return IsochroneResponse(
        center={"lng": LNG, "lat": LAT},
        walk_minutes=15,
        threshold_seconds=900,
        radius_m=1200,
        step_m=150,
        total_points=len(points),
        reachable_points=sum(1 for *_ignored, reachable in points if reachable),
        points=[
            IsochronePoint(
                lng=point_lng,
                lat=point_lat,
                duration=600 if reachable else 1200,
                reachable=reachable,
            )
            for point_lng, point_lat, reachable in points
        ],
    )


@pytest.fixture
def _no_network(monkeypatch):
    """不触网：POI 检索返回空集，且关闭缓存避免用例间串味。"""
    monkeypatch.setattr(blindspot_service.settings, "CACHE_ENABLED", False)

    async def fake_search(lng, lat, categories=None, radius=None):
        return {}, []

    monkeypatch.setattr(blindspot_service, "search_all_categories", fake_search)


def test_unselected_key_categories_are_not_added_back(monkeypatch, _no_network):
    """用户没勾选关键三类时，它们不该出现在结果里。

    回归用例：这里曾经无条件把关键三类补进检索集合，
    导致用户在界面上取消勾选后，报告里仍然冒出完整的三类——
    覆盖率、逐类盲区率、健康度全被悄悄扩回全量，筛选形同虚设。
    """
    chosen = ["公园", "银行"]
    response = asyncio.run(
        blindspot_service.compute_blindspot(
            LNG, LAT, categories=chosen, isochrone=_isochrone((LNG, LAT, True))
        )
    )

    assert set(response.categories) == set(chosen)
    # 判定集为空 → 没有可判定的类别，必须由这个字段表达「未判定」，
    # 而不是让 blind_points=0 冒充「没有盲区」
    assert response.judge_categories == []
    assert response.blind_points == 0


def test_judge_categories_are_intersection_with_selection(monkeypatch, _no_network):
    """勾选了部分关键三类时，只判定勾选到的那几类。"""
    chosen = ["药店", "公园"]
    response = asyncio.run(
        blindspot_service.compute_blindspot(
            LNG, LAT, categories=chosen, isochrone=_isochrone((LNG, LAT, True))
        )
    )

    assert set(response.categories) == set(chosen)
    assert response.judge_categories == ["药店"]


def test_explicit_judge_category_is_still_retrieved(monkeypatch, _no_network):
    """显式指定判定类别时仍要补进检索范围，否则拿不到数据无法判定。"""
    response = asyncio.run(
        blindspot_service.compute_blindspot(
            LNG,
            LAT,
            categories=["公园"],
            blindspot_categories=["药店"],
            isochrone=_isochrone((LNG, LAT, True)),
        )
    )

    assert set(response.categories) == {"公园", "药店"}
    assert response.judge_categories == ["药店"]
