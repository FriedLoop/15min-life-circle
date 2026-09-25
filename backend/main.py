from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
from dotenv import load_dotenv
import os

load_dotenv()
BAIDU_SERVER_AK = os.getenv("BAIDU_SERVER_AK")
app = FastAPI(title="15分钟生活圈API")

# 跨域中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 请求模型：radius、types设置默认值，前端可以只传lng lat
class PointRequest(BaseModel):
    lng: float
    lat: float
    radius: int = 1000
    types: str = "学校,医院,商场,超市,公园"


@app.get("/")
def root():
    return {"msg": "15分钟生活圈后端服务正常运行"}


@app.post("/api/get_poi")
def get_poi(data: PointRequest):
    if not BAIDU_SERVER_AK:
        raise HTTPException(status_code=500, detail="未配置百度地图服务端AK，请检查.env文件")

    url = "https://api.map.baidu.com/place/v2/search"
    params = {
        "ak": BAIDU_SERVER_AK,
        "query": data.types,
        "location": f"{data.lat},{data.lng}",
        "radius": data.radius,
        "output": "json",
        "scope": 2
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        res = resp.json()
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"请求百度地图API网络异常：{str(e)}")

    if res.get("status") != 0:
        msg = res.get("message", "百度API未知错误")
        raise HTTPException(status_code=400, detail=f"百度API错误：{msg}")

    pois = []
    for item in res.get("results", []):
        loc = item.get("location", {})
        detail = item.get("detail_info", {})
        pois.append({
            "name": item.get("name"),
            "address": item.get("address"),
            "lng": loc.get("lng"),
            "lat": loc.get("lat"),
            "type": detail.get("tag", "")
        })

    return {
        "center": {"lng": data.lng, "lat": data.lat},
        "radius": data.radius,
        "poi_list": pois
    }
