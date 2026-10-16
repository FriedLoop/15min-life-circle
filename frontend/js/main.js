/**
 * 应用入口：串联配置加载、地图初始化、分析流程与结果渲染。
 *
 * 整体流程：
 *   拉取后端配置(AK/示例点位/类别) → 加载百度地图 → 用户选点
 *   → 调用 /api/report → 绘制等时圈与盲区 → 渲染评分与图表
 *
 * 坐标系处理（重要）：
 *   界面上的中心点可能来自三个地方，坐标系各不相同：
 *     示例点位 / 地图点击 / 地理编码  → 百度返回，本来就是 BD09
 *     手工粘贴的坐标                  → 用户声明 bd09 / gcj02 / wgs84
 *   因此 state 里同时保存「用户声明的原始坐标 + 坐标系」与「转换后的 BD09」：
 *     原始坐标直接透传给后端（coord_type 一并传），由后端统一转 BD09 再分析；
 *     转换后的 BD09 只用于地图标记与界面显示（百度地图按 BD09 渲染）。
 *   这样界面上展示的转换结果与后端实际使用的坐标是同一套转换链路。
 */
(function () {
    const state = {
        // 用户声明的原始输入坐标与坐标系（请求里原样透传）
        inputLng: null,
        inputLat: null,
        coordType: 'bd09',
        // 转换后的 BD09 坐标（仅用于地图与显示）
        bdLng: null,
        bdLat: null,
        // 中心点来源说明，例如「示例点位：xxx」
        sourceNote: '',
        analyzing: false,
        // 最近一次报告与当前图层设置：切换图层无需重新请求
        report: null,
        layer: 'accessibility',
        blindCategory: '__any__',
    };

    const $ = (id) => document.getElementById(id);

    // ------------------------------------------------------------------
    // 通用 UI 辅助
    // ------------------------------------------------------------------
    function setStatus(text, cls) {
        const el = $('backend-status');
        el.textContent = text;
        el.className = 'badge ' + cls;
    }

    /** 转义用户/接口返回的文本，避免 POI 名称里的 < & 破坏页面结构 */
    function escapeHtml(text) {
        return String(text == null ? '' : text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    let loadingTimer = null;

    function showLoading(text) {
        $('loading-mask').hidden = false;
        const label = text || '正在分析…';
        const startedAt = Date.now();

        // 分析需多轮调用地图接口，耗时以十秒计，必须显示计时否则用户以为卡死
        const tick = () => {
            const sec = Math.round((Date.now() - startedAt) / 1000);
            $('loading-text').textContent = `${label}（已用 ${sec} 秒）`;
        };

        tick();
        clearInterval(loadingTimer);
        loadingTimer = setInterval(tick, 1000);
    }

    function hideLoading() {
        clearInterval(loadingTimer);
        loadingTimer = null;
        $('loading-mask').hidden = true;
    }

    function alertError(msg) {
        hideLoading();
        window.alert(msg);
    }

    // ------------------------------------------------------------------
    // 中心点
    // ------------------------------------------------------------------
    /**
     * 记录中心点。input* 为原始输入，bd* 为转换后的 BD09。
     * @param {string} note 来源说明
     */
    function applyCenter(inputLng, inputLat, coordType, bdLng, bdLat, note) {
        const changed =
            state.inputLng !== inputLng ||
            state.inputLat !== inputLat ||
            state.coordType !== (coordType || 'bd09');

        state.inputLng = inputLng;
        state.inputLat = inputLat;
        state.coordType = coordType || 'bd09';
        state.bdLng = bdLng == null ? inputLng : bdLng;
        state.bdLat = bdLat == null ? inputLat : bdLat;
        state.sourceNote = note || '';
        updateCoordText();

        if (changed) resetResults();
    }

    /**
     * 换了中心点就丢掉上一处的结论。
     *
     * 不这么做的话，地图上会残留旧点位的热力图与盲区标注，
     * 侧栏却显示「当前中心点」已变——用户很容易把两张图当成同一处的结论。
     */
    function resetResults() {
        state.report = null;
        state.blindCategory = '__any__';
        $('report-panel').hidden = true;
        $('poi-panel').hidden = true;
        $('map-controls').hidden = true;
        $('poi-result').innerHTML = '';
        $('layer-note').textContent = '';
        $('legend-grid').textContent = '网格单元：—';
        if (MapManager.map) MapManager.clearOverlays();
        // 报告没了，侧栏空出来了，把输入区重新展开
        setInputPanelsOpen(true);
    }

    // ------------------------------------------------------------------
    // 面板折叠
    // ------------------------------------------------------------------

    /**
     * 展开/收起「选择中心点」与「分析参数」两块输入面板。
     *
     * 分析出结果后收起：让侧栏首屏直接是报告，避免每次都要滚过两个输入块。
     * 换中心点清空报告后重新展开：此时收起的前提（有报告要看）已经不成立，
     * 用户正要改输入，折叠着反而是障碍。
     */
    function setInputPanelsOpen(open) {
        ['panel-center', 'panel-params'].forEach((id) => {
            const panel = $(id);
            if (panel) panel.open = open;
        });
    }

    // ------------------------------------------------------------------
    // 口径说明抽屉
    // ------------------------------------------------------------------

    function helpIsOpen() {
        return !$('help-drawer').hidden;
    }

    function openHelp() {
        $('help-backdrop').hidden = false;
        $('help-drawer').hidden = false;
        $('help-drawer').scrollTop = 0;
        // 焦点移入抽屉，键盘用户不必 Tab 穿过整个侧栏才能关掉
        $('help-close').focus();
    }

    function closeHelp() {
        if (!helpIsOpen()) return;
        $('help-drawer').hidden = true;
        $('help-backdrop').hidden = true;
        $('help-btn').focus(); // 焦点还给触发按钮，保持键盘浏览位置
    }

    /** 已经是 BD09 的中心点（示例点位 / 地图点击 / 地理编码） */
    function useBd09Center(lng, lat, note) {
        applyCenter(lng, lat, 'bd09', lng, lat, note);
        MapManager.setCenter(lng, lat);
        $('convert-result').hidden = true;
    }

    function updateCoordText() {
        if (state.bdLng == null) return;
        $('coord-text').textContent = `${state.bdLng.toFixed(6)}, ${state.bdLat.toFixed(6)}`;
        $('coord-source').textContent = state.sourceNote;
    }

    // ------------------------------------------------------------------
    // 面板渲染
    // ------------------------------------------------------------------
    function renderSamples() {
        const sel = $('sample-select');
        sel.innerHTML = '<option value="">— 自定义（点击地图 / 手工输入）—</option>';

        AppConfig.samples.forEach((s, i) => {
            const opt = document.createElement('option');
            opt.value = String(i);
            opt.textContent = `${s.name}（${s.area_type}）`;
            sel.appendChild(opt);
        });

        // 默认选中第一个示例点位
        if (AppConfig.samples.length) sel.value = '0';
    }

    function renderCategories() {
        const box = $('category-list');
        box.innerHTML = '';

        AppConfig.categories.forEach((cat) => {
            const item = document.createElement('span');
            item.className = 'cat-item checked';
            item.dataset.cat = cat;
            item.textContent = cat;
            item.addEventListener('click', () => {
                item.classList.toggle('checked');
                updateCategoryWarn();
            });
            box.appendChild(item);
        });

        updateCategoryWarn();
    }

    /**
     * 关键三类全被取消勾选时给出提示。
     *
     * 取消勾选会让判定类别为空 —— 后端据此**真正跳过**盲区判定（不再像以前那样
     * 把三类塞回来）。后果是两个数字会突然「变好看」：盲区占比 0、健康度换一套
     * 只按所选类别算的口径。不说明的话，用户会把「未判定」误读成「没有盲区」。
     */
    function updateCategoryWarn() {
        const chosen = getSelectedCategories();
        const noneSelected = AppConfig.keyCategories.every(
            (cat) => chosen.indexOf(cat) < 0
        );
        $('categories-warn').hidden = !noneSelected;
    }

    /** 图例中的设施类别配色，与 layers.js 的 categoryColor 同源 */
    function renderLegendCategories() {
        const box = $('legend-categories');
        if (!box) return;
        box.innerHTML = '';

        // 形状 + 颜色双重编码，色觉障碍人群也能区分
        Object.keys(Layers.categoryColor).forEach((cat) => {
            const item = document.createElement('span');
            item.className = 'cat';
            item.innerHTML = `${Layers.legendSvgFor(cat)}${cat}`;
            box.appendChild(item);
        });
    }

    function getSelectedCategories() {
        return Array.from(document.querySelectorAll('.cat-item.checked')).map(
            (el) => el.dataset.cat
        );
    }

    function setCategories(list) {
        document.querySelectorAll('.cat-item').forEach((el) => {
            el.classList.toggle('checked', list.indexOf(el.dataset.cat) >= 0);
        });
        updateCategoryWarn();
    }

    // ------------------------------------------------------------------
    // 地图渲染
    // ------------------------------------------------------------------
    /** 按当前图层设置重绘地图（切换图层时复用已有报告，不再请求后端） */
    function renderMap() {
        const report = state.report;
        if (!report) return;

        const iso = report.isochrone;
        const step = iso.step_m;
        const durationMode = state.layer === 'duration';

        MapManager.clearOverlays();

        if (durationMode) {
            // 全部采样点都着色，才能看出「同一个直线距离，不同方向耗时不同」
            Layers.drawDuration(iso.points, step, iso.threshold_seconds);
        } else {
            // 只在等时圈内着色，红区即盲区
            Layers.drawAccessibility(report.blindspot.points, step);
        }

        // 绘制顺序即叠放顺序（百度按添加顺序摆放同 zIndex 的覆盖物）。
        // 期望层级：热力图 < 盲区点位标注 < 等时圈边界 < 设施点位。
        // 这里曾经把边界画在盲区标注之前，结果边界被盲区框（带 18% 红色填充）
        // 整条糊住、几乎看不出来——顺序反了。
        const judging = (report.blindspot.judge_categories || []).length > 0;
        const marked = judging
            ? Layers.drawBlindMarks(report.blindspot.points, step, state.blindCategory)
            : 0;

        Layers.drawBoundary(report.blindspot.points, step);
        Layers.drawPois(report.pois || []);

        // 图例随图层切换，避免颜色含义被误读
        $('legend-sub').textContent = durationMode
            ? '步行耗时（绿=近，红=远，深红=超出阈值）'
            : '设施可达性（仅等时圈内）';
        $('legend-scale').innerHTML = durationMode
            ? '<span>近（省力）</span><span>远（超时）</span>'
            : '<span>便利</span><span>匮乏（盲区）</span>';

        // 标注网格单元的实际尺寸：否则用户无法把色块换算成真实距离
        let grid = `网格单元：${step} m × ${step} m；采样 ${iso.total_points} 点`;
        if (iso.strategy === 'coarse') {
            const routed = iso.routed_points == null ? iso.total_points : iso.routed_points;
            const saved = iso.total_points
                ? ((1 - routed / iso.total_points) * 100).toFixed(0)
                : '0';
            grid += `；真实算路 ${routed} 点（省 ${saved}%），其余由 IDW 插值补全`;
        }
        $('legend-grid').textContent = grid;

        const target =
            state.blindCategory === '__any__'
                ? '缺失任一判定类别'
                : `缺失「${state.blindCategory}」`;
        const degradedNote = iso.degraded
            ? '<br><span class="warn-text">当前为直线距离估算的降级结果</span>'
            : '';

        // 没有判定类别时整组隐藏，并在说明里点明原因——
        // 否则用户只会看到「已标注 0 个盲区点位」，误以为真的没有盲区
        $('blind-mark-group').hidden = !judging;
        $('layer-note').innerHTML = judging
            ? `已标注 <b>${marked}</b> 个盲区点位（${target}）${degradedNote}`
            : `未选择关键三类，本次<b>不做盲区判定</b>，地图上无盲区标注${degradedNote}`;

        // 控件放在最后显示：它的三块内容（图层 / 标注类别 / 已标注数量）
        // 全部依赖刚画好的热力图，先出控件再出色块会很突兀。
        // 放在 renderMap 末尾也顺带保证了「没有报告时不会露出来」——
        // 函数开头就把 !report 挡住了。
        $('map-controls').hidden = false;
    }

    // ------------------------------------------------------------------
    // 报告渲染
    // ------------------------------------------------------------------
    function renderSummary(report) {
        const iso = report.isochrone;
        const bs = report.blindspot;
        const totalPoi = Object.values(report.poi_counts || {}).reduce(
            (a, b) => a + b,
            0
        );
        const blindRate = bs.total_points
            ? ((bs.blind_points / bs.total_points) * 100).toFixed(1)
            : '0.0';
        // judge_categories 为空 = 用户把关键三类全取消了勾选，后端真的没做判定。
        // 这时 blind_points 恒为 0，直接显示「0%」会被读成「没有盲区」。
        const judging = (bs.judge_categories || []).length > 0;

        // 算路调用量是本项目最核心的配额指标，直接列进概览便于评审核对
        const routed = iso.routed_points == null ? iso.total_points : iso.routed_points;

        // 「盲区占比」往往接近 100%，单独看没有区分度，
        // 因此同时给出按缺失类别数划分的重度/中度/轻度统计
        const lv = bs.blind_levels || {};
        const items = [
            { k: '可达网格点', v: iso.reachable_points },
            { k: '采样/算路网格点', v: `${iso.total_points}/${routed}` },
            { k: '圈内设施', v: totalPoi + ' 个' },
            {
                k: judging ? '盲区占比' : '盲区判定',
                v: judging ? blindRate + '%' : '未判定',
            },
            judging
                ? {
                      k: '重度/中度/轻度',
                      v: `${lv.severe || 0}/${lv.medium || 0}/${lv.light || 0}`,
                  }
                : { k: '盲区类别', v: '未选择' },
            { k: '灰色地带精算', v: (bs.precise_calls || 0) + ' 次' },
        ];

        $('summary-grid').innerHTML = items
            .map(
                (it) =>
                    `<div class="summary-item"><div class="k">${it.k}</div><div class="v">${it.v}</div></div>`
            )
            .join('');
    }

    /** 逐类覆盖 / 盲区率表：把「盲区占比」这个汇总数字拆到类别维度 */
    function renderCategoryTable(report) {
        const box = $('category-table');
        const coverage = report.coverage || {};
        const counts = report.poi_counts || {};
        const judge = (report.blindspot && report.blindspot.judge_categories) || [];
        const cats = Object.keys(coverage);

        if (!cats.length) {
            box.innerHTML = '<div class="chart-empty">暂无数据</div>';
            return;
        }

        const rows = cats
            .map((cat) => {
                const cov = coverage[cat] || 0;
                const blind = 1 - cov;
                const isJudge = judge.indexOf(cat) >= 0;
                return (
                    `<tr class="${isJudge ? 'is-judge' : ''}">` +
                    `<td><span class="cat-name">${Layers.legendSvgFor(cat)}${cat}` +
                    `${isJudge ? ' ★' : ''}</span></td>` +
                    `<td>${(cov * 100).toFixed(1)}%</td>` +
                    `<td>${(blind * 100).toFixed(1)}%</td>` +
                    `<td class="bar-cell"><div class="mini-bar">` +
                    `<span style="width:${(blind * 100).toFixed(0)}%"></span></div></td>` +
                    `<td>${counts[cat] || 0}</td>` +
                    '</tr>'
                );
            })
            .join('');

        box.innerHTML =
            '<table><thead><tr><th>类别</th><th>覆盖率</th><th>盲区率</th>' +
            '<th></th><th>圈内</th></tr></thead><tbody>' +
            rows +
            '</tbody></table>';
    }

    /** 盲区标注类别下拉：可选「综合」或任一判定类别 */
    function renderBlindCategoryOptions(report) {
        const sel = $('blind-category');
        const judge = (report.blindspot && report.blindspot.judge_categories) || [];
        const prev = state.blindCategory;

        sel.innerHTML =
            '<option value="__any__">综合（任一缺失）</option>' +
            judge.map((c) => `<option value="${c}">${c}</option>`).join('');

        state.blindCategory =
            prev === '__any__' || judge.indexOf(prev) >= 0 ? prev : '__any__';
        sel.value = state.blindCategory;
    }

    function renderCacheBadge(report) {
        const iso = report.isochrone;
        const routed = iso.routed_points == null ? iso.total_points : iso.routed_points;
        const coarse = iso.strategy === 'coarse';
        const strategy = coarse ? '分级网格 + IDW 插值' : '单级精细网格';
        // 分级网格是有损近似，必须显著提示，否则用户会把近似边界当成真实路网结论
        const caveat = coarse
            ? '<br><span class="warn-text">⚠️ 分级网格为有损近似：' +
              '剪枝依赖「路网 ≤ 绕行系数 × 直线距离」，路网被水域/围墙切断处会误判' +
              '（松山湖实测面积误差 7.94%、5 个点判定相反）。需要准确边界请切回单级精细网格</span>'
            : '';
        const badge = $('cache-badge');
        badge.hidden = false;

        if (report.cached) {
            badge.className = 'cache-badge' + (coarse ? ' is-warn' : '');
            badge.innerHTML =
                '<b>结果来自缓存</b>，本次未消耗任何地图 API 配额。' +
                `<br>网格策略：${strategy}；采样 ${iso.total_points} 点，` +
                `真实算路 ${routed} 点` +
                caveat;
        } else {
            badge.className =
                'cache-badge ' + (coarse ? 'is-warn' : 'is-live');
            badge.innerHTML =
                '<b>实时计算</b>（缓存未命中，本次已消耗配额）。' +
                `<br>网格策略：${strategy}；采样 ${iso.total_points} 点，` +
                `真实算路 ${routed} 点；灰色地带路网精算 ${report.blindspot.precise_calls || 0} 次` +
                caveat;
        }
    }

    function renderReport(report) {
        $('report-panel').hidden = false;
        $('poi-panel').hidden = false;
        // 收起输入面板 + 侧栏回到顶部：让「报告」直接出现在首屏，
        // 否则用户要先滚过两个输入块才看得到自己刚跑出来的结论
        setInputPanelsOpen(false);
        $('sidebar').scrollTop = 0;

        // 降级结果必须显著提示：批量算路不可用时后端退化为「直线距离估算」，
        // 精度明显低于真实路网。若与正常结果长得一样，用户会把它当成真实路网结论。
        const iso = report.isochrone || {};
        const degradedNote = iso.degraded
            ? `<br><span class="warn-text">⚠️ ${iso.message || '批量算路不可用'}；` +
              `本次等时圈为直线距离估算（${iso.step_m} m 网格、覆盖半径 ${iso.radius_m} m），` +
              `精度低于真实路网，仅供参考</span>`
            : '';

        // 有类别检索失败时必须显著提示：其覆盖率不可信，
        // 否则用户会把「请求失败」当成「这里真的没有此类设施」
        const failed = (report.blindspot && report.blindspot.failed_categories) || [];
        const failedNote = failed.length
            ? `<br><span class="warn-text">⚠️ ${failed.join('、')} 检索失败（可能触及限流），` +
              `这部分覆盖率不可信，请稍后重试</span>`
            : '';

        $('report-address').innerHTML =
            (report.address || '') + degradedNote + failedNote;

        // 健康度评分
        $('health-score').textContent = report.health_score.toFixed(1);
        $('health-bar').style.width = Math.min(report.health_score, 100) + '%';

        renderCacheBadge(report);
        renderSummary(report);

        // 明确说明盲区依据哪些类别判定，避免用户误以为「盲区率 100% = 什么都没有」。
        // 未判定时的说明比正常情况更要紧：此时盲区数为 0，不讲清楚就会被读成「没有盲区」。
        const judge = (report.blindspot && report.blindspot.judge_categories) || [];
        const note = $('blindspot-note');
        if (judge.length) {
            note.className = 'coverage-note';
            note.textContent =
                `盲区判定基于：${judge.join('、')}` +
                '（缺失任一即记为盲区；其余类别仅统计覆盖率，见下方逐类盲区率）';
        } else {
            note.className = 'coverage-note is-warn';
            note.textContent =
                '未选择关键三类（菜市场 / 药店 / 小学）：本次不做盲区判定，' +
                '下方仅有覆盖率统计，健康度也只按所选类别计算';
        }

        Charts.renderCoverage(report.coverage, report.poi_counts);
        Charts.renderRadar(report.score_detail);
        renderCategoryTable(report);
        renderBlindCategoryOptions(report);
    }

    // ------------------------------------------------------------------
    // 中心点输入：手工坐标转换
    // ------------------------------------------------------------------
    async function convertAndLocate() {
        const raw = $('manual-coord').value.trim();
        if (!raw) {
            window.alert('请输入坐标，格式：经度, 纬度（如 113.881641, 22.909011）');
            return;
        }

        const matched = raw.match(/^(-?\d+(?:\.\d+)?)\s*[,，\s]\s*(-?\d+(?:\.\d+)?)$/);
        if (!matched) {
            window.alert('坐标格式无法识别，请用「经度, 纬度」，例如 113.881641, 22.909011');
            return;
        }

        const lng = Number(matched[1]);
        const lat = Number(matched[2]);
        if (Math.abs(lng) > 180 || Math.abs(lat) > 90) {
            window.alert('经纬度超出取值范围（经度 ±180，纬度 ±90）');
            return;
        }

        const type = $('coord-type').value;
        $('sample-select').value = '';
        $('convert-result').hidden = true;

        if (type === 'bd09') {
            useBd09Center(lng, lat, '手工输入：BD09（本就是基准坐标系，未做转换）');
            return;
        }

        // 非 BD09：交给后端转换。地图按转换后的 BD09 渲染，
        // 分析请求仍把「原始坐标 + 声明的坐标系」透传，由后端用同一套逻辑转换。
        try {
            const res = await Api.convert([{ lng, lat }], type);
            const point = (res.points || [])[0];
            if (!point) throw new Error('转换接口未返回结果');

            applyCenter(
                lng,
                lat,
                type,
                point.lng,
                point.lat,
                `手工输入：${type.toUpperCase()}（分析时由后端转换为 BD09）`
            );
            MapManager.setCenter(point.lng, point.lat);

            const gap = distanceMeters(lng, lat, point.lng, point.lat);
            const methodLabel =
                {
                    api: '百度坐标转换接口（/geoconv/v1）',
                    local: '本地算法兜底',
                    none: '无需转换',
                }[res.method] || res.method;

            const box = $('convert-result');
            box.hidden = false;
            box.innerHTML =
                `输入 <b>${type.toUpperCase()}</b> (${lng.toFixed(6)}, ${lat.toFixed(6)})` +
                `<br>↓ ${methodLabel}<br>` +
                `<b>BD09</b> (${point.lng.toFixed(6)}, ${point.lat.toFixed(6)})` +
                `<br>两者相距约 <b>${gap.toFixed(1)} m</b>` +
                (res.message
                    ? `<br><span class="warn-text">${escapeHtml(res.message)}</span>`
                    : '');
        } catch (err) {
            alertError('坐标转换失败：' + err.message);
        }
    }

    // ------------------------------------------------------------------
    // 原始 POI 检索（/api/get_poi）
    // ------------------------------------------------------------------
    function renderPoiResult(res) {
        const counts = res.category_counts || {};
        const chips = Object.keys(counts)
            .map((cat) => `<span class="chip">${cat} <b>${counts[cat]}</b></span>`)
            .join('');

        const list = res.poi_list || [];
        const shown = list.slice(0, 100);
        const rows = shown
            .map((p) => {
                const color = Layers.categoryColor[p.category] || '#6b7280';
                return (
                    '<div class="poi-row">' +
                    `<span class="dot" style="background:${color}"></span>` +
                    `<span class="poi-name">${escapeHtml(p.name)}</span>` +
                    `<span class="poi-dist">${p.category || '—'} · ` +
                    `${p.distance_m != null ? Math.round(p.distance_m) + ' m' : '—'}</span>` +
                    '</div>'
                );
            })
            .join('');

        $('poi-result').innerHTML =
            `<div class="poi-counts">${chips}</div>` +
            `<div class="hint">半径 ${res.radius} m 内共 ${res.total} 个，` +
            `下方按距离列出前 ${shown.length} 个</div>` +
            `<div class="poi-list">${rows || '<div class="poi-row">无结果</div>'}</div>`;
    }

    async function runPoiSearch() {
        if (state.inputLng == null) {
            window.alert('请先选择一个中心点');
            return;
        }

        const btn = $('poi-btn');
        btn.disabled = true;
        $('poi-result').innerHTML =
            '<div class="hint">检索中…（按类别分别请求，消耗地点检索配额）</div>';

        try {
            const res = await Api.getPoi(
                state.inputLng,
                state.inputLat,
                Number($('poi-radius').value),
                getSelectedCategories(),
                state.coordType
            );
            renderPoiResult(res);
        } catch (err) {
            $('poi-result').innerHTML =
                `<div class="warn-text">检索失败：${escapeHtml(err.message)}</div>`;
        } finally {
            btn.disabled = false;
        }
    }

    // ------------------------------------------------------------------
    // 分析流程
    // ------------------------------------------------------------------
    async function analyze() {
        if (state.inputLng == null) {
            window.alert('请先选择一个中心点（点击地图、选示例点位或手工输入坐标）');
            return;
        }

        const categories = getSelectedCategories();
        if (!categories.length) {
            window.alert('请至少选择一个设施类别');
            return;
        }

        state.analyzing = true;
        const btn = $('analyze-btn');
        btn.disabled = true;
        showLoading('正在计算等时圈与设施覆盖');

        try {
            const report = await Api.getReport(
                state.inputLng,
                state.inputLat,
                Number($('walk-minutes').value),
                categories,
                Number($('grid-step').value),
                state.coordType,
                $('grid-strategy').value === 'coarse'
            );

            state.report = report;
            renderReport(report);
            renderMap();
            hideLoading();
        } catch (err) {
            alertError('分析失败：' + err.message);
        } finally {
            state.analyzing = false;
            btn.disabled = false;
        }
    }

    // ------------------------------------------------------------------
    // 事件绑定
    // ------------------------------------------------------------------
    function bindEvents() {
        // 示例点位切换
        $('sample-select').addEventListener('change', (e) => {
            const idx = e.target.value;
            if (idx === '') return;
            const s = AppConfig.samples[Number(idx)];
            useBd09Center(s.lng, s.lat, `示例点位：${s.name}（${s.area_type}）`);
        });

        // 地点搜索
        $('geocode-btn').addEventListener('click', async () => {
            const address = $('address-input').value.trim();
            if (!address) return;
            try {
                const geo = await Api.geocode(address);
                $('sample-select').value = '';
                useBd09Center(geo.lng, geo.lat, `地理编码：${geo.address || address}`);
            } catch (err) {
                alertError('定位失败：' + err.message);
            }
        });

        // 手工输入坐标：声明坐标系后转换并定位
        $('coord-btn').addEventListener('click', convertAndLocate);
        $('manual-coord').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') convertAndLocate();
        });

        // 步行时间滑块
        $('walk-minutes').addEventListener('input', (e) => {
            $('walk-minutes-value').textContent = e.target.value;
        });

        // 网格策略：解释统一收进「口径说明」抽屉了，不再常驻侧栏。
        // 但「分级网格是有损近似」这个前提必须当场可见，否则用户切过去就漏看了——
        // 所以给这个选项单独留一行警示，只在选中时出现，默认不占位置。
        $('grid-strategy').addEventListener('change', (e) => {
            $('strategy-warn').hidden = e.target.value !== 'coarse';
        });

        // 类别快捷选择
        $('cat-all').addEventListener('click', () => setCategories(AppConfig.categories));
        $('cat-key').addEventListener('click', () => setCategories(AppConfig.keyCategories));

        // 图层切换：复用已有报告，不重新请求
        document.querySelectorAll('.mc-btn').forEach((btn) => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.mc-btn').forEach((b) => {
                    b.classList.toggle('is-active', b === btn);
                });
                state.layer = btn.dataset.layer;
                renderMap();
            });
        });

        // 盲区标注类别切换
        $('blind-category').addEventListener('change', (e) => {
            state.blindCategory = e.target.value;
            renderMap();
        });

        // 原始 POI 检索
        $('poi-btn').addEventListener('click', runPoiSearch);

        // 口径说明抽屉：按钮 / 关闭 / 点遮罩 / Esc 四条关闭路径都要有，
        // 只给一个「关闭」按钮会让习惯点空白处或按 Esc 的用户被困住
        $('help-btn').addEventListener('click', openHelp);
        $('help-close').addEventListener('click', closeHelp);
        $('help-backdrop').addEventListener('click', closeHelp);
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') closeHelp();
        });

        // 开始分析
        $('analyze-btn').addEventListener('click', analyze);
    }

    // ------------------------------------------------------------------
    // 启动
    // ------------------------------------------------------------------
    async function boot() {
        try {
            await AppConfig.load();
            setStatus(
                AppConfig.backendReady ? '后端已就绪' : '后端缺 AK 配置',
                AppConfig.backendReady ? 'badge-ok' : 'badge-warn'
            );
        } catch (err) {
            setStatus('后端未连接', 'badge-error');
            alertError(err.message);
            return;
        }

        renderSamples();
        renderCategories();
        renderLegendCategories();

        const center = AppConfig.defaultCenter;

        try {
            await MapManager.loadScript(AppConfig.baiduAk);
            MapManager.init(center);
        } catch (err) {
            alertError(err.message);
            return;
        }

        const first = AppConfig.samples[0];
        useBd09Center(
            center.lng,
            center.lat,
            first ? `默认示例点位：${first.name}` : '默认中心点'
        );

        MapManager.onSelect = (lng, lat) => {
            $('sample-select').value = '';
            applyCenter(lng, lat, 'bd09', lng, lat, '地图点击选点');
        };

        bindEvents();
    }

    document.addEventListener('DOMContentLoaded', boot);
})();
