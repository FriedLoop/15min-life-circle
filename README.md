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
| **坐标系转换** | WGS84 / GCJ02 / BD09 互转；界面可声明坐标来源，后端统一转 BD09 再分析（百度 geoconv 接口 + 本地算法兜底） |
| **真实路网等时圈** | 网格采样 + 步行批量算路，还原 15 分钟可达范围 |
| **双图层热力图** | 可切换「设施可达性」（有没有配套用）与「步行耗时」（路网让这段距离多费劲），后者直观证明等时圈不是圆 |
| **设施覆盖统计** | 10 类民生设施的数量与覆盖率 |
| **服务盲区识别** | 找出 1km 内缺少菜市场 / 药店 / 小学的区域，分三级标注；可按类别单独标注，并给出逐类盲区率 |
| **设施检索面板** | 直接调用 `/api/get_poi` 展示未经等时圈过滤的原始 POI 与各类数量，可核对覆盖率的统计底数 |
| **健康度评分** | 0~100 综合评分，重点类别权重更高 |
| **配额实证** | 响应回传真实算路条数与灰色地带精算次数，界面标注缓存命中状态 |
| **数据基准校验** | 用东莞市医保局 / 教育局 / 民政局的政务公开名录交叉验证百度 POI 检索，量化召回率并暴露自身口径缺陷 |
| **示例点位** | 内置松山湖、莞城、虎门北栅三个真实社区，一键对比 |

---

## 三、快速开始

> **只需一步**：把两个 AK 通过环境变量传给启动命令即可，**不需要编辑任何文件**。
> 两个 AK 都必填——服务端 AK 用于检索与算路，浏览器端 AK 用于加载地图，
> 缺任意一个都会导致功能不完整（缺浏览器端 AK 表现为地图白屏，页面顶部会明确提示）。

### 方式 A：Docker（推荐）

```bash
# Linux / macOS / Git Bash —— 一行命令，不碰任何文件
BAIDU_SERVER_AK=你的服务端AK BAIDU_BROWSER_AK=你的浏览器端AK docker compose up --build
```

```powershell
# Windows PowerShell
$env:BAIDU_SERVER_AK="你的服务端AK"; $env:BAIDU_BROWSER_AK="你的浏览器端AK"; docker compose up --build
```

打开 **http://localhost:8000** 即可（后端同时托管前端页面，单端口）。

<details>
<summary>Docker 构建失败？多半是拉不到基础镜像（国内网络）</summary>

直连 Docker Hub 在国内常常超时（表现为 `python:3.11-slim` 拉取失败）。三种绕法任选：

```bash
# ① 换构建源（不需要改 Docker 全局配置）
docker compose build --build-arg BASE_IMAGE=docker.1ms.run/library/python:3.11-slim
docker compose up

# ② 先拉加速源的同名镜像再打回官方标签
docker pull docker.1ms.run/library/python:3.11-slim
docker tag docker.1ms.run/library/python:3.11-slim python:3.11-slim
docker compose up --build

# ③ 给 Docker Desktop 配置镜像加速源（Settings → Docker Engine，加 registry-mirrors）
#    可用的加速源：https://docker.1ms.run  https://docker.m.daocloud.io  https://hub.rat.dev
```

</details>

### 方式 B：本地运行

```bash
# Git Bash / Linux / macOS —— 一行命令，不碰任何文件
BAIDU_SERVER_AK=你的服务端AK BAIDU_BROWSER_AK=你的浏览器端AK ./start.sh

# 也支持参数形式
./start.sh --server-ak 你的服务端AK --browser-ak 你的浏览器端AK
```

```powershell
# Windows PowerShell
.\start.ps1 -ServerAk 你的服务端AK -BrowserAk 你的浏览器端AK
```

脚本依次完成：创建虚拟环境 → 安装依赖 → 启动服务。
依赖默认走清华镜像，失败时自动回退官方源。

