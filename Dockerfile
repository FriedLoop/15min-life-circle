# 15分钟生活圈 · 智能体检助手
#
# 单容器部署：FastAPI 后端同时提供 API 与前端静态页面，
# 评审启动后只需访问 http://localhost:8000 即可使用完整应用。

FROM python:3.11-slim

WORKDIR /app

# 先只复制依赖清单，充分利用 Docker 构建缓存
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r /tmp/requirements.txt

# 再复制源码
COPY backend/ /app/backend/
COPY frontend/ /app/frontend/

WORKDIR /app/backend

EXPOSE 8000

# AK 等配置由 docker-compose 的 env_file 注入（读取 backend/.env）
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
