#!/usr/bin/env bash
# 一键启动脚本（Git Bash / Linux / macOS）
#
# 用法（三种任选，推荐第一种——不需要编辑任何文件）：
#   BAIDU_SERVER_AK=xxx BAIDU_BROWSER_AK=yyy ./start.sh
#   ./start.sh --server-ak xxx --browser-ak yyy
#   ./start.sh                     # 已配置 backend/.env 时直接启动
#
# 依次完成：解析 AK → 创建虚拟环境 → 安装依赖 → 启动服务。
# 后端会同时托管前端页面，因此只需 8000 这一个端口。

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"

# 1. 命令行参数（可选），优先级高于同名环境变量
while [ $# -gt 0 ]; do
    case "$1" in
        --server-ak)    BAIDU_SERVER_AK="$2";  shift 2 ;;
        --browser-ak)   BAIDU_BROWSER_AK="$2"; shift 2 ;;
        --server-ak=*)  BAIDU_SERVER_AK="${1#*=}";  shift ;;
        --browser-ak=*) BAIDU_BROWSER_AK="${1#*=}"; shift ;;
        -h|--help)      sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "未知参数：$1（可用：--server-ak / --browser-ak）" >&2; exit 2 ;;
    esac
done

# 传入的 AK 以环境变量形式交给应用。进程环境变量的优先级高于 .env 文件，
# 因此这里不需要（也不会）改写任何配置文件。
if [ -n "$BAIDU_SERVER_AK" ]; then export BAIDU_SERVER_AK; fi
if [ -n "$BAIDU_BROWSER_AK" ]; then export BAIDU_BROWSER_AK; fi

echo "=============================================="
echo " 15分钟生活圈 · 一键启动"
echo "=============================================="

# 2. AK 检查：**只提示、不中断**。
#    服务照常启动后，页面顶部会如实显示「后端缺 AK 配置」，
#    这比脚本直接退出更容易定位问题——"服务起不来"和"缺一行配置"
#    是完全不同的两类故障，不该用同一种方式表达。
if [ -z "$BAIDU_SERVER_AK" ] && [ ! -f "$BACKEND_DIR/.env" ]; then
    cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env" 2>/dev/null || true
    echo ""
    echo "!! 未检测到百度地图 AK：服务仍会启动，但分析功能不可用。"
    echo "   补齐方式（推荐第一种，无需编辑文件）："
    echo "     BAIDU_SERVER_AK=你的服务端AK BAIDU_BROWSER_AK=你的浏览器端AK ./start.sh"
    echo "   或编辑 backend/.env（已从 .env.example 生成）后重新运行本脚本。"
    echo "   注意：两个 AK 都要填；浏览器端 AK 还必须在其控制台配置 Referer"
    echo "         白名单，否则地图会白屏（页面顶部也会提示）。"
    echo ""
fi

# 3. 虚拟环境
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

# 4. 依赖。默认走清华镜像（与 Dockerfile 保持一致），失败时回退官方源，
#    避免国内网络下要么很慢、要么直接装不上。
PIP_MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"
echo ">> 检查并安装依赖..."
if ! "$PY" -m pip install -q -i "$PIP_MIRROR" -r "$BACKEND_DIR/requirements.txt"; then
    echo "   国内镜像不可用，回退默认源重试..."
    "$PY" -m pip install -q -r "$BACKEND_DIR/requirements.txt"
fi

# 5. 启动
echo ""
echo ">> 启动服务，浏览器访问 http://localhost:8000"
cd "$BACKEND_DIR"
exec "$PY" -m uvicorn main:app --host 0.0.0.0 --port 8000
