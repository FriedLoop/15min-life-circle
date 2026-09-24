from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
from dotenv import load_dotenv
import os

load_dotenv()
BAIDU_SERVER_AK = os.getenv("BAIDU_SERVER_AK")
app = FastAPI(title="15分钟生活圈API")

class PointRequest(BaseModel):
    lng: float
    lat: float
    radius: int = 1000
    # 检索分类，可多选：学校,医院,商场,超市,公园
    types: str = "学校,医院,商场,超市,公园"

@app.get("/")
def root():
    return {"msg": "15分钟生活圈后端服务正常运行"}

@app.post("/api/get_poi")
def get_poi(data: PointRequest):
    if not BAIDU_SERVER_AK:
        raise HTTPException(status_code=500, detail="未配置百度地图AK")

    url = "https://api.map.baidu.com/place/v2/search"
    params = {
        "ak": BAIDU_SERVER_AK,
        "query": data.types,
        "location": f"{data.lat},{data.lng}",
        "radius": data.radius,
        "output": "json",
        "scope": 2
    }
    resp = requests.get(url, params=params)
    res = resp.json()
    if res["status"] != 0:
        raise HTTPException(status_code=400, detail=f"百度API错误：{res['message']}")

    pois = []
    for item in res.get("results", []):
        pois.append({
            "name": item.get("name"),
            "address": item.get("address"),
            "lng": item["location"]["lng"],
            "lat": item["location"]["lat"],
            "type": item.get("detail_info", {}).get("tag", "")
        })
    return {
        "center": {"lng": data.lng, "lat": data.lat},
        "radius": data.radius,
        "poi_list": pois
    }
