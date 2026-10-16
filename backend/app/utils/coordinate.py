"""坐标系转换：WGS84 / GCJ02 / BD09 互转。

为什么需要：
    本项目内部统一使用 BD09（百度经纬度），但输入坐标可能来自别处：

    - **WGS84**    GPS 设备、手机原始定位、GeoJSON、OpenStreetMap
    - **GCJ02**    高德 / 腾讯地图、以及国内合规化后的「火星坐标」
    - **BD09**     百度地图（本项目基准）

    三者定位同一地点时最多可相差 **600 米以上**，若不加转换直接用，
    15 分钟等时圈会整体平移——算出来的可达范围与盲区结论全部失真。

与百度 geoconv 接口的关系：
    百度提供 `/geoconv/v1` 在线转换（见 `services/coordconv.py`），
    本模块是**离线等价实现**，用于不想消耗配额或网络不可用时。
    两者结果一致（见 tests/test_coordinate.py 的往返与对照用例）。

算法说明：
    GCJ02 是对 WGS84 施加的非线性偏移（国测局加密算法），
    没有公开的解析逆函数，因此反解采用迭代逼近（精度优于 1e-7 度，约 1 cm）。
    BD09 相对 GCJ02 只是固定的小幅偏移，可解析互转。
"""

import math
from typing import Literal

# 支持的坐标系标识
CoordType = Literal["bd09", "gcj02", "wgs84"]

COORD_TYPES: tuple[str, ...] = ("bd09", "gcj02", "wgs84")

# 坐标类型的中文名，用于响应与日志
COORD_TYPE_LABELS: dict[str, str] = {
    "bd09": "百度经纬度（BD09）",
    "gcj02": "国测局坐标（GCJ02，高德/腾讯）",
    "wgs84": "GPS 坐标（WGS84）",
}

# 克拉索夫斯基椭球参数（GCJ02 偏移算法使用）
_EARTH_A = 6378245.0
_EARTH_EE = 0.00669342162296594323

# BD09 相对 GCJ02 的偏移系数
_BD09_X_PI = 3000.0 / 180.0
_BD09_Y_PI = 3000.0 / 180.0
_BD09_Z = math.sqrt(2.0) * 2.0 * 20.0 / 180.0


def out_of_china(lng: float, lat: float) -> bool:
    """粗略判断坐标是否位于中国大陆之外。

    GCJ02 加密只在中国大陆范围内生效，境外坐标不应施加偏移，
    否则会把本来正确的坐标改错。
    """
    return not (72.004 <= lng <= 137.8347 and 0.8293 <= lat <= 55.8271)


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def _delta(lng: float, lat: float) -> tuple[float, float]:
    """返回该点从 WGS84 到 GCJ02 的偏移量（度）。"""
    d_lat = _transform_lat(lng - 105.0, lat - 35.0)
    d_lng = _transform_lng(lng - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * math.pi
    magic = math.sin(rad_lat)
    magic = 1 - _EARTH_EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((_EARTH_A * (1 - _EARTH_EE)) / (magic * sqrt_magic) * math.pi)
    d_lng = (d_lng * 180.0) / (_EARTH_A / sqrt_magic * math.cos(rad_lat) * math.pi)
    return d_lng, d_lat


def wgs84_to_gcj02(lng: float, lat: float) -> tuple[float, float]:
    """WGS84 转 GCJ02。境外坐标原样返回。"""
    if out_of_china(lng, lat):
        return lng, lat
    d_lng, d_lat = _delta(lng, lat)
    return lng + d_lng, lat + d_lat


def gcj02_to_wgs84(lng: float, lat: float) -> tuple[float, float]:
    """GCJ02 转 WGS84（迭代逼近，精度约 1 cm）。

    偏移算法没有解析逆函数，用「先正向加偏移、再按残差回退」的方式逼近：
    每轮把当前估计值转回 GCJ02 与实际值比较，按差值修正，收敛很快。
    """
    if out_of_china(lng, lat):
        return lng, lat
    # 以「减去一次偏移」作为初值，可让迭代次数更少
    d_lng, d_lat = _delta(lng, lat)
    guess_lng, guess_lat = lng - d_lng, lat - d_lat
    for _ in range(6):
        g_lng, g_lat = wgs84_to_gcj02(guess_lng, guess_lat)
        err_lng, err_lat = g_lng - lng, g_lat - lat
        if abs(err_lng) < 1e-9 and abs(err_lat) < 1e-9:
            break
        guess_lng -= err_lng
        guess_lat -= err_lat
    return guess_lng, guess_lat


def gcj02_to_bd09(lng: float, lat: float) -> tuple[float, float]:
    """GCJ02 转 BD09（解析公式）。"""
    z = math.sqrt(lng * lng + lat * lat) + 0.00002 * math.sin(lat * _BD09_X_PI)
    theta = math.atan2(lat, lng) + 0.000003 * math.cos(lng * _BD09_Y_PI)
    return z * math.cos(theta) + 0.0065, z * math.sin(theta) + 0.006


def bd09_to_gcj02(lng: float, lat: float) -> tuple[float, float]:
    """BD09 转 GCJ02（解析公式）。"""
    x = lng - 0.0065
    y = lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * _BD09_X_PI)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * _BD09_Y_PI)
    return z * math.cos(theta), z * math.sin(theta)


def to_bd09(lng: float, lat: float, source: str = "bd09") -> tuple[float, float]:
    """把任意支持的坐标系坐标转换为 BD09（本项目内部基准）。"""
    if source == "bd09":
        return lng, lat
    if source == "gcj02":
        return gcj02_to_bd09(lng, lat)
    if source == "wgs84":
        return gcj02_to_bd09(*wgs84_to_gcj02(lng, lat))
    raise ValueError(f"不支持的坐标系：{source!r}，可选 {COORD_TYPES}")


def from_bd09(lng: float, lat: float, target: str = "bd09") -> tuple[float, float]:
    """把 BD09 坐标转换为目标坐标系。"""
    if target == "bd09":
        return lng, lat
    if target == "gcj02":
        return bd09_to_gcj02(lng, lat)
    if target == "wgs84":
        return gcj02_to_wgs84(*bd09_to_gcj02(lng, lat))
    raise ValueError(f"不支持的坐标系：{target!r}，可选 {COORD_TYPES}")
