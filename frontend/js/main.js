/**
 * 应用入口：串联配置加载、地图初始化、分析流程与结果渲染。
 *
 * 整体流程：
 *   拉取后端配置(AK/示例点位/类别) → 加载百度地图 → 用户选点
 *   → 调用 /api/report → 绘制等时圈与盲区 → 渲染评分与图表
 */
(function () {
    const state = {
        lng: null,
        lat: null,
        analyzing: false,
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

    function updateCoordText() {
        if (state.lng == null) return;
        $('coord-text').textContent = `${state.lng.toFixed(6)}, ${state.lat.toFixed(6)}`;
    }

    // ------------------------------------------------------------------
    // 面板渲染
    // ------------------------------------------------------------------
    function renderSamples() {
        const sel = $('sample-select');
        sel.innerHTML = '<option value="">— 自定义（点击地图）—</option>';

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
            });
            box.appendChild(item);
        });
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

        // 「盲区占比」往往接近 100%，单独看没有区分度，
        // 因此同时给出按缺失类别数划分的重度/中度/轻度统计
        const lv = bs.blind_levels || {};
        const items = [
            { k: '可达网格点', v: iso.reachable_points },
            { k: '圈内设施', v: totalPoi + ' 个' },
            { k: '盲区占比', v: blindRate + '%' },
            {
                k: '重度/中度/轻度',
                v: `${lv.severe || 0}/${lv.medium || 0}/${lv.light || 0}`,
            },
        ];

        $('summary-grid').innerHTML = items
            .map(
                (it) =>
                    `<div class="summary-item"><div class="k">${it.k}</div><div class="v">${it.v}</div></div>`
            )
            .join('');
    }

    function renderReport(report) {
        $('report-panel').hidden = false;

        // 有类别检索失败时必须显著提示：其覆盖率不可信，
        // 否则用户会把「请求失败」当成「这里真的没有此类设施」
        const failed = (report.blindspot && report.blindspot.failed_categories) || [];
        $('report-address').innerHTML =
            (report.address || '') +
            (failed.length
                ? `<br><span class="warn-text">⚠️ ${failed.join('、')} 检索失败（可能触及限流），` +
                  `这部分覆盖率不可信，请稍后重试</span>`
                : '');

        // 标注网格单元的实际尺寸：否则用户无法把色块换算成真实距离
        const gridStep = report.isochrone.step_m;
        $('legend-grid').textContent = `网格单元：${gridStep} m × ${gridStep} m`;

        // 健康度评分
        $('health-score').textContent = report.health_score.toFixed(1);
        $('health-bar').style.width = Math.min(report.health_score, 100) + '%';

        renderSummary(report);

        // 明确说明盲区依据哪些类别判定，避免用户误以为「盲区率 100% = 什么都没有」
        const judge = (report.blindspot && report.blindspot.judge_categories) || [];
        $('blindspot-note').textContent = judge.length
            ? `盲区判定基于：${judge.join('、')}（缺失任一即记为盲区；其余类别仅统计覆盖率）`
            : '';

        Charts.renderCoverage(report.coverage, report.poi_counts);
        Charts.renderRadar(report.score_detail);
    }

    // ------------------------------------------------------------------
    // 分析流程
    // ------------------------------------------------------------------
    async function analyze() {
        if (state.lng == null) {
            window.alert('请先选择一个中心点（点击地图或选择示例点位）');
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
                state.lng,
                state.lat,
                Number($('walk-minutes').value),
                categories,
                Number($('grid-step').value)
            );

            // 绘制地图图层：可达性热力图（底）→ 设施点位（上）
            // 红区即服务盲区，因此不再需要额外的盲区标记图层
            MapManager.clearOverlays();
            Layers.drawAccessibility(
                report.blindspot.points,
                report.isochrone.step_m
            );
            Layers.drawBoundary(
                report.blindspot.points,
                report.isochrone.step_m
            );
            Layers.drawPois(report.pois || []);

            renderReport(report);
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
            state.lng = s.lng;
            state.lat = s.lat;
            MapManager.setCenter(s.lng, s.lat);
            updateCoordText();
        });

        // 地点搜索
        $('geocode-btn').addEventListener('click', async () => {
            const address = $('address-input').value.trim();
            if (!address) return;
            try {
                const geo = await Api.geocode(address);
                state.lng = geo.lng;
                state.lat = geo.lat;
                MapManager.setCenter(geo.lng, geo.lat);
                updateCoordText();
            } catch (err) {
                alertError('定位失败：' + err.message);
            }
        });

        // 步行时间滑块
        $('walk-minutes').addEventListener('input', (e) => {
            $('walk-minutes-value').textContent = e.target.value;
        });

        // 类别快捷选择
        $('cat-all').addEventListener('click', () => setCategories(AppConfig.categories));
        $('cat-key').addEventListener('click', () => setCategories(AppConfig.keyCategories));

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
        state.lng = center.lng;
        state.lat = center.lat;

        try {
            await MapManager.loadScript(AppConfig.baiduAk);
            MapManager.init(center);
            MapManager.setCenter(center.lng, center.lat);
        } catch (err) {
            alertError(err.message);
            return;
        }

        MapManager.onSelect = (lng, lat) => {
            state.lng = lng;
            state.lat = lat;
            $('sample-select').value = '';
            updateCoordText();
        };

        bindEvents();
        updateCoordText();
    }

    document.addEventListener('DOMContentLoaded', boot);
})();
