# 一键启动脚本（Windows PowerShell）
#
# 用法（三种任选，推荐第一种——不需要编辑任何文件）：
#   .\start.ps1 -ServerAk xxx -BrowserAk yyy
#   $env:BAIDU_SERVER_AK="xxx"; $env:BAIDU_BROWSER_AK="yyy"; .\start.ps1
#   .\start.ps1                    # 已配置 backend/.env 时直接启动
#
# 若提示禁止运行脚本，先执行一次：
#   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
#
# 依次完成：解析 AK → 创建虚拟环境 → 安装依赖 → 启动服务。
# 后端会同时托管前端页面，因此只需 8000 这一个端口。

param(
    [string]$ServerAk = "",
    [string]$BrowserAk = ""
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"

# 1. 传入的 AK 以环境变量形式交给应用。进程环境变量的优先级高于 .env 文件，
#    因此这里不需要（也不会）改写任何配置文件。
if ($ServerAk) { $env:BAIDU_SERVER_AK = $ServerAk }
if ($BrowserAk) { $env:BAIDU_BROWSER_AK = $BrowserAk }

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " 15分钟生活圈 · 一键启动" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan

# 2. AK 检查：**只提示、不中断**。
#    服务照常启动后，页面顶部会如实显示「后端缺 AK 配置」，
#    这比脚本直接退出更容易定位问题——"服务起不来"和"缺一行配置"
#    是完全不同的两类故障，不该用同一种方式表达。
$envFile = Join-Path $Backend ".env"
if (-not $env:BAIDU_SERVER_AK -and -not (Test-Path $envFile)) {
    Copy-Item (Join-Path $Backend ".env.example") $envFile -ErrorAction SilentlyContinue
    Write-Host ""
    Write-Host "!! 未检测到百度地图 AK：服务仍会启动，但分析功能不可用。" -ForegroundColor Yellow
    Write-Host "   补齐方式（推荐第一种，无需编辑文件）：" -ForegroundColor Yellow
    Write-Host "     .\start.ps1 -ServerAk 你的服务端AK -BrowserAk 你的浏览器端AK" -ForegroundColor Yellow
    Write-Host "   或编辑 backend/.env（已从 .env.example 生成）后重新运行本脚本。" -ForegroundColor Yellow
    Write-Host "   注意：两个 AK 都要填；浏览器端 AK 还必须在其控制台配置 Referer" -ForegroundColor Yellow
    Write-Host "         白名单，否则地图会白屏（页面顶部也会提示）。" -ForegroundColor Yellow
    Write-Host ""
}

# 3. 虚拟环境
$py = Join-Path $Backend "venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host ">> 创建虚拟环境..." -ForegroundColor Cyan
    python -m venv (Join-Path $Backend "venv")
}

# 4. 依赖。默认走清华镜像（与 Dockerfile 保持一致），失败时回退官方源，
#    避免国内网络下要么很慢、要么直接装不上。
$PipMirror = "https://pypi.tuna.tsinghua.edu.cn/simple"
Write-Host ">> 检查并安装依赖..." -ForegroundColor Cyan
& $py -m pip install -q -i $PipMirror -r (Join-Path $Backend "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    Write-Host "   国内镜像不可用，回退默认源重试..." -ForegroundColor Yellow
    & $py -m pip install -q -r (Join-Path $Backend "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        Write-Host "!! 依赖安装失败。若为网络问题，可手动指定镜像后重试：" -ForegroundColor Red
        Write-Host "   & `"$py`" -m pip install -i $PipMirror -r backend\requirements.txt" -ForegroundColor Red
        exit 1
    }
}

# 5. 启动
Write-Host ""
Write-Host ">> 启动服务，浏览器访问 http://localhost:8000" -ForegroundColor Green
Set-Location $Backend
& $py -m uvicorn main:app --host 0.0.0.0 --port 8000