**未提供 AK 时脚本不会中断**：服务照常启动，页面顶部显示「后端缺 AK 配置」。
这是刻意的——「服务起不来」和「缺一行配置」是两类完全不同的故障，
用同一种方式表达会让人误以为部署失败。

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

覆盖内容：地理计算与 IDW 插值、坐标系互转、进程内缓存、设施分类与检索词拼接、
可达性得分、等时圈降级路径与分级网格剪枝、报告聚合链路、接口契约与单端口部署。

外部地图接口全部使用 mock，**运行测试不消耗任何 API 配额**。
其中 `tests/test_report.py` 会完整跑一遍报告生成链路，
用于捕获「变量名写错、参数漏传」这类只在运行时才暴露的问题。

---

## 四、环境变量

配置来源有两条，**进程环境变量优先于配置文件**，因此两者不会互相干扰：

1. 启动命令前直接传（推荐，见第三章）：`BAIDU_SERVER_AK=xxx docker compose up --build`
2. 配置文件：`backend/.env`（从 `.env.example` 复制而来，已被 `.gitignore` 排除）

> **密钥脱敏**：仓库内所有文档与示例文件只出现变量名和占位符，**不含任何真实 AK**；
> 镜像同样不含密钥（`.dockerignore` 已排除），配置一律在运行时注入。

| 变量 | 必填 | 说明 |
|---|---|---|
| `BAIDU_SERVER_AK` | ✅ | 百度地图**服务端** AK，用于地点检索、批量算路、地理编码 |
| `BAIDU_BROWSER_AK` | ✅ | 百度地图**浏览器端** AK，前端加载地图用。**必须在控制台配置 Referer 白名单**，否则地图白屏 |
| `BAIDU_API_BASE` | | 百度 Web 服务 API 基址，默认 `https://api.map.baidu.com`，一般无需修改 |
| `HTTP_MAX_CONCURRENCY` | | 并发上限，默认 3（个人开发者配额上限，调高会被限流） |
| `HTTP_TIMEOUT` | | 单次请求超时（秒），默认 10 |
| `HTTP_RETRIES` | | 网络错误重试次数，默认 2 |
| `WALK_MINUTES` | | 生活圈时间阈值（分钟），默认 15 |
| `WALK_SPEED_MPS` | | 步行速度（m/s），默认 1.17（按百度步行算路实测反推）。降级估算与分级网格剪枝都依赖该值 |
| `GRID_STEP_M` | | 网格间隔（米），默认 150。调大省配额，调小边界更精细 |
| `GRID_COARSE_STEP_M` | | 分级网格优化的粗网格间隔（米），默认 450（= 3 × 主步长）。仅在请求 `coarse_grid=true` 时生效 |
| `GRID_STRATEGY_MARGIN` | | 分级网格剪枝边界余量（比例），默认 0.05。兜不住「路网被水域切断」的误判，详见技术方案 §5 |
| `IDW_POWER` / `IDW_NEIGHBORS` | | IDW 插值参数：距离衰减指数（默认 2）/ 参与插值的最近样本数（默认 8） |
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

### 部署自检（30 秒）

```bash
curl http://localhost:8000/api/health
# 期望：{"status":"ok","ak_configured":true,"browser_ak_configured":true,"walk_minutes":15}
```

| 返回值 | 含义与处理 |
|---|---|
| `ak_configured: false` | 服务端 AK 未配置，**或仍是 `.env.example` 里的模板占位符**。页面顶部会显示「后端缺 AK 配置」 |
| `browser_ak_configured: false` | 浏览器端 AK 未配置 → 地图会白屏。页面顶部会显示「地图 AK 未配置（地图将白屏）」 |
| 两者均为 `true` | 打开 http://localhost:8000 即可正常使用 |

