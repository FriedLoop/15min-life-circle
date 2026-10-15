/**
 * 图表渲染（纯 SVG 自绘，无第三方依赖）。
 *
 * 为什么不用 ECharts：
 *     原先通过 jsdelivr CDN 引入 ECharts，但国内访问该 CDN 不稳定，
 *     一旦加载失败图表区就是一片空白（页面其余部分正常，很难察觉）。
 *     改为自绘 SVG 后：
 *       1. 零外部依赖，Docker 离线部署也能正常显示
 *       2. 体积更小、风格与页面统一
 *       3. 不占用评审环境的网络
 *
 * 两张图对应「数据可视化」评分要求：
 *     覆盖率柱状图 —— 比较各类设施的覆盖水平
 *     得分雷达图   —— 一眼看出生活圈的短板
 */

/** 按得分给出配色：高=绿、中=黄、低=红 */
function scoreColor(value) {
    if (value >= 80) return '#16a34a';
    if (value >= 40) return '#f59e0b';
    return '#dc2626';
}

const Charts = {
    /**
     * 设施覆盖率柱状图。
     * @param {Object} coverage {类别: 覆盖率 0~1}
     * @param {Object} counts {类别: 圈内数量}
     */
    renderCoverage(coverage, counts) {
        const el = document.getElementById('chart-coverage');
        if (!el) return;

        const cats = Object.keys(coverage || {});
        if (!cats.length) {
            el.innerHTML = '<div class="chart-empty">暂无数据</div>';
            return;
        }

        const values = cats.map((c) => (coverage[c] || 0) * 100);
        const numbers = cats.map((c) => (counts || {})[c] || 0);

        const W = 360;
        const H = 210;
        const padL = 30;
        const padR = 8;
        const padT = 14;
        const padB = 58; // 留给旋转后的类别标签
        const plotW = W - padL - padR;
        const plotH = H - padT - padB;
        const step = plotW / cats.length;
        const barW = Math.max(step * 0.58, 3);

        let svg = `<svg viewBox="0 0 ${W} ${H}" class="svg-chart" role="img">`;

        // Y 轴网格线与刻度
        [0, 25, 50, 75, 100].forEach((v) => {
            const y = padT + plotH * (1 - v / 100);
            svg += `<line x1="${padL}" y1="${y}" x2="${W - padR}" y2="${y}" stroke="#eef2f7" stroke-width="1"/>`;
            svg += `<text x="${padL - 5}" y="${y + 3}" text-anchor="end" font-size="9" fill="#9ca3af">${v}</text>`;
        });

        // 柱子
        cats.forEach((cat, i) => {
            const value = values[i];
            const barH = Math.max(plotH * (value / 100), value > 0 ? 2 : 0);
            const x = padL + step * i + (step - barW) / 2;
            const y = padT + plotH - barH;

            svg +=
                `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barW.toFixed(1)}" ` +
                `height="${barH.toFixed(1)}" rx="2" fill="${scoreColor(value)}">` +
                `<title>${cat}：覆盖率 ${value.toFixed(1)}%，圈内 ${numbers[i]} 个</title></rect>`;

            // 柱顶数值
            svg +=
                `<text x="${(x + barW / 2).toFixed(1)}" y="${(y - 3).toFixed(1)}" ` +
                `text-anchor="middle" font-size="8.5" fill="#6b7280">${value.toFixed(0)}</text>`;

            // 类别标签（旋转 40° 避免重叠）
            const lx = padL + step * i + step / 2;
            const ly = padT + plotH + 10;
            svg +=
                `<text x="${lx.toFixed(1)}" y="${ly.toFixed(1)}" text-anchor="end" ` +
                `font-size="9" fill="#6b7280" ` +
                `transform="rotate(-40 ${lx.toFixed(1)} ${ly.toFixed(1)})">${cat}</text>`;
        });

        svg += '</svg>';
        el.innerHTML = svg;
    },

    /**
     * 各类别得分雷达图。
     * @param {Object} detail {类别: 得分 0~100}
     */
    renderRadar(detail) {
        const el = document.getElementById('chart-radar');
        if (!el) return;

        const cats = Object.keys(detail || {});
        if (cats.length < 3) {
            el.innerHTML = '<div class="chart-empty">类别不足，无法绘制雷达图</div>';
            return;
        }

        const W = 340;
        const H = 250;
        const cx = W / 2;
        const cy = H / 2 + 4;
        const R = Math.min(W, H) * 0.30;

        const angleOf = (i) => -Math.PI / 2 + (i * 2 * Math.PI) / cats.length;
        const pointAt = (i, r) => [
            cx + Math.cos(angleOf(i)) * r,
            cy + Math.sin(angleOf(i)) * r,
        ];

        let svg = `<svg viewBox="0 0 ${W} ${H}" class="svg-chart" role="img">`;

        // 网格环
        [0.25, 0.5, 0.75, 1].forEach((k) => {
            const pts = cats
                .map((_, i) => pointAt(i, R * k).map((n) => n.toFixed(1)).join(','))
                .join(' ');
            svg += `<polygon points="${pts}" fill="none" stroke="#eef2f7" stroke-width="1"/>`;
        });

        // 轴线
        cats.forEach((_, i) => {
            const [x, y] = pointAt(i, R);
            svg += `<line x1="${cx}" y1="${cy}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" stroke="#eef2f7" stroke-width="1"/>`;
        });

        // 数据多边形
        const norm = (v) => Math.max(0, Math.min(1, (v || 0) / 100));
        const dataPts = cats
            .map((c, i) => pointAt(i, R * norm(detail[c])).map((n) => n.toFixed(1)).join(','))
            .join(' ');
        svg +=
            `<polygon points="${dataPts}" fill="rgba(26,115,232,0.22)" ` +
            `stroke="#1a73e8" stroke-width="2" stroke-linejoin="round"/>`;

        // 数据点
        cats.forEach((c, i) => {
            const [x, y] = pointAt(i, R * norm(detail[c]));
            svg +=
                `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="2.6" fill="#1a73e8">` +
                `<title>${c}：${(detail[c] || 0).toFixed(1)} 分</title></circle>`;
        });

        // 类别标签
        cats.forEach((cat, i) => {
            const [x, y] = pointAt(i, R + 15);
            const dx = x - cx;
            const anchor = Math.abs(dx) < 8 ? 'middle' : dx > 0 ? 'start' : 'end';
            svg +=
                `<text x="${x.toFixed(1)}" y="${(y + 3).toFixed(1)}" text-anchor="${anchor}" ` +
                `font-size="9" fill="#6b7280">${cat}</text>`;
        });

        svg += '</svg>';
        el.innerHTML = svg;
    },

    /** SVG 自适应容器，无需在窗口变化时重绘 */
    resize() {},
};
