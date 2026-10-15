"""地理计算工具的单元测试。

这些是纯本地计算，不调用任何外部接口，因此可以频繁运行。
"""

from app.utils.geo import (
    METERS_PER_DEGREE_LAT,
    generate_square_grid,
    haversine_distance,
    meters_per_degree_lng,
    offset_by_meters,
    quantize_coord,
)

# 东莞理工学院松山湖校区（实测 BD09）
LNG = 113.881641
LAT = 22.909011


def test_haversine_same_point_is_zero():
    assert haversine_distance(LNG, LAT, LNG, LAT) == 0.0


def test_haversine_one_degree_latitude():
    """沿同一经度向北 1 度，距离应接近每度纬度对应的米数。"""
    distance = haversine_distance(LNG, LAT, LNG, LAT + 1)
    assert abs(distance - METERS_PER_DEGREE_LAT) < 600


def test_haversine_is_symmetric():
    forward = haversine_distance(LNG, LAT, LNG + 0.01, LAT + 0.01)
    backward = haversine_distance(LNG + 0.01, LAT + 0.01, LNG, LAT)
    assert abs(forward - backward) < 1e-6


def test_meters_per_degree_lng_shrinks_with_latitude():
    """纬度越高，经度每度对应的实际距离越短。"""
    assert meters_per_degree_lng(0) > meters_per_degree_lng(45)
    assert meters_per_degree_lng(45) > meters_per_degree_lng(80)


def test_offset_by_meters_roundtrip():
    east_lng, north_lat = offset_by_meters(LNG, LAT, 0, 1000)
    back_lng, back_lat = offset_by_meters(east_lng, north_lat, 0, -1000)
    assert abs(back_lat - LAT) < 1e-9
    assert abs(back_lng - LNG) < 1e-9


def test_offset_distance_matches_haversine():
    lng2, lat2 = offset_by_meters(LNG, LAT, 300, 400)
    # 勾股定理：东西 300m + 南北 400m → 直线 500m
    assert abs(haversine_distance(LNG, LAT, lng2, lat2) - 500) < 5


def test_generate_square_grid_point_count():
    """点数应接近圆面积除以单格面积。"""
    radius, step = 1200, 150
    points = generate_square_grid(LNG, LAT, radius, step)

    expected = 3.14159 * (radius / step) ** 2
    assert len(points) > 0
    assert abs(len(points) - expected) / expected < 0.15


def test_generate_square_grid_respects_radius():
    radius, step = 600, 100
    for lng, lat in generate_square_grid(LNG, LAT, radius, step):
        assert haversine_distance(LNG, LAT, lng, lat) <= radius + step


def test_quantize_coord_is_stable():
    assert quantize_coord(LNG, LAT, 50) == quantize_coord(LNG, LAT, 50)


def test_quantize_coord_separates_distant_points():
    """相隔 1km 的两点，量化结果必须不同（否则缓存会错误复用）。"""
    far_lng, far_lat = offset_by_meters(LNG, LAT, 1000, 1000)
    assert quantize_coord(LNG, LAT, 50) != quantize_coord(far_lng, far_lat, 50)