> 占位符也算「未配置」：`.env.example` 里的 `your_baidu_server_ak_here` 非空，
> 若只做非空判断，界面会显示「已就绪」而每个请求都失败——这类"说好了却报错"的问题最难自查。

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
| POST | `/api/convert` | **坐标转换**：WGS84 / GCJ02 → BD09 |
| POST | `/api/reverse_geocode` | 坐标 → 结构化地址 |
| POST | `/api/get_poi` | POI 检索 |
| POST | `/api/isochrone` | 计算等时圈 |
| POST | `/api/blindspot` | 盲区识别 |
| POST | `/api/report` | **综合体检报告**（等时圈+覆盖+盲区+评分） |

> 坐标系约定：全部接口**输出**统一为 **BD09**（百度经纬度），与百度地图 JS API 点击取点一致。
>
> **输入**侧可用 `coord_type` 声明来源坐标系（`bd09` / `gcj02` / `wgs84`），后端先转换为 BD09 再分析。
> 这一步不能省：三者定位同一地点最多相差 600 米以上，WGS84（GPS、GeoJSON）或
> GCJ02（高德、腾讯）的坐标若被当成 BD09 直接使用，等时圈与盲区结论会整体平移。
> 前端「手动输入坐标」处可选坐标系，并实时展示转换结果与偏移量。

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

> 已知边界条件：`d < 625m → 必然非盲区` 依赖「路网距离 ≤ 1.6 × 直线距离」这一绕行系数上界。
> 实测（松山湖校区）存在被水域 / 围墙切断的点，等效绕行系数可达 **2.8**，
> 这类点会被初筛误判为「非盲区」（漏报）。方向上的取舍是刻意的：
> 漏报比多算几个点严重，所以这里宁可放宽系数；若要彻底消除，
> 只能对初筛结论也做抽样复核，代价是配额。实测数据见技术方案 §5。

### 3. 健康度评分

```
score = 100 × Σ(权重ᵢ × 覆盖率ᵢ) / Σ(权重ᵢ)
```

权重：赛题点名的三类（菜市场 / 药店 / 小学）为 1.5，其余为 1.0。

### 4. 网格策略与空间插值：算路调用量 vs 面积误差

除默认的「单级精细网格」外，接口还支持 `coarse_grid=true` 启用
**分级网格 + IDW 插值**：用几何性质剪掉「判定可达 / 判定不可达」的采样点，
只对灰色地带做真实算路，其余耗时由反距离加权（IDW）插值补全。
另有一个**扇形采样 + IDW** 方案作为对照（只沿 20 个方向 × 6 个距离采样）。

实测（松山湖校区，2026-10-15，`backend/scripts/compare_grid_strategies.py`）：

| 策略 | 算路调用 | 省配额 | 可达面积 | 面积误差 | IoU |
|---|---|---|---|---|---|
| 单级精细网格（默认/基准） | 197 | — | 1.417 km² | 0%（基准） | 1.00 |
| 分级网格 + IDW | 125 | **36.5%** | 1.530 km² | **7.94%** | 0.93 |
| 扇形采样 + IDW | 120 | 39.1% | 1.417 km² | 0% | 0.88 |

**结论**：分级网格省 36.5% 算路，代价是**可达面积高估 7.94%**——
被剪掉的点里有 5 个实际被水域/围墙切断（直线 424~618 m，真实耗时 1023~1480 s）。
因此它是**有损近似，默认关闭**；配额充足时用单级网格，界面与文档都明确标注了这一点。
扇形采样省得更多但同样有代价（面积对上了，但可达格子的位置有 12% 不一致，IoU 0.88）。

IDW 只用于给「已由几何定论」的点补一个耗时值，供耗时热力图着色：
必然可达区实测中位误差 114 秒（阈值 900 秒），必然不可达区本就只有判定意义。
等时圈**边界**始终由真实算路决定，不依赖插值。

### 5. 数据可信度：用政务公开名录交叉校验百度 POI

