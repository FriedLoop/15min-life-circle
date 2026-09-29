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


def convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """求二维点集的凸包（Andrew monotone chain，O(n log n)）。

    等时圈的可达点集是离散网格，取其凸包即得包围全部可达点的
    最小凸多边形，可作为等时圈的边界轮廓绘制在地图上。

    Args:
        points: (lng, lat) 序列

    Returns:
        按逆时针排列的凸包顶点；点数不足 3 时原样返回。
    """
    unique = sorted(set(points))
    if len(unique) <= 2:
        return unique

    def cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        """叉积，>0 表示 o->a->b 左转。"""
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    # 下凸包
    lower: list[tuple[float, float]] = []
    for p in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    # 上凸包
    upper: list[tuple[float, float]] = []
    for p in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    # 首尾点各出现两次，去掉重复的尾点
    return lower[:-1] + upper[:-1]


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
