"""批量算路服务（步行）。

接口：`/routematrix/v2/walking`，一次请求可携带多个目的地，
返回每个「起点-终点」组合的路网距离与步行耗时。

配额要点：
    批量算路按「最终路线数」计费而非请求数，一次等时圈分析需上百条路线。
    因此本模块做三件事来控制成本：
        1. 分批：把大量目的地切成小批次，避免单次请求过大
        2. 并发：交给 baidu_client 的信号量统一限流（个人开发者上限 3）
        3. 过滤：把算路失败的点识别出来，避免污染后续计算

坐标顺序警告：
    百度批量算路的 origins/destinations 是 **纬度在前**（"lat,lng"），
    与 POI 检索的 location 参数一致，但与本项目的 (lng, lat) 元组相反，切勿写反。
"""

from app.core.config import settings
from app.services.baidu_client import baidu_client

# 单条路线的结构：duration 步行耗时（秒）、distance 路网距离（米）
RouteInfo = dict[str, int]


async def walking_matrix(
    origin_lng: float,
    origin_lat: float,
    destinations: list[tuple[float, float]],
    batch_size: int | None = None,
) -> list[RouteInfo | None]:
    """批量计算「同一出发点 → 多个目的地」的步行耗时。

    Args:
        origin_lng / origin_lat: 出发点（BD09）
        destinations: 目的地列表，每项为 (lng, lat)
        batch_size: 单批目的地数量，默认取配置 ROUTEMATRIX_BATCH_SIZE

    Returns:
        与 destinations 等长同序的列表。每项为
        {"duration": 秒, "distance": 米}，算路失败则为 None。

    Raises:
        BaiduApiError: 接口不可用（配额耗尽、AK 无效等），由上层决定降级策略。
    """
    size = batch_size or settings.ROUTEMATRIX_BATCH_SIZE
    # 百度要求纬度在前
    origin = f"{origin_lat:.6f},{origin_lng:.6f}"

    batches = [destinations[i : i + size] for i in range(0, len(destinations), size)]

    requests = [
        (
            "/routematrix/v2/walking",
            {
                "origins": origin,
                "destinations": "|".join(f"{lat:.6f},{lng:.6f}" for lng, lat in batch),
            },
        )
        for batch in batches
    ]

    responses = await baidu_client.gather(requests)

    results: list[RouteInfo | None] = []
    for data in responses:
        # result 数组按 origin1-dest1, origin1-dest2 ... 行优先排列，
        # 因只有 1 个起点，故顺序与 destinations 完全一致
        for item in data.get("result", []):
            duration = (item.get("duration") or {}).get("value", 0)
            distance = (item.get("distance") or {}).get("value", 0)

            # duration=0 表示该点算路失败（不在路网、跨城、坐标落水等）。
            # 绝不能当成「0 秒到达」，否则会被误判为高度可达点。
            if duration <= 0:
                results.append(None)
            else:
                results.append(
                    {"duration": int(duration), "distance": int(distance)}
                )

    return results
