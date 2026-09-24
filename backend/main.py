from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="15分钟生活圈体检工具")

@app.get("/")
def hello():
    return {"msg":"后端服务正常运行"}

class PointRequest(BaseModel):
    lng: float
    lat: float

@app.post("/api/getCircleData")
async def get_circle_data(req:PointRequest):
    return {"code":0,"msg":"接口预留，待实现"}