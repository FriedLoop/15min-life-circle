# 15 分钟生活圈 · 智能体检助手

[![CI](https://github.com/FriedLoop/15min-life-circle/actions/workflows/ci.yml/badge.svg)](https://github.com/FriedLoop/15min-life-circle/actions/workflows/ci.yml)

基于百度地图开放能力，输入任意中心点，自动计算**基于真实路网的 15 分钟步行等时圈**，
统计圈内民生设施覆盖情况，识别设施匮乏的「服务盲区」，并输出可视化体检报告。

---

## 一、为什么不是「画一个圆」

常见的生活圈做法是：以中心点为圆心画一个固定半径的圆。
但现实中的道路并非直线——红绿灯、过街天桥、河流、施工围挡都会显著压缩实际可达范围。

本项目的核心是**用真实路网算路还原可达范围**：

| 对比 | 固定半径圆 | 本项目（真实路网） |
|---|---|---|
| 形状 | 正圆 | 不规则多边形，沿道路延展 |
| 遇到河流/铁路 | 照画不误 | 自然断开，形成缺口 |
| 单侧绕行 | 无法体现 | 该方向可达距离明显缩短 |
| 依据 | 直线距离 | 百度步行批量算路返回的真实耗时 |

实测数据（东莞市，2026-09）：

- 百度步行算路采用固定速度 ≈ **1.17 m/s**（三样本反推 1.170~1.174，高度一致）
- 15 分钟（900 秒）实际可走约 **1056 m 路网距离**
- 实测绕行系数 **1.33 ~ 1.58**（路网距离 ÷ 直线距离）

> 注：百度步行算路未额外计入红绿灯等待时间，属偏乐观估计，报告中的「15 分钟」以官方接口返回值为准。

---

## 二、功能

| 功能 | 说明 |
|---|---|
| **真实路网等时圈** | 网格采样 + 步行批量算路，还原 15 分钟可达范围 |
| **设施覆盖统计** | 10 类民生设施的数量与覆盖率 |
| **服务盲区识别** | 找出 1km 内缺少菜市场 / 药店 / 小学的区域，分三级标注 |
| **健康度评分** | 0~100 综合评分，重点类别权重更高 |
| **可视化报告** | 设施可达性热力图、设施点位标注、覆盖率柱状图、得分雷达图 |
| **示例点位** | 内置松山湖、莞城两个真实社区，一键对比 |

---

## 三、快速开始

### 方式 A：Docker（推荐，评审最省事）

```bash
# 1. 配置密钥
cp backend/.env.example backend/.env
#    编辑 backend/.env，填入百度地图服务端 AK

# 2. 启动
docker compose up --build

# 3. 打开 http://localhost:8000
```

### 方式 B：本地运行

```bash
# Git Bash / Linux / macOS
./start.sh

# Windows PowerShell
.\start.ps1
```

脚本会自动完成：创建 `.env` → 创建虚拟环境 → 安装依赖 → 启动服务。
启动后访问 **http://localhost:8000**（后端同时托管前端页面，单端口即可）。

手动启动：

```bash
cd backend
source venv/Scripts/activate          # Windows；Linux/macOS 用 venv/bin/activate
python -m uvicorn main:app --port 8000
```

### 运行测试

```bash
cd backend
python -m pip install pytest
python -m pytest tests/ -v
```

覆盖内容：地理计算、进程内缓存、设施分类、可达性得分、等时圈降级路径、报告聚合链路。

外部地图接口全部使用 mock，**运行测试不消耗任何 API 配额**。
其中 `tests/test_report.py` 会完整跑一遍报告生成链路，
用于捕获「变量名写错、参数漏传」这类只在运行时才暴露的问题。

---

## 四、环境变量

配置文件：`backend/.env`（从 `.env.example` 复制而来，已被 `.gitignore` 排除）

| 变量 | 必填 | 说明 |
|---|---|---|
| `BAIDU_SERVER_AK` | ✅ | 百度地图**服务端** AK，用于地点检索、批量算路、地理编码 |
| `BAIDU_BROWSER_AK` | ✅ | 百度地图**浏览器端** AK，前端加载地图用。**必须在控制台配置 Referer 白名单** |
| `BAIDU_API_BASE` | | 百度 Web 服务 API 基址，默认 `https://api.map.baidu.com`，一般无需修改 |
| `HTTP_MAX_CONCURRENCY` | | 并发上限，默认 3（个人开发者配额上限，调高会被限流） |
| `HTTP_TIMEOUT` | | 单次请求超时（秒），默认 10 |
| `HTTP_RETRIES` | | 网络错误重试次数，默认 2 |
| `WALK_MINUTES` | | 生活圈时间阈值（分钟），默认 15 |
| `WALK_SPEED_MPS` | | 步行速度（m/s），默认 1.2。仅在批量算路降级为直线估算时用于折算耗时 |
| `GRID_STEP_M` | | 网格间隔（米），默认 150。调大省配额，调小边界更精细 |
| `GRID_COARSE_STEP_M` | | 分级网格优化的粗网格间隔（米），默认 500。阶段5 可选优化，**当前未启用** |
| `ISOCHRONE_MAX_RADIUS_M` | | 网格覆盖半径（米），默认 1200 |
| `ROUTEMATRIX_BATCH_SIZE` | | 单次批量算路携带的终点数，默认 50 |
| `BLINDSPOT_DISTANCE_M` | | 盲区判定阈值（米），默认 1000 |
| `POI_SEARCH_RADIUS_M` | | POI 检索半径（米），默认 2000（须显著大于等时圈半径） |
| `DETOUR_FACTOR` | | 绕行系数上限，默认 1.6，用于盲区直线初筛 |
| `GREY_ZONE_CANDIDATES` | | 灰色地带精算时取的候选设施数，默认 3 |
| `CATEGORY_WEIGHT_KEY` / `CATEGORY_WEIGHT_NORMAL` | | 评分权重，重点三类 1.5 / 其余 1.0 |
| `CACHE_ENABLED` | | 结果缓存开关，默认 true |
| `CACHE_TTL_SECONDS` / `CACHE_MAX_SIZE` | | 缓存过期（秒，默认 3600）/ 容量（默认 64） |
| `CACHE_COORD_PRECISION_M` | | 缓存坐标量化粒度（米），默认 50 |
| `CORS_ORIGINS` | | 允许的跨域来源，默认 `*` |

### AK 申请要点

百度地图开放平台需创建**两个应用**，类型不能混用：

| 应用类型 | 用途 | 校验方式 |
|---|---|---|
| 服务端 | 后端调用 Web 服务 API | IP 白名单（建议留空） |
| 浏览器端 | 前端 JS API 加载地图 | **Referer 白名单**（填 `localhost`、`127.0.0.1` 及部署域名） |

常见错误码：

| 状态码 | 含义 | 处理 |
|---|---|---|
| 200 | AK 有误 | 检查 AK 是否复制完整 |
| 210 / 240 | 服务被禁用 | 控制台中该应用**未开通对应服务**，需勾选 |
| 220 | Referer 校验失败 | 浏览器端 AK 的白名单未包含当前域名 |
| 302 | 配额超限 | 次日恢复或申请提额 |

---

## 五、API

启动后访问 `http://localhost:8000/docs` 查看交互式文档（FastAPI 自动生成）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| GET | `/api/config` | 下发前端配置（AK、示例点位、设施类别） |
| POST | `/api/geocode` | 地名 → BD09 坐标 |
| POST | `/api/reverse_geocode` | 坐标 → 结构化地址 |
| POST | `/api/get_poi` | POI 检索 |
| POST | `/api/isochrone` | 计算等时圈 |
| POST | `/api/blindspot` | 盲区识别 |
| POST | `/api/report` | **综合体检报告**（等时圈+覆盖+盲区+评分） |

> 坐标系约定：全部接口统一使用 **BD09**（百度经纬度），与百度地图 JS API 点击取点一致。

---

## 六、算法说明

### 1. 等时圈：网格采样 + 批量算路

```
中心点 → 生成网格(半径1200m / 间隔150m)
       → 分批调步行批量算路(每批≤50终点，并发3)
       → 筛选 duration ≤ 900秒
       → 前端逐格绘制色块 + 按邻接关系描边成外轮廓
```

**为何用网格法而非射线法**：射线法只得到边界上稀疏的点，无法表达区域内部差异，
画不出评分要求的「热力图」；网格法内部有完整的逐点分布，既能画热力图，
又能直接复用于盲区分析。

**为何不用凸包做轮廓**：凸包会把可达范围的凹陷与缺口全部抹平，
画出来又变成接近圆的形状，恰恰丢掉了「真实路网 ≠ 直线距离」这一核心结论。
因此前端按网格单元逐个绘制半透明正方形色块，再遍历每个可达格子、
凡是某个方向没有相邻可达格子就描出那条边，拼成保留凹陷与缺口的真实外轮廓。
后端不计算凸包——原先返回的 `polygon` 字段已移除。

### 2. 盲区识别：直线初筛 + 路网精算

对每个可达点，记 `d` = 到该类最近设施的**直线距离**：

| 条件 | 结论 | 是否调 API |
|---|---|---|
| 该类在范围内无设施 | 必然盲区 | 否 |
| `d > 1000m` | 必然盲区（路网 ≥ 直线） | 否 |
| `d < 625m`（1000 ÷ 绕行系数1.6） | 必然非盲区 | 否 |
| `625m ≤ d ≤ 1000m`（灰色地带） | 需真实路网距离 | **是** |

前三类由几何性质保证成立。实测约 **81%** 的判定可由初筛直接得出，大幅节省配额。

### 3. 健康度评分

```
score = 100 × Σ(权重ᵢ × 覆盖率ᵢ) / Σ(权重ᵢ)
```

权重：赛题点名的三类（菜市场 / 药店 / 小学）为 1.5，其余为 1.0。

---

## 七、配额与性能

百度个人开发者日配额（本项目实际用量）：

| 服务 | 日配额 | 单次完整分析 |
|---|---|---|
| 批量算路 | 5000 条 | 网格点数（默认 150m 间隔 = 197）+ 灰色地带精算次数 × 候选数（≤3），实测约 600 条 |
| 地点检索 | 100 次 | 10 次（逐类检索，每类最多翻 2 页） |
| 地理编码 | 5000 次 | 1 次 |
| 逆地理编码 | 300 次 | 1 次 |

> 网格点数取决于间隔：`GRID_STEP_M` 默认 150 → 197 点。
> `/api/isochrone` 与 `/api/report` 均遵循该配置（`step_m` 留空即取配置值）。

**优化手段**：

1. **结果缓存**：坐标量化到 50m，相同位置重复查询不消耗配额
2. **直线初筛**：砍掉约 80% 的盲区算路调用
3. **按需检索**：可只查关心的类别（调试时用「仅关键三类」）
4. **降级容错**：批量算路不可用时退化为直线估算，响应标记 `degraded: true`

单次完整分析约需 **30~60 秒**（受并发上限 3 限制），命中缓存后**秒级返回**。

---

## 八、目录结构

```
15min-life-circle/
├── backend/
│   ├── app/
│   │   ├── core/       config.py(配置) constants.py(设施分类) samples.py(示例点位)
│   │   ├── schemas/    models.py(数据模型)
│   │   ├── services/   baidu_client(限流重试) routematrix(批量算路) geocoding
│   │   │               poi isochrone blindspot report
│   │   ├── routers/    health config poi geocode isochrone report
│   │   └── utils/      geo.py(距离/网格/坐标量化) cache.py(TTL+LRU缓存)
│   ├── scripts/        delivery_check(交付自检) check_quota test_isochrone
│   │                   test_report resolve_location
│   ├── tests/          pytest 用例（外部接口全部 mock，不消耗配额）
│   ├── main.py         应用入口
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── css/style.css
│   └── js/             config api map layers charts main
├── docs/               技术方案.md / 测试报告.md / 手动测试清单.md
├── .github/workflows/  GitHub Actions 流水线（ci.yml）
├── ruff.toml           静态检查规则
├── Dockerfile
├── docker-compose.yml
├── start.sh / start.ps1
└── README.md
```

---

## 九、示例点位

| 点位 | 坐标（BD09） | 特征 |
|---|---|---|
| 东莞理工学院（松山湖校区） | `113.881641, 22.909011` | 规划新区，配套稀疏，易暴露盲区 |
| 东莞理工学院（莞城校区） | `113.779678, 23.057248` | 老城区，配套密集但绕行严重 |

两点位形成对比：**新城「直线近、配套少」 vs 老城「配套多、走不到」**。

> 坐标经「地理编码 + 地点检索」交叉验证。莞城校区的地理编码结果曾偏差 4273 米，
> 已改用地点检索的 POI 标注坐标——对学校、园区这类面状地物，地理编码可能落在边界或道路上，必须交叉验证。

---

## 十、技术栈

- **后端**：Python 3.11+ / FastAPI / httpx（异步并发）/ Pydantic
- **前端**：原生 HTML + CSS + JavaScript（无构建步骤，评审可直接运行）
- **地图**：百度地图 JavaScript API、Web 服务 API
- **图表**：纯 SVG 自绘（`js/charts.js`），不引入 ECharts 等 CDN 依赖
- **代码质量**：pytest（单元测试）+ ruff（静态检查）

---

## 十一、CI/CD 与代码检查

**构建状态**：[![CI](https://github.com/FriedLoop/15min-life-circle/actions/workflows/ci.yml/badge.svg)](https://github.com/FriedLoop/15min-life-circle/actions/workflows/ci.yml)
—— 全部通过，运行记录见徽章链接。

CI 由 **GitHub Actions** 承载，配置见 `.github/workflows/ci.yml`。
推送到 `master` / `dev` 或提交 PR 时自动执行：

1. `pip install -r backend/requirements.txt` 安装依赖
2. `ruff check backend/` 静态检查与格式检查
3. `python -m pytest backend/tests/ -v` 运行单元测试（外部接口全部 mock，**不消耗 API 配额**）
4. `python backend/scripts/delivery_check.py --no-lint --no-test` 交付要求自检
   （交付物、密钥安全、文档一致性、API 契约、评分维度逐条证据）

另有一个独立的 `docker` job，用于自动验证「评审可用 Docker 一键跑通」这一交付要求：

- `docker build` 构建镜像
- 启动容器，断言 `GET /` 返回前端页面、`GET /api/health` 返回 `status: ok`
- 失败时自动输出容器日志

### 本地等价的检查（与 CI 完全一致）

在**仓库根目录**执行：

```powershell
pip install -r backend/requirements.txt
python -m pytest backend/tests/ -v
ruff check backend/          # 检查
ruff check backend/ --fix    # 自动修复
```

规则集定义在 `ruff.toml`（pycodestyle + pyflakes + isort + pyupgrade + bugbear）。

### 交付要求自检（一条命令）

提交或评审前，用一条命令确认全部交付要求是否满足：

```powershell
python backend/scripts/delivery_check.py
```

检查项：

| # | 检查内容 | 判定方式 |
|---|---|---|
| 1 | 交付物完整性 | 文档、部署脚本、CI、依赖清单等必须文件是否存在 |
| 2 | 前端资源完整性 | `index.html` 引用的本地 css/js 是否都存在 |
| 3 | 密钥安全 | `.env` 是否被忽略且未被追踪、示例文件中是否只有占位符、镜像是否排除密钥 |
| 4 | 环境变量文档一致性 | 解析 `Settings` 字段，比对 `.env.example` 与 README 是否都已说明 |
| 5 | API 契约一致性 | 代码注册的 `/api/*` 路由与 README 接口表双向比对 |
| 6 | 静态检查 | `ruff check backend/` |
| 7 | 单元测试 | `python -m pytest backend/tests/ -q` |
| 8 | **交付要求与评分维度逐条核对** | 对照赛题《交付要求》与《评审维度》，逐条在文档 / 代码中查找实际证据 |
| 9 | 文档一致性 | 不引用已删除的流水线配置（避免文档自相矛盾） |
| 10 | Docker 一键部署 | 可选，`--docker` 构建镜像并断言 `/api/health`、`/` 可用 |

第 8 项把评分标准逐条落到可验证的证据上，共 16 条：

| 评分维度（权重） | 核对条目 | 证据位置 |
|---|---|---|
| 交付要求 | 开源许可证 | `LICENSE`（MIT） |
| 交付要求 | 一键式部署脚本 | `start.sh` / `start.ps1` / `Dockerfile` / `docker-compose.yml` / `.env.example` |
| 交付要求 | 预置示例数据 | `core/samples.py` + `/api/config` 下发样例点位 |
| 交付要求 | 技术设计文档 | `docs/技术方案.md`（API 策略 / 等时圈 / POI 清洗 / 盲区算法） |
| 交付要求 | 真实社区对比测试报告 | `docs/测试报告.md`（松山湖 vs 莞城） |
| 功能正确性 40% | 地图基础能力 | `/geocoding/v3`、`/place/v2/search`、`/routematrix/v2/walking` |
| 功能正确性 40% | 等时圈热力图 | `services/isochrone.py` + `js/layers.js` 的 `drawAccessibility` / `drawBoundary` |
| 功能正确性 40% | 盲区识别 | `BLINDSPOT_CATEGORIES`（菜市场 / 药店 / 小学）+ `BLINDSPOT_DISTANCE_M=1000` |
| API 深度调用 30% | 批量距离矩阵 + 并发 | `routematrix.py` 分批 + `baidu_client.py` 的 `Semaphore` |
| API 深度调用 30% | 容错与降级 | `degraded` 标记、`return_exceptions=True`、`BaiduApiError` |
| API 深度调用 30% | 空间插值 | `generate_square_grid` + `DETOUR_FACTOR` 直线初筛 |
| 产品交互 15% | 可视化 | `layers.js` 热力图 + `charts.js` 柱状图 / 雷达图 |
| 产品交互 15% | 自定义中心点 | `map.js` 的 `setCenter` / `onSelect` + 样例点选择 |
| 开源工程规范 15% | 代码规范 | 分层目录 + `ruff.toml` |
| 开源工程规范 15% | 文档与部署 | README 环境变量 / 快速开始 + `.env.example` 占位符 |
| 开源工程规范 15% | CI/CD | `.github/workflows/ci.yml`（ruff + pytest + docker job） |

退出码 `0` 表示通过；存在 `[FAIL]` 时返回 `1`。全部通过即代表交付要求已满足。

> 自动化脚本无法覆盖「地图渲染是否真的不规则」「降级注入后表现如何」等需要人眼与真实接口确认的部分，
> 这部分请按 [`docs/手动测试清单.md`](docs/手动测试清单.md) 逐项走查（9 组 64 项）。

```powershell
python backend/scripts/delivery_check.py --docker   # 额外验证 Docker 一键部署
python backend/scripts/delivery_check.py --strict   # 把 [WARN] 也视为失败
python backend/scripts/delivery_check.py -v         # 显示全部通过项的明细
```

---

## 许可证

MIT License
