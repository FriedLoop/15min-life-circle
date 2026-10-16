"""坐标转换服务：优先调用百度 geoconv，不可用时退化为本地算法。

为什么两个都要有（实测对照，2026-10-15，东莞境内）：

| 输入纬度 | 官方 /geoconv/v1 与本地算法的差异 |
|---|---|
| 22.83 - 22.91 | 2.1 ~ 6.7 m |
| 23.05 | 16.0 ~ 25.2 m |

差异在 **23.0°N 附近明显放大**——GCJ02 偏移函数在该纬度带变化陡峭，
实现上的微小差别会被放大。因此：

- 有 AK 且网络可用：走官方接口，结果与百度地图渲染**完全一致**；
- 否则：本地算法兜底。即便取最坏 25 m，也远小于 150 m 网格间隔
  与 50 m 缓存量化粒度，不改变任何结论，符合本项目「宁可降级不可崩」的一贯取舍。

批量策略：百度单次请求最多带 100 个坐标，本项目按 50 分批，
与批量算路的 ROUTEMATRIX_BATCH_SIZE 保持一致，避免单请求过大。
"""

from app.services.baidu_client import BaiduApiError, baidu_client
from app.utils.coordinate import to_bd09

# 单次 geoconv 请求携带的坐标数（百度上限 100，取 50 留余量）
BATCH_SIZE = 50

# coord_type -> 百度 geoconv 的 from 参数（目标恒为 5 = BD09）
_FROM_CODE: dict[str, int] = {"wgs84": 1, "gcj02": 3}

_METHOD_API = "api"
_METHOD_LOCAL = "local"
_METHOD_NONE = "none"


def to_bd09_point(lng: float, lat: float, coord_type: str = "bd09") -> tuple[float, float]:
    """把单个坐标转成 BD09（本地算法，同步、不消耗配额）。

    供各分析接口在入口处统一调用：它们拿到的坐标可能来自 GPS 或高德，
    直接当 BD09 用会整体平移数百米。
    """
    if coord_type == "bd09":
        return lng, lat
    return to_bd09(lng, lat, coord_type)


def _local_convert(
    points: list[tuple[float, float]], coord_type: str
) -> list[tuple[float, float]]:
    return [to_bd09(lng, lat, coord_type) for lng, lat in points]


async def _convert_via_api(
    points: list[tuple[float, float]], coord_type: str
) -> list[tuple[float, float]]:
    """调用百度 /geoconv/v1 批量转换。

    Raises:
        BaiduApiError: AK 未配置、网络异常或接口返回非 0 状态码。
    """
    from_code = _FROM_CODE[coord_type]
    batches = [points[i : i + BATCH_SIZE] for i in range(0, len(points), BATCH_SIZE)]

    requests = [
        (
            "/geoconv/v1/",
            {
                "coords": ";".join(f"{lng:.6f},{lat:.6f}" for lng, lat in batch),
                "from": from_code,
                "to": 5,
            },
        )
        for batch in batches
    ]

    responses = await baidu_client.gather(requests)

    converted: list[tuple[float, float]] = []
    for data in responses:
        for item in data.get("result") or []:
            converted.append((float(item["x"]), float(item["y"])))
    return converted


async def convert_points(
    points: list[tuple[float, float]],
    coord_type: str = "wgs84",
    use_api: bool = True,
) -> tuple[list[tuple[float, float]], str, str]:
    """把一组坐标转换为 BD09。

    Args:
        points: 待转换坐标列表，每项 (lng, lat)
        coord_type: 输入坐标系，bd09 / gcj02 / wgs84
        use_api: 是否允许调用百度 geoconv 接口

    Returns:
        (BD09 坐标列表, 使用的方法, 说明信息)
        method 取值：api=官方接口 / local=本地算法 / none=本就是 BD09
    """
    if coord_type == "bd09":
        return list(points), _METHOD_NONE, ""

    if not use_api:
        return _local_convert(points, coord_type), _METHOD_LOCAL, "按要求使用本地算法"

    try:
        converted = await _convert_via_api(points, coord_type)
    except BaiduApiError as exc:
        message = f"坐标转换接口不可用，已降级为本地算法：{exc.message}"
        return _local_convert(points, coord_type), _METHOD_LOCAL, message

    if len(converted) != len(points):
        message = (
            f"坐标转换接口返回 {len(converted)} 个结果、请求 {len(points)} 个，"
            "已降级为本地算法以保证数量一致"
        )
        return _local_convert(points, coord_type), _METHOD_LOCAL, message

    return converted, _METHOD_API, ""