覆盖率与盲区率全部建立在百度 POI 检索之上，而百度是**商业收录**——
漏掉真实设施会让覆盖率虚低、盲区率虚高，且报告本身看不出异常。
所以引入一份不依赖百度、来源可追溯的基准：东莞市**医保局 / 教育局 / 民政局 /
市场监管局**公开发布的民生设施名录（药店 232 条、幼儿园 31 条、学校 55 条等），
冻结为 `backend/scripts/authority_benchmark/*.csv`。

方法：权威地址地理编码定位 → 取检索半径内的记录 → 与该类目的 POI 检索结果
按**归一化名称**配对（不用距离配对，原因见下）→ 统计召回率。

| 类别 | 半径内权威数 | 命中 | 召回率 |
|---|---|---|---|
| 幼儿园 | 7 | 7 | **100%** |
| 小学 | 8 | 3 | 37.5% |
| 药店 | 47 | 19 | 40.4% |

**两个必须说清楚的结论**：

1. **校园类统计可信**：幼儿园全部命中；小学未覆盖的 5 条里 4 条经「名称直查」
   证明百度库里有它——只是没进入我们的检索结果。
2. **发现一处属于我们自己的口径缺陷**：地点检索每类最多 2 页 × 20 条 = 40 条，
   且实测按**相关性而非距离**排序（莞城药店返回的 40 条距离跨 398~1811 m）。
   莞城、虎门的药店与幼儿园检索**全部触顶**，说明半径内仍有同类设施未被返回，
   **偏差方向是覆盖率虚低、盲区率虚高**。该局限已写入测试报告「已知局限」，
   未做静默修正（修正需提高翻页数，会让地点检索消耗从 10 次/分析升到 20~30 次，
   而日配额仅 100 次）。

**顺带记一个方法论教训**：初版用「距离 ≤ 100/300 m」配对，得到的「漏检」距离
密集落在 372~536 m，看上去像百度大面积漏检；实际是**地址地理编码只精确到路口**，
与 POI 的建筑物入口坐标天然差几百米。改用名称配对后未覆盖数直接降了三分之一。
若不修这一步，这个校验会得出完全错误的结论。

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

1. **结果缓存**：坐标量化到 50m，相同位置重复查询不消耗配额（响应里 `cached` 字段与界面徽标都会标注）
2. **直线初筛**：砍掉约 80% 的盲区算路调用
3. **分级网格 + IDW 插值**（`coarse_grid=true`）：等时圈算路量降 36.5%，代价是面积误差 7.94%，默认关闭
4. **按需检索**：可只查关心的类别（调试时用「仅关键三类」）
5. **降级容错**：批量算路不可用时退化为直线估算，响应标记 `degraded: true`

配额不是「估算」而是**可核对的实测值**：`/api/isochrone` 与 `/api/report` 的响应里
`isochrone.routed_points` 是本次真实发起的算路终点数、`blindspot.precise_calls` 是
灰色地带路网精算次数，界面「体检报告」顶部与地图图例都会如实展示。

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
│   │   │               poi isochrone blindspot report coordconv(坐标转换服务)
│   │   ├── routers/    health config poi geocode isochrone report convert
│   │   └── utils/      geo.py(距离/网格/IDW插值) coordinate.py(坐标系互转)
│   │                   cache.py(TTL+LRU缓存)
│   ├── scripts/        delivery_check(交付自检) check_quota test_isochrone
│   │                   compare_grid_strategies(三策略对照实验)
│   │                   collect_authority_data(采集政务权威名录)
│   │                   authority_benchmark(权威名录交叉校验)
│   │                   authority_benchmark/(冻结的名录快照 + 来源清单)
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
| 东莞市虎门镇北栅行政小区 | `113.723151, 22.833109` | 老镇区居住社区，商住混杂、路网密而曲折 |

三点位构成三种城市形态：**新区「直线近、配套少」vs 老城学府「配套多、走不到」
vs 老镇区社区「商住混杂、路网密」**。

> 第三点对应赛题要求的「社区/街道」样本——前两点是学校校区，严格说属园区而非社区。
> 它位于虎门镇九方工贸大厦旁约 87 m。

