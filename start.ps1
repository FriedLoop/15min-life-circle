# 一键启动脚本（Windows PowerShell）
#
# 用法：
#   .\start.ps1
#
# 若提示禁止运行脚本，先执行一次：
#   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " 15分钟生活圈 · 一键启动" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

# 1. 环境变量文件
$envFile = Join-Path $Backend ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $Backend ".env.example") $envFile
    Write-Host ""
    Write-Host "已创建 backend/.env，请填入百度地图服务端 AK（BAIDU_SERVER_AK）后重新运行" -ForegroundColor Yellow
    exit 1
}

# 2. 虚拟环境
$py = Join-Path $Backend "venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host ">> 创建虚拟环境..." -ForegroundColor Cyan
    python -m venv (Join-Path $Backend "venv")
}

# 3. 依赖
Write-Host ">> 检查并安装依赖..." -ForegroundColor Cyan
& $py -m pip install -q -r (Join-Path $Backend "requirements.txt")

# 4. 启动
Write-Host ""
Write-Host ">> 启动服务，浏览器访问 http://localhost:8000" -ForegroundColor Green
Set-Location $Backend
& $py -m uvicorn main:app --host 0.0.0.0 --port 8000
