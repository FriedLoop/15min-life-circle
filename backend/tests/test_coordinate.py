"""坐标系转换测试（纯数学，不触网、不消耗配额）。

重点验证三件事：
    1. 三种坐标系之间的往返转换可逆（否则分析结果会整体平移）
    2. 偏移量量级合理（GCJ02 相对 WGS84 在国内是百米级偏移）
    3. 境外坐标不被施加偏移（GCJ02 只在中国大陆生效）
"""

import pytest

from app.utils.coordinate import (
    bd09_to_gcj02,
    from_bd09,
    gcj02_to_bd09,
    gcj02_to_wgs84,
    out_of_china,
    to_bd09,
    wgs84_to_gcj02,
)
from app.utils.geo import haversine_distance

# 松山湖校区（BD09 基准）附近的一点，用于量级检查
LNG = 113.881641
LAT = 22.909011

# 往返转换允许的误差：1e-6 度约 0.11 米
TOLERANCE_DEG = 1e-6


def test_to_bd09_passthrough_for_bd09():
    assert to_bd09(LNG, LAT, "bd09") == (LNG, LAT)


def test_from_bd09_passthrough_for_bd09():
    assert from_bd09(LNG, LAT, "bd09") == (LNG, LAT)


def test_wgs84_to_gcj02_offset_is_hundreds_of_meters():
    """GCJ02 相对 WGS84 在国内是百米级偏移，量级不对说明公式实现有误。"""
    wgs_lng, wgs_lat = bd09_to_gcj02(LNG, LAT)  # 先取一个 GCJ02 点
    back_lng, back_lat = gcj02_to_wgs84(wgs_lng, wgs_lat)  # 再反解出 WGS84

    gap = haversine_distance(wgs_lng, wgs_lat, back_lng, back_lat)
    assert 100 <= gap <= 1000, f"偏移量级异常：{gap:.1f} m"


def test_wgs84_gcj02_round_trip():
    wgs_lng, wgs_lat = gcj02_to_wgs84(LNG, LAT)
    again_lng, again_lat = wgs84_to_gcj02(wgs_lng, wgs_lat)

    assert abs(again_lng - LNG) < TOLERANCE_DEG
    assert abs(again_lat - LAT) < TOLERANCE_DEG


def test_bd09_gcj02_round_trip():
    """BD09 与 GCJ02 互转公式互为近似逆运算（误差在厘米级），可认为无损。

    这对公式不是严格互逆（正反两个方向里 sin/cos 项取的参考点不同），
    残差约 1.8e-7 度（≈ 2 cm），远小于定位本身的误差，因此可以接受；
    这里用 TOLERANCE_DEG（1e-6 度）做护栏，防止公式被改错导致整体平移。
    """
    gcj_lng, gcj_lat = bd09_to_gcj02(LNG, LAT)
    again_lng, again_lat = gcj02_to_bd09(gcj_lng, gcj_lat)

    assert abs(again_lng - LNG) < TOLERANCE_DEG
    assert abs(again_lat - LAT) < TOLERANCE_DEG


def test_from_bd09_is_inverse_of_to_bd09():
    """BD09 转出去再转回来，必须回到原点。"""
    for source in ("gcj02", "wgs84"):
        bd_lng, bd_lat = to_bd09(LNG, LAT, source)
        back_lng, back_lat = from_bd09(bd_lng, bd_lat, source)

        assert abs(back_lng - LNG) < TOLERANCE_DEG, source
        assert abs(back_lat - LAT) < TOLERANCE_DEG, source


def test_to_bd09_from_wgs84_equals_two_steps():
    """WGS84 转 BD09 应当等于「先转 GCJ02 再转 BD09」。"""
    assert to_bd09(LNG, LAT, "wgs84") == gcj02_to_bd09(*wgs84_to_gcj02(LNG, LAT))


def test_input_types_shift_bd09_by_hundreds_of_meters():
    """用错坐标系会造成数百米偏移——这正是必须转换的原因，用它做回归护栏。"""
    bd = to_bd09(LNG, LAT, "bd09")
    as_wgs = to_bd09(LNG, LAT, "wgs84")

    gap = haversine_distance(bd[0], bd[1], as_wgs[0], as_wgs[1])
    assert 100 <= gap <= 2000, f"坐标系误用造成的偏移量级异常：{gap:.1f} m"


def test_out_of_china():
    assert out_of_china(139.6917, 35.6895)  # 东京
    assert out_of_china(-0.1276, 51.5074)  # 伦敦
    assert not out_of_china(LNG, LAT)  # 东莞


def test_overseas_coordinates_are_untouched():
    """境外坐标不施加 GCJ02 偏移，否则会把本来就对的坐标改错。"""
    tokyo = (139.6917, 35.6895)
    assert wgs84_to_gcj02(*tokyo) == tokyo
    assert gcj02_to_wgs84(*tokyo) == tokyo


def test_invalid_coord_type_raises():
    with pytest.raises(ValueError):
        to_bd09(LNG, LAT, "mars")
    with pytest.raises(ValueError):
        from_bd09(LNG, LAT, "mars")
