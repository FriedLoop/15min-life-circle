# 15分钟生活圈 · 智能体检助手
#
# 单容器部署：FastAPI 后端同时提供 API 与前端静态页面，
# 评审启动后只需访问 http://localhost:8000 即可使用完整应用。

# 基础镜像可用 --build-arg 覆盖：国内网络直连 Docker Hub 常常失败，
# 换用镜像加速源即可构建，无需改 Docker 全局配置：
#   docker build --build-arg BASE_IMAGE=docker.1ms.run/library/python:3.11-slim .
# 也可先 docker pull 加速源的同名镜像后 docker tag 成 python:3.11-slim。
ARG BASE_IMAGE=python:3.11-slim
FROM ${BASE_IMAGE}

WORKDIR /app

# 先只复制依赖清单，充分利用 Docker 构建缓存
COPY backend/requirements.txt /tmp/requirements.txt

# 优先走清华镜像（国内快），失败则回退官方源。
# 必须有这个回退：实测部分网络下清华镜像会直接返回 403 Forbidden
# （DNS 正常、官方源可达），此时若只写死一个源，整个构建就失败了——
# 表现为「一键部署」在评审机器上不可用。2026-10-16 实测复现并修复。
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r /tmp/requirements.txt \
    || pip install --no-cache-dir -r /tmp/requirements.txt

# 再复制源码
COPY backend/ /app/backend/
COPY frontend/ /app/frontend/

WORKDIR /app/backend

EXPOSE 8000

# AK 等配置在运行时注入（docker-compose 的 env_file 读取 backend/.env，
# 或直接以环境变量传入），镜像本身不含任何密钥
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
