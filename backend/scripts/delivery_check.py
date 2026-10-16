#!/usr/bin/env python
"""交付要求一键自检。

在提交 / 评审前用一条命令确认全部交付要求是否满足，覆盖：

1. 交付物完整性（文档、部署脚本、CI、依赖清单……）
2. 前端资源完整性（index.html 引用的本地文件都存在）
3. 密钥安全（.env 未被追踪、示例文件中只有占位符、镜像不含密钥）
4. 环境变量文档一致性（配置字段、.env.example、README 三方比对）
5. API 契约一致性（代码注册的路由与 README 接口表双向比对）
6. 静态检查（ruff）
7. 单元测试（pytest）
8. 交付要求与评分维度逐条核对（对照赛题《交付要求》与《评审维度》）
9. 文档一致性（不引用已删除的流水线配置）
10. Docker 一键部署（可选，`--docker`）

用法（在仓库根目录执行）：

    python backend/scripts/delivery_check.py

参数：
    --docker   额外验证 Docker 一键部署（构建镜像 + 健康检查，较慢）
    --strict   把「提示」也计为失败（最严格的提交前自检）
    --no-test  跳过单元测试
    --no-lint  跳过 ruff 静态检查

退出码：0 = 全部通过；1 = 存在失败项（`--strict` 下提示项同样视为失败）。
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
CONFIG_PY = BACKEND / "app" / "core" / "config.py"
ENV_EXAMPLE = BACKEND / ".env.example"
README = ROOT / "README.md"

OK, FAIL, WARN, SKIP, SECTION = "OK", "FAIL", "WARN", "SKIP", "SECTION"
_MARK = {OK: "[ OK ]", FAIL: "[FAIL]", WARN: "[WARN]", SKIP: "[SKIP]"}

# 必须存在的交付物（目录以 / 结尾）
REQUIRED_ARTIFACTS = (
    "README.md",
    "LICENSE",
    "docs/技术方案.md",
    "docs/测试报告.md",
    "docs/手动测试清单.md",
    ".gitignore",
    ".dockerignore",
    "Dockerfile",
    "docker-compose.yml",
    "start.sh",
    "start.ps1",
    "ruff.toml",
    ".github/workflows/ci.yml",
    "backend/main.py",
    "backend/requirements.txt",
    "backend/.env.example",
    "backend/tests/",
    "frontend/index.html",
    "frontend/css/style.css",
    "frontend/js/",
)

# 文档中承诺的、但仓库已不再提供的文件（避免文档自相矛盾）
STALE_REFERENCES = (
    ".workflow/MasterPipeline.yml",
    ".gitlab-ci.yml",
)

# 必须同时出现在 .env.example 与 README 中的配置项
REQUIRED_DOCUMENTED = ("BAIDU_SERVER_AK", "BAIDU_BROWSER_AK")

# index.html 中引用的本地资源
_ASSET_REF = re.compile(r'(?:src|href)="([^"]+)"')
# 形如 BAIDU_SERVER_AK=xxxxxxxx 的赋值
_AK_ASSIGN = re.compile(
    r"\b(BAIDU_[A-Z_]*AK)\b\s*[=:]\s*[\"']?([A-Za-z0-9_\-]{16,})", re.IGNORECASE
)
# 真实 AK：24 位以上的纯字母数字（占位符通常带下划线或尖括号）
_LOOKS_REAL_AK = re.compile(r"^[0-9A-Za-z]{20,}$")


@dataclass
class Report:
    """收集并渲染自检结果。"""

    items: list[tuple[str, str, str]] = field(default_factory=list)

    def section(self, name: str) -> None:
        self.items.append((SECTION, name, ""))

    def add(self, status: str, title: str, detail: str = "") -> None:
        self.items.append((status, title, detail.strip()))

    def check(self, passed: bool, title: str, detail_ok: str = "", detail_fail: str = "") -> bool:
        self.add(OK if passed else FAIL, title, detail_ok if passed else detail_fail)
        return passed

    def count(self, status: str) -> int:
        return sum(1 for status_, _, _ in self.items if status_ == status)

    def render(self, verbose: bool) -> None:
        for status, title, detail in self.items:
            if status == SECTION:
                print(f"\n=== {title} ===")
                continue
            line = f"{_MARK[status]} {title}"
            if detail and (verbose or status in (FAIL, WARN)):
                line += f"\n       {detail}"
            print(line)

    def passed(self, strict: bool) -> bool:
        if self.count(FAIL):
            return False
        return not (strict and self.count(WARN))


def _run(cmd: list[str], cwd: Path, timeout: int = 300) -> tuple[int, str]:
    """执行外部命令，统一处理缺失/超时，返回 (退出码, 输出)。"""
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError:
        return 127, f"命令不存在：{cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, f"命令超时（>{timeout}s）：{' '.join(cmd)}"
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, output


def _tail(text: str, limit: int = 600) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return "...\n" + text[-limit:]


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _is_placeholder(value: str) -> bool:
    lowered = value.lower()
    if "_" in value or "<" in value or ">" in value:
        return True
    return any(token in lowered for token in ("your", "here", "xxxx", "example", "placeholder"))


# --------------------------------------------------------------------------
# 1. 交付物完整性
# --------------------------------------------------------------------------
def check_artifacts(report: Report) -> None:
    report.section("1. 交付物完整性")
    for rel in REQUIRED_ARTIFACTS:
        path = ROOT / rel.rstrip("/")
        exists = path.is_dir() if rel.endswith("/") else path.is_file()
        report.add(OK if exists else FAIL, rel, "" if exists else "缺失")
    report.check(
        README.is_file() and "## 四、环境变量" in _read(README),
        "README 含环境变量章节",
        "环境变量清单已文档化",
        "README 缺少「环境变量」章节",
    )
    report.check(
        BACKEND.joinpath("app").is_dir() and FRONTEND.joinpath("js").is_dir(),
        "后端 / 前端源码目录结构完整",
    )


def check_frontend_assets(report: Report) -> None:
    report.section("2. 前端资源完整性")
    index = FRONTEND / "index.html"
    if not index.is_file():
        report.add(FAIL, "frontend/index.html", "缺失，无法检查资源引用")
        return
    html = _read(index)
    refs = [
        ref
        for ref in _ASSET_REF.findall(html)
        if not ref.startswith(("http://", "https://", "//", "#", "data:"))
    ]
    missing = sorted({ref for ref in refs if not (FRONTEND / ref.lstrip("/")).is_file()})
    report.check(
        not missing,
        f"index.html 引用的本地资源均存在（{len(set(refs))} 个）",
        detail_fail="缺失：" + "、".join(missing),
    )
    modules = sorted(p.name for p in (FRONTEND / "js").glob("*.js"))
    report.add(OK if modules else FAIL, f"前端 JS 模块 {len(modules)} 个", "、".join(modules))
    check_dom_bindings(report, html)


def check_dom_bindings(report: Report, html: str) -> None:
    """前端 JS 里 $('id') 引用的元素必须真的存在于 index.html。

    为什么值得单列一条：这类错误**不会报错**——$ 取到 null，
    后续 el.hidden / el.textContent 直接抛 TypeError 或被 if 守卫静默跳过，
    表现为「某个按钮没反应」或「改了结构之后功能悄悄失效」。
    本项目已经踩过一次同类问题（layers.js 按不存在的 p.reachable 过滤，
    导致等时圈边界永远画不出来却毫无提示）。
    """
    html_ids = set(re.findall(r'id="([^"]+)"', html))
    js_sources = "\n".join(_read(p) for p in sorted((FRONTEND / "js").glob("*.js")))
    used = set(re.findall(r"\$\('([^']+)'\)", js_sources))
    # 允许 JS 侧拼出来的 id（如 $('panel-' + kind)）无法静态解析，这里只查字面量
    missing = sorted(used - html_ids)
    report.check(
        not missing,
        f"JS 里 $('id') 引用的元素均在 index.html 中存在（{len(used)} 个）",
        detail_fail="index.html 中不存在：" + "、".join(missing),
    )


# --------------------------------------------------------------------------
# 3. 密钥安全
# --------------------------------------------------------------------------
def check_secrets(report: Report) -> None:
    report.section("3. 密钥安全")
    gitignore = _read(ROOT / ".gitignore").splitlines()
    report.check(".env" in [line.strip() for line in gitignore], ".gitignore 忽略 .env")
    dockerignore = _read(ROOT / ".dockerignore")
    report.check(
        "backend/.env" in dockerignore,
        ".dockerignore 排除密钥（不打进镜像）",
        "backend/.env 已被排除",
        "backend/.env 可能被打进镜像",
    )

    code, out = _run(["git", "ls-files"], ROOT)
    if code != 0:
        report.add(SKIP, "git 仓库检查", "当前不在 git 仓库中或未安装 git")
        return

    tracked = [line.strip() for line in out.splitlines() if line.strip()]
    report.check(
        "backend/.env" not in tracked,
        "backend/.env 未被 git 追踪",
        detail_fail="密钥文件已进入版本库，必须立即从历史中移除",
    )

    suspected: list[str] = []
    for rel in tracked:
        path = ROOT / rel
        if not path.is_file() or path.suffix not in (".py", ".md", ".env", ".example", ".yml", ""):
            continue
        if path.suffix == "" and path.name not in (".env", ".env.example"):
            continue
        text = _read(path)
        for name, value in _AK_ASSIGN.findall(text):
            if _LOOKS_REAL_AK.match(value) and not _is_placeholder(value):
                suspected.append(f"{rel}: {name}={value[:8]}…")
    report.check(
        not suspected,
        "已追踪文件中无硬编码 AK",
        detail_fail="疑似真实密钥：" + "；".join(suspected),
    )

    example = _read(ENV_EXAMPLE)
    leaked = [
        f"{name}={value[:8]}…"
        for name, value in _AK_ASSIGN.findall(example)
        if not _is_placeholder(value)
    ]
    report.check(
        not leaked,
        ".env.example 中 AK 均为占位符",
        detail_fail="示例文件含疑似真实密钥：" + "；".join(leaked),
    )

    if (BACKEND / ".env").is_file():
        report.add(OK, "本地 backend/.env 存在", "已配置真实 AK（本地调试用，不会提交）")
    else:
        report.add(WARN, "本地 backend/.env 不存在", "真实分析需先由 .env.example 复制并填入 AK")


# --------------------------------------------------------------------------
# 4. 环境变量文档一致性
# --------------------------------------------------------------------------
def parse_settings_fields(config_py: Path = CONFIG_PY) -> list[str]:
    """用 AST 解析 Settings 类的字段名（字段名即环境变量名）。"""
    if not config_py.is_file():
        return []
    tree = ast.parse(_read(config_py))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            return [
                item.target.id
                for item in node.body
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
            ]
    return []


def check_env_docs(report: Report) -> None:
    report.section("4. 环境变量文档一致性")
    fields = parse_settings_fields()
    if not fields:
        report.add(FAIL, "解析 Settings 配置字段", f"未从 {CONFIG_PY} 解析到字段")
        return

    example = _read(ENV_EXAMPLE)
    readme = _read(README)

    for name in REQUIRED_DOCUMENTED:
        missing_spots = []
        if name not in example:
            missing_spots.append("backend/.env.example")
        if name not in readme:
            missing_spots.append("README")
        report.check(
            not missing_spots,
            f"{name} 已在示例与文档中说明",
            detail_fail="缺失位置：" + "、".join(missing_spots),
        )

    undocumented = [
        name
        for name in fields
        if name not in REQUIRED_DOCUMENTED and name not in example and name not in readme
    ]
    rest = len(fields) - len(REQUIRED_DOCUMENTED)
    if undocumented:
        report.add(
            WARN,
            f"其余 {rest} 项配置中 {len(undocumented)} 项未在文档中出现",
            "、".join(undocumented),
        )
    else:
        report.add(OK, f"其余 {rest} 项配置已在文档中说明")

    report.add(OK, f"共解析到 {len(fields)} 项配置", "、".join(fields))


# --------------------------------------------------------------------------
# 5. API 契约一致性
# --------------------------------------------------------------------------
_ROUTE_SNIPPET = (
    "import json, sys;"
    "sys.path.insert(0, '.');"
    "from main import app;"
    "print(json.dumps(sorted(app.openapi()['paths'])))"
)


def _app_routes() -> tuple[list[str] | None, str]:
    code, out = _run([sys.executable, "-c", _ROUTE_SNIPPET], BACKEND, timeout=120)
    if code != 0:
        return None, _tail(out)
    for line in reversed(out.strip().splitlines()):
        line = line.strip()
        if line.startswith("["):
            try:
                return json.loads(line), ""
            except json.JSONDecodeError:
                continue
    return None, _tail(out)


def check_api_contract(report: Report) -> None:
    report.section("5. API 契约一致性")
    routes, error = _app_routes()
    if routes is None:
        report.add(FAIL, "应用可导入并列出路由", error)
        return
    app_api = {route for route in routes if route.startswith("/api/")}
    readme = _read(README)
    readme_api = set(re.findall(r"/api/[a-z_]+", readme))

    missing_in_readme = sorted(app_api - readme_api)
    missing_in_code = sorted(readme_api - app_api)
    report.add(OK, f"应用可导入，/api/ 路由 {len(app_api)} 个", "、".join(sorted(app_api)))
    report.check(
        not missing_in_readme,
        "README 已收录全部接口",
        detail_fail="代码中存在但 README 未记录：" + "、".join(missing_in_readme),
    )
    report.check(
        not missing_in_code,
        "README 中的接口均已实现",
        detail_fail="README 中有但代码未实现：" + "、".join(missing_in_code),
    )
    report.check(
        "StaticFiles" in _read(BACKEND / "main.py"),
        "后端挂载前端静态页面（单端口部署）",
    )


# --------------------------------------------------------------------------
# 官方《交付要求》与《评审维度》核对数据（由 check_rubric 使用）
# --------------------------------------------------------------------------
# 每项：(条目描述, ((文件, (关键词, ...)), ...))
# 全部关键词命中即视为该条目已落实；缺失则报告具体文件与关键词。
RubricItem = tuple[str, tuple[tuple[str, tuple[str, ...]], ...]]
RUBRIC: tuple[RubricItem, ...] = (
    # ---- 3. 交付要求 ----
    (
        "交付① 开源应用源码 + 标准开源许可证",
        (
            ("LICENSE", ("MIT",)),
            ("README.md", ("百度地图", "Docker")),
        ),
    ),
    (
        "交付② 一键式部署脚本（Docker / 环境配置文件）",
        (
            ("start.sh", ("uvicorn",)),
            ("start.ps1", ("uvicorn",)),
            ("Dockerfile", ("uvicorn",)),
            ("docker-compose.yml", ("env_file",)),
            ("backend/.env.example", ("BAIDU_SERVER_AK",)),
        ),
    ),
    (
        "交付② 预置示例数据（评审可一键加载样例点位）",
        (
            ("backend/app/core/samples.py", ("SAMPLE_LOCATIONS", "113.881641", "113.779678")),
            # 第三个点位是赛题要求的「社区/街道」样本（虎门镇北栅行政小区），
            # 必须与前两点同为「地理编码 + 地点检索」交叉验证过的坐标
            ("backend/app/core/samples.py", ("113.723151", "九方工贸大厦")),
            ("backend/app/routers/config.py", ("SAMPLE_LOCATIONS",)),
        ),
    ),
    (
        "交付③ 技术设计文档（API 策略 / 等时圈 / POI 清洗 / 盲区算法）",
        (
            ("docs/技术方案.md", ("地图 API 调用策略", "等时圈", "POI 数据清洗", "盲区识别")),
        ),
    ),
    (
        "交付③ 特定社区真实对比测试报告",
        (
            ("docs/测试报告.md", ("松山湖", "莞城")),
        ),
    ),
    # ---- 4. 功能正确性与覆盖率 40% ----
    (
        "功能① 地图基础能力：坐标转换 / POI 检索 / 路径规划",
        (
            ("backend/app/services/geocoding.py", ("/geocoding/v3", "/reverse_geocoding/v3")),
            ("backend/app/services/poi.py", ("/place/v2/search",)),
            ("backend/app/services/routematrix.py", ("/routematrix/v2/walking",)),
        ),
    ),
    (
        "功能① 坐标转换能力（WGS84 / GCJ02 / BD09 互转 + 请求入口统一转 BD09）",
        (
            (
                "backend/app/utils/coordinate.py",
                ("wgs84_to_gcj02", "gcj02_to_bd09", "bd09_to_gcj02"),
            ),
            ("backend/app/routers/convert.py", ("/convert",)),
            ("backend/app/services/coordconv.py", ("to_bd09_point",)),
            # 前端必须能声明坐标系，否则「坐标转换」只有接口、没有入口
            ("frontend/js/main.js", ("coord_type", "convertAndLocate")),
            ("frontend/index.html", ('id="coord-type"',)),
        ),
    ),
    (
        "功能② 真实路网等时圈 + 热力图渲染",
        (
            ("backend/app/services/isochrone.py", ("duration", "threshold_seconds")),
            ("frontend/js/layers.js", ("drawAccessibility", "drawBoundary")),
        ),
    ),
    (
        "功能③ 服务盲区识别（1km 内菜市场 / 药店 / 小学）",
        (
            ("backend/app/core/constants.py", ("BLINDSPOT_CATEGORIES", "菜市场", "药店", "小学")),
            ("backend/app/core/config.py", ("BLINDSPOT_DISTANCE_M", "1000")),
        ),
    ),
    # ---- 4. API 深度调用与工程优化 30% ----
    (
        "深度① 批量距离矩阵 + 并发请求策略",
        (
            ("backend/app/services/routematrix.py", ("batch_size", "/routematrix/v2/walking")),
            ("backend/app/services/baidu_client.py", ("Semaphore",)),
        ),
    ),
    (
        "深度② 容错与降级机制（限流 / 异常 / POI 缺失）",
        (
            ("backend/app/services/isochrone.py", ("degraded", "BaiduApiError")),
            ("backend/app/services/poi.py", ("return_exceptions=True",)),
            ("backend/app/services/baidu_client.py", ("BaiduApiError",)),
            # 降级必须对用户可见，否则「直线估算」会被当成真实路网结论
            ("frontend/js/main.js", ("degraded", "failed_categories")),
        ),
    ),
    (
        "深度③ 空间插值思路：网格采样 + 直线初筛推导连通区域",
        (
            ("backend/app/utils/geo.py", ("generate_square_grid",)),
            ("backend/app/services/blindspot.py", ("DETOUR_FACTOR",)),
            ("docs/技术方案.md", ("网格采样", "直线初筛")),
        ),
    ),
    (
        "深度③ IDW 插值：分级网格 + 反距离加权，并给出三策略实测对照",
        (
            ("backend/app/utils/geo.py", ("idw_interpolate",)),
            ("backend/app/services/isochrone.py", ("interpolated", "routed_points")),
            ("backend/scripts/compare_grid_strategies.py", ("SECTOR_RADII_M",)),
            ("docs/技术方案.md", ("IDW", "面积误差")),
        ),
    ),
    (
        "深度② 配额实证：响应回传真实算路量，前端展示缓存与精算次数",
        (
            ("backend/app/schemas/models.py", ("routed_points", "interpolated_points")),
            ("frontend/js/main.js", ("renderCacheBadge", "precise_calls")),
        ),
    ),
    (
        "深度③ 数据可信度：用政务公开权威名录交叉校验 POI 检索",
        (
            ("backend/scripts/collect_authority_data.py", ("东莞市医疗保障局", "东莞市教育局")),
            ("backend/scripts/authority_benchmark.py", ("_name_hit", "baidu_knows_it")),
            # 冻结的名录快照必须入库，否则评审无法离线复现校验结果
            ("backend/scripts/authority_benchmark/dongguan_pharmacy.csv", ("镇街", "地址")),
            ("backend/scripts/authority_benchmark/manifest.json", ("publisher", "collected_at")),
            ("docs/技术方案.md", ("权威名录交叉校验", "召回率")),
        ),
    ),
    # ---- 4. 产品交互与用户体验 15% ----
    (
        "产品① 可视化：双图层热力图 + 柱状图 + 雷达图 + 逐类盲区率",
        (
            ("frontend/js/layers.js", ("drawAccessibility", "drawDuration", "drawBlindMarks")),
            ("frontend/js/charts.js", ("renderCoverage", "renderRadar")),
            ("frontend/js/main.js", ("renderCategoryTable", "renderMap")),
        ),
    ),
    (
        "产品② 用户可自定义地图中心点 + 设施检索面板",
        (
            ("frontend/js/map.js", ("setCenter", "onSelect")),
            ("frontend/js/main.js", ("renderSamples", "runPoiSearch")),
            ("frontend/js/api.js", ("getPoi", "convert")),
        ),
    ),
    # ---- 4. 开源工程规范 15% ----
    (
        "工程① 代码规范：分层结构 + ruff 规则集",
        (
            ("ruff.toml", ("line-length",)),
            ("backend/app/routers/health.py", ()),
            ("backend/app/services/report.py", ()),
            ("backend/app/schemas/models.py", ()),
        ),
    ),
    (
        "工程② 文档与部署说明（环境变量脱敏 + 部署指南）",
        (
            ("README.md", ("环境变量", "快速开始", "docker compose")),
            ("backend/.env.example", ("your_baidu_server_ak_here",)),
        ),
    ),
    (
        "工程③ CI/CD 自动化构建与代码格式化检查",
        (
            (".github/workflows/ci.yml", ("ruff check", "pytest")),
        ),
    ),
)


def check_rubric(report: Report) -> None:
    """按官方《交付要求》与《评审维度》逐条核对仓库中的实际证据。"""
    report.section("8. 交付要求与评分维度逐条核对")
    for title, evidences in RUBRIC:
        problems: list[str] = []
        for rel, keywords in evidences:
            path = ROOT / rel
            if not path.is_file():
                problems.append(f"{rel} 不存在")
                continue
            text = _read(path)
            problems.extend(f"{rel} 缺少「{kw}」" for kw in keywords if kw not in text)
        if problems:
            report.add(FAIL, title, "；".join(problems))
        else:
            report.add(OK, title, f"证据 {len(evidences)} 处")


# --------------------------------------------------------------------------
# 6. 静态检查与单元测试
# --------------------------------------------------------------------------
def check_lint(report: Report) -> None:
    report.section("6. 静态检查（ruff）")
    code, out = _run([sys.executable, "-m", "ruff", "check", "backend/"], ROOT)
    if code == 127 or "No module named" in out:
        report.add(SKIP, "ruff 静态检查", "未安装：pip install -r backend/requirements.txt")
        return
    report.check(code == 0, "ruff check backend/", "无告警", _tail(out))


def check_tests(report: Report) -> None:
    report.section("7. 单元测试（pytest）")
    code, out = _run([sys.executable, "-m", "pytest", "backend/tests/", "-q"], ROOT, timeout=900)
    if code == 127 or "No module named" in out:
        report.add(SKIP, "pytest 单元测试", "未安装：pip install -r backend/requirements.txt")
        return
    summary = next(
        (line for line in reversed(out.strip().splitlines()) if "passed" in line or "failed" in line),
        _tail(out, 200),
    )
    report.check(code == 0, "pytest backend/tests/", summary, _tail(out))


# --------------------------------------------------------------------------
# 10. Docker 一键部署（可选）
# --------------------------------------------------------------------------
def check_docker(report: Report) -> None:
    report.section("10. Docker 一键部署")
    if shutil.which("docker") is None:
        report.add(SKIP, "Docker 一键部署", "本机未安装 docker，由 CI 的 docker job 覆盖")
        return

    image, name, port = "15min-life-circle:selfcheck", "15min-life-circle-selfcheck", 8123
    code, out = _run(["docker", "build", "-t", image, "."], ROOT, timeout=1800)
    if not report.check(code == 0, "docker build 成功", detail_fail=_tail(out, 800)):
        return

    _run(["docker", "rm", "-f", name], ROOT, timeout=60)
    code, out = _run(
        ["docker", "run", "-d", "--name", name, "-p", f"{port}:8000", image], ROOT, timeout=180
    )
    if not report.check(code == 0, "容器已启动", detail_fail=_tail(out, 400)):
        return

    try:
        healthy = False
        for _ in range(30):
            try:
                with urllib.request.urlopen(  # noqa: S310 - 本机自检地址
                    f"http://localhost:{port}/api/health", timeout=5
                ) as resp:
                    healthy = resp.status == 200 and b'"status":"ok"' in resp.read()
            except (urllib.error.URLError, OSError):
                time.sleep(2)
                continue
            break
        report.check(
            healthy, "容器内 GET /api/health 返回 status: ok", detail_fail=_tail(out, 400)
        )
        root_ok = False
        try:
            with urllib.request.urlopen(  # noqa: S310 - 本机自检地址
                f"http://localhost:{port}/", timeout=5
            ) as resp:
                root_ok = b"<html" in resp.read().lower()
        except (urllib.error.URLError, OSError) as exc:
            report.add(FAIL, "容器内 GET / 返回前端页面", str(exc))
        else:
            report.check(root_ok, "容器内 GET / 返回前端页面")
    finally:
        _run(["docker", "rm", "-f", name], ROOT, timeout=60)


# --------------------------------------------------------------------------
# 9. 文档与跨平台一致性
# --------------------------------------------------------------------------
# Windows PowerShell 控制台默认 GBK(cp936)。脚本输出里一旦出现对勾、警告、对号（U+2713 / U+26A0 / U+2705）这类
# 不在 GBK 内的符号，print 会直接抛 UnicodeEncodeError 并中断整个脚本——
# backend/scripts 下确实因此崩过（resolve_location.py 在打印结论前就挂了）。
# 所以源码统一要求「可被 GBK 编码」，这是本项目 Windows 可用性的一部分。
_CONSOLE_ENCODING = "gbk"
_SOURCE_SKIP_DIRS = frozenset({"venv", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"})


def _is_console_safe(char: str) -> bool:
    try:
        char.encode(_CONSOLE_ENCODING)
    except UnicodeEncodeError:
        return False
    return True


def check_console_compat(report: Report) -> None:
    """源码中不得出现 GBK 无法编码的字符（会中断 Windows 控制台脚本）。"""
    offenders: list[str] = []
    for path in sorted(BACKEND.rglob("*.py")):
        if _SOURCE_SKIP_DIRS & set(path.parts):
            continue
        bad = sorted({char for char in _read(path) if not _is_console_safe(char)})
        if bad:
            offenders.append(f"{path.relative_to(ROOT)}: {' '.join(bad)}")
    report.check(
        not offenders,
        f"源码字符可在 Windows {_CONSOLE_ENCODING.upper()} 控制台输出",
        detail_fail="含无法编码的字符（会抛 UnicodeEncodeError）：" + "；".join(offenders),
    )


def check_stale_references(report: Report) -> None:
    report.section("9. 文档与跨平台一致性")
    stale = [rel for rel in STALE_REFERENCES if (ROOT / rel).exists()]
    report.check(not stale, "STALE_REFERENCES 中的废弃配置未残留", detail_fail="、".join(stale))

    mentioned: list[str] = []
    for path in (README, ROOT / "ruff.toml", ROOT / "docs" / "技术方案.md"):
        text = _read(path)
        for rel in STALE_REFERENCES:
            if rel in text:
                mentioned.append(f"{path.relative_to(ROOT)} 提到已删除的 {rel}")
    report.check(
        not mentioned,
        "文档未引用已删除的流水线配置",
        detail_fail="；".join(mentioned),
    )
    check_console_compat(report)


def main() -> int:
    parser = argparse.ArgumentParser(description="交付要求一键自检")
    parser.add_argument("--docker", action="store_true", help="额外验证 Docker 一键部署")
    parser.add_argument("--strict", action="store_true", help="把提示项也计为失败")
    parser.add_argument("--no-lint", action="store_true", help="跳过 ruff 静态检查")
    parser.add_argument("--no-test", action="store_true", help="跳过单元测试")
    parser.add_argument("-v", "--verbose", action="store_true", help="显示全部明细")
    args = parser.parse_args()

    report = Report()
    check_artifacts(report)
    check_frontend_assets(report)
    check_secrets(report)
    check_env_docs(report)
    check_api_contract(report)
    if args.no_lint:
        report.section("6. 静态检查（ruff）")
        report.add(SKIP, "ruff 静态检查", "--no-lint")
    else:
        check_lint(report)
    if args.no_test:
        report.section("7. 单元测试（pytest）")
        report.add(SKIP, "pytest 单元测试", "--no-test")
    else:
        check_tests(report)
    check_rubric(report)
    check_stale_references(report)
    if args.docker:
        check_docker(report)

    report.render(args.verbose)

    print(
        f"\n结果：通过 {report.count(OK)} 项，失败 {report.count(FAIL)} 项，"
        f"提示 {report.count(WARN)} 项，跳过 {report.count(SKIP)} 项"
    )
    if report.passed(args.strict):
        print("交付要求自检通过。")
        return 0
    print("交付要求自检未通过，请修复上述 [FAIL] 项。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
