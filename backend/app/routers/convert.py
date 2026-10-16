"""坐标转换路由。"""

from fastapi import APIRouter

from app.schemas.models import ConvertRequest, ConvertResponse
from app.services import coordconv

router = APIRouter(prefix="/api", tags=["convert"])


@router.post("/convert", response_model=ConvertResponse)
async def convert(data: ConvertRequest) -> ConvertResponse:
    """把 WGS84 / GCJ02 坐标转换为 BD09。

    用于把外部来源的坐标接入本项目：GPS 设备与 GeoJSON 是 WGS84，
    高德/腾讯是 GCJ02，而百度地图（以及本项目全部接口）使用 BD09。
    三者定位同一地点最多相差 600 米以上，不转换会让等时圈与盲区结论整体平移。

    转换方式由 method 字段说明：
        api    调用百度「坐标转换」接口（/geoconv/v1），与百度地图渲染完全一致
        local  接口不可用时降级为本地算法（实测差异 2~25 m，见 coordconv 模块注释）
        none   输入本就是 BD09，未做转换
    """
    points = [(point.lng, point.lat) for point in data.points]
    converted, method, message = await coordconv.convert_points(
        points, data.coord_type, data.use_api
    )

    return ConvertResponse(
        source=data.coord_type,
        method=method,
        message=message,
        points=[{"lng": lng, "lat": lat} for lng, lat in converted],
    )
