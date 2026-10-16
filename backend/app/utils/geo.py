"""地理计算工具。

约定：lng 经度在前、lat 纬度在后，坐标系 BD09。
"""

import math

# 地球平均半径（米）
EARTH_RADIUS_M = 6371008.8

# 纬度每度对应的距离（米），随纬度变化极小，可视为常数
METERS_PER_DEGREE_LAT = 111320.0


def haversine_distance(
    lng1: float, lat1: float, lng2: float, lat2: float
) -> float:
    """计算两点球面直线距离（米）。

    用于盲区算法的粗筛：直线距离是路网距离的下界，
    若直线距离已超过阈值，则无需再调用昂贵的批量算路接口。
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lng2 - lng1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def meters_per_degree_lng(lat: float) -> float:
    """给定纬度下，经度每度对应的距离（米）。"""
    return METERS_PER_DEGREE_LAT * math.cos(math.radians(lat))


def offset_by_meters(
    lng: float, lat: float, east_m: float, north_m: float
) -> tuple[float, float]:
    """从原点按米级偏移得到新坐标。

    Args:
        east_m: 向东偏移（米），负值向西
        north_m: 向北偏移（米），负值向南
    """
    new_lat = lat + north_m / METERS_PER_DEGREE_LAT
    new_lng = lng + east_m / meters_per_degree_lng(lat)
    return new_lng, new_lat


def generate_square_grid(
    center_lng: float,
    center_lat: float,
    radius_m: float,
    step_m: float,
) -> list[tuple[float, float]]:
    """以中心点生成正方形网格，并裁剪到圆形范围内。

    网格法是等时圈算法的基础：对每个网格点调用批量算路，
    得到真实步行耗时，从而还原不规则的可达范围。

    Args:
        radius_m: 网格覆盖半径（米）
        step_m: 网格间隔（米），越小越精细但调用量按平方增长
    """
    steps = int(radius_m // step_m)
    points: list[tuple[float, float]] = []

    for i in range(-steps, steps + 1):
        for j in range(-steps, steps + 1):
            east, north = i * step_m, j * step_m
            # 圆形裁剪，避免计算圈外无意义的点
            if math.hypot(east, north) > radius_m:
                continue
            points.append(offset_by_meters(center_lng, center_lat, east, north))

    return points


def idw_interpolate(
    lng: float,
    lat: float,
    samples: list[tuple[float, float, float]],
    power: float = 2.0,
    neighbors: int = 8,
) -> float | None:
    """反距离加权插值（Inverse Distance Weighting）。

    用途：分级网格只对「灰色地带」做了真实算路，内部网格点的耗时
    由已采样点插值补全，从而在不增加 API 调用的前提下保持热力图连续。

    公式：v = Σ(w_i · v_i) / Σw_i，其中 w_i = 1 / d_i^power。
    取最近的 neighbors 个样本，避免远处样本把局部梯度抹平。

    Args:
        lng / lat: 待插值点
        samples: [(lng, lat, value), ...]，已采样的点及其取值
        power: 距离衰减指数，2 表示权重随距离平方衰减
        neighbors: 参与插值的最近样本数

    Returns:
        插值结果；样本为空时返回 None。
    """
    if not samples:
        return None

    scored = sorted(
        ((haversine_distance(lng, lat, s_lng, s_lat), value) for s_lng, s_lat, value in samples),
        key=lambda pair: pair[0],
    )[:neighbors]

    # 与某个样本重合时直接取其值，避免除零
    if scored[0][0] < 1e-6:
        return scored[0][1]

    weight_sum = 0.0
    value_sum = 0.0
    for distance, value in scored:
        weight = 1.0 / (distance**power)
        weight_sum += weight
        value_sum += weight * value

    return value_sum / weight_sum


def quantize_coord(lng: float, lat: float, meters: float) -> tuple[int, int]:
    """把坐标量化到指定米数的网格。

    用于缓存键去重：在地图上轻微拖动产生的几十米偏差应视为同一位置，
    否则会生成大量近似键，缓存就形同虚设了。

    Returns:
        (经度序号, 纬度序号)
    """
    lat_step = meters / METERS_PER_DEGREE_LAT
    lng_step = meters / meters_per_degree_lng(lat)
    return round(lng / lng_step), round(lat / lat_step)
