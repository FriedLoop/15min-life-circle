"""地理计算工具的单元测试。

这些是纯本地计算，不调用任何外部接口，因此可以频繁运行。
"""

from app.utils.geo import (
    METERS_PER_DEGREE_LAT,
    generate_square_grid,
    haversine_distance,
    idw_interpolate,
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


# ---------------------------------------------------------------------------
# IDW 插值（分级网格用它补全未采样点的耗时）
# ---------------------------------------------------------------------------
def test_idw_without_samples_returns_none():
    """没有任何采样点时不能凭空造值，调用方需据此回退到几何估计。"""
    assert idw_interpolate(LNG, LAT, []) is None


def test_idw_on_sample_returns_sample_value():
    """与样本重合时应直接取该样本值，且不能因除零而出错。"""
    samples = [(LNG, LAT, 123.0), (LNG + 0.01, LAT, 456.0)]
    assert idw_interpolate(LNG, LAT, samples) == 123.0


def test_idw_weighting_favors_nearer_sample():
    """权重随距离衰减：结果应更接近近处样本。"""
    near = offset_by_meters(LNG, LAT, 100, 0)
    far = offset_by_meters(LNG, LAT, 1000, 0)
    samples = [(near[0], near[1], 100.0), (far[0], far[1], 200.0)]

    value = idw_interpolate(LNG, LAT, samples)

    assert 100.0 < value < 150.0


def test_idw_reproduces_linear_field_inside_samples():
    """在耗时近似随距离线性增长的场里，插值误差应当很小。

    分级网格只对灰色地带算路，内部耗时全靠插值——若插值误差过大，
    耗时热力图就会失真，因此这条护栏不能省。

    只在样本「包围范围内」取点验证：IDW 是加权平均，在凸包边缘会被
    单侧样本拖偏（越靠外偏差越大），这也正是分级网格必须把粗网格锚点
    布在可达区内部、而不是只靠外围灰色地带的原因。
    """
    # 沿正东方向布置 5 个样本，取值 = 直线距离（当作「耗时」的线性场）
    samples = []
    for east in (0, 300, 600, 900, 1200):
        lng2, lat2 = offset_by_meters(LNG, LAT, east, 0)
        samples.append((lng2, lat2, float(east)))

    for east in (450, 750):
        lng2, lat2 = offset_by_meters(LNG, LAT, east, 0)
        value = idw_interpolate(lng2, lat2, samples)
        assert value is not None
        assert abs(value - east) < 30, f"{east} m 处插值偏差过大：{value:.1f}"
