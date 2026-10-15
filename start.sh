#!/usr/bin/env bash
# 一键启动脚本（Git Bash / Linux / macOS）
#
# 用法：
#   ./start.sh          # 或 bash start.sh
#
# 脚本会依次完成：检查并创建 .env → 创建虚拟环境 → 安装依赖 → 启动服务

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"

echo "=============================================="
echo " 15分钟生活圈 · 一键启动"
echo "=============================================="

# 1. 环境变量文件：没有就从模板创建，并提示填写 AK
if [ ! -f "$BACKEND_DIR/.env" ]; then
    cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
    echo ""
    echo "已创建 backend/.env"
    echo "请先编辑它，填入百度地图服务端 AK（BAIDU_SERVER_AK），然后重新运行本脚本"
    exit 1
fi

# 2. 虚拟环境
if [ ! -d "$BACKEND_DIR/venv" ]; then
    echo ">> 创建虚拟环境..."
    python -m venv "$BACKEND_DIR/venv"
fi

# 兼容 Windows（venv/Scripts）与 Linux/macOS（venv/bin）
if [ -f "$BACKEND_DIR/venv/Scripts/python.exe" ]; then
    PY="$BACKEND_DIR/venv/Scripts/python.exe"
else
    PY="$BACKEND_DIR/venv/bin/python"
fi

# 3. 依赖
echo ">> 检查并安装依赖..."
"$PY" -m pip install -q -r "$BACKEND_DIR/requirements.txt"

# 4. 启动（后端同时托管前端页面，只需这一个端口）
echo ""
echo ">> 启动服务，浏览器访问 http://localhost:8000"
cd "$BACKEND_DIR"
exec "$PY" -m uvicorn main:app --host 0.0.0.0 --port 8000