> 坐标一律经「地理编码 + 地点检索」交叉验证。莞城校区的地理编码结果曾偏差 4273 米，
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

第 8 项把评分标准逐条落到可验证的证据上，共 20 条：

| 评分维度（权重） | 核对条目 | 证据位置 |
|---|---|---|
| 交付要求 | 开源许可证 | `LICENSE`（MIT） |
| 交付要求 | 一键式部署脚本 | `start.sh` / `start.ps1` / `Dockerfile` / `docker-compose.yml` / `.env.example` |
| 交付要求 | 预置示例数据 | `core/samples.py` 三个交叉验证点位（含虎门北栅社区）+ `/api/config` 下发 |
| 交付要求 | 技术设计文档 | `docs/技术方案.md`（API 策略 / 等时圈 / POI 清洗 / 盲区算法 / 网格策略对照） |
| 交付要求 | 真实社区对比测试报告 | `docs/测试报告.md`（松山湖 vs 莞城） |
| 功能正确性 40% | 地图基础能力 | `/geocoding/v3`、`/place/v2/search`、`/routematrix/v2/walking` |
| 功能正确性 40% | **坐标转换能力** | `utils/coordinate.py` 三系互转 + `/api/convert` + 前端坐标系选择 |
| 功能正确性 40% | 等时圈热力图 | `services/isochrone.py` + `js/layers.js` 的 `drawAccessibility` / `drawBoundary` |
| 功能正确性 40% | 盲区识别 | `BLINDSPOT_CATEGORIES`（菜市场 / 药店 / 小学）+ `BLINDSPOT_DISTANCE_M=1000` |
| API 深度调用 30% | 批量距离矩阵 + 并发 | `routematrix.py` 分批 + `baidu_client.py` 的 `Semaphore` |
| API 深度调用 30% | 容错与降级 | `degraded` 标记、`return_exceptions=True`、`BaiduApiError` |
| API 深度调用 30% | **配额实证** | 响应回传 `routed_points` / `precise_calls`，前端展示缓存与精算次数 |
| API 深度调用 30% | 空间插值 | `generate_square_grid` + `DETOUR_FACTOR` 直线初筛 |
| API 深度调用 30% | **IDW 插值 + 三策略对照** | `utils/geo.py` 的 `idw_interpolate` + `scripts/compare_grid_strategies.py` |
| API 深度调用 30% | **数据可信度交叉校验** | `scripts/authority_benchmark.py` + 政务名录快照 + `技术方案.md` §4.5 |
| 产品交互 15% | 可视化（双图层 + 逐类盲区率） | `layers.js` 可达性/耗时双图层 + `charts.js` + `main.js` 逐类盲区表 |
| 产品交互 15% | 自定义中心点 + 设施检索面板 | `map.js` 的 `setCenter` / `onSelect` + 样例点 + `/api/get_poi` 面板 |
| 开源工程规范 15% | 代码规范 | 分层目录 + `ruff.toml` |
| 开源工程规范 15% | 文档与部署 | README 环境变量 / 快速开始 + `.env.example` 占位符 |
| 开源工程规范 15% | CI/CD | `.github/workflows/ci.yml`（ruff + pytest + docker job） |

退出码 `0` 表示通过；存在 `[FAIL]` 时返回 `1`。全部通过即代表交付要求已满足。

> 自动化脚本无法覆盖「地图渲染是否真的不规则」「降级注入后表现如何」等需要人眼与真实接口确认的部分，
> 这部分请按 [`docs/手动测试清单.md`](docs/手动测试清单.md) 逐项走查（9 组 108 项）。

```powershell
python backend/scripts/delivery_check.py --docker   # 额外验证 Docker 一键部署
python backend/scripts/delivery_check.py --strict   # 把 [WARN] 也视为失败
python backend/scripts/delivery_check.py -v         # 显示全部通过项的明细
```

---

## 许可证

MIT License
