"""可达性得分与类别权重的单元测试。

可达性得分直接决定热力图配色，语义是「可及类别的加权占比」——
刻意不使用距离线性衰减（那样会让覆盖率高的区域反而显示为红色）。
"""

from app.core import constants
from app.schemas.models import CategoryDistance
from app.services.blindspot import _accessibility_score, _category_weight

KEY_CATS = list(constants.BLINDSPOT_CATEGORIES)


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
