/**
 * 图层绘制。
 *
 * 提供两种可切换的热力图，不是替代关系而是互补：
 *
 *     1. 设施可达性（drawAccessibility，默认）
 *        着色依据是该点的**综合设施可达性**，颜色含义：绿 = 周边设施便利，
 *        红 = 配套匮乏（即服务盲区）。只在等时圈范围内着色，
 *        因此一张图同时表达了「等时圈范围」与「盲区分布」，红区即盲区。
 *
 *     2. 步行耗时（drawDuration）
 *        着色依据是该点的**真实步行耗时**。它不回答「有没有东西用」，
 *        而是回答「这段路走起来多费劲」——同一个直线距离上，
 *        路网稀疏方向的耗时明显更长，这正是「等时圈不是圆」的直接证据。
 *        全部采样点（含圈外）都着色，圈内外的分界由等时圈边界线给出。
 *
 * 盲区点位另由 drawBlindMarks 用加粗红框标注，可按单个判定类别筛选。
 *
 * 设施点位采用**形状 + 颜色**双重编码：
 *     仅用颜色区分对色觉障碍人群不友好，因此每个类别额外赋予一种形状，
 *     即使完全无法辨色，也能靠轮廓区分设施类型。
 */

/** 按米级偏移计算新坐标 */
function offsetMeters(lng, lat, eastM, northM) {
    const dLat = northM / 111320;
    const dLng = eastM / (111320 * Math.cos((lat * Math.PI) / 180));
    return [lng + dLng, lat + dLat];
}

/** 两点间球面直线距离（米），用于展示「用错坐标系造成的偏移量」 */
function distanceMeters(lng1, lat1, lng2, lat2) {
    const R = 6371008.8;
    const rad = Math.PI / 180;
    const dLat = (lat2 - lat1) * rad;
    const dLng = (lng2 - lng1) * rad;
    const a =
        Math.sin(dLat / 2) ** 2 +
        Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLng / 2) ** 2;
    return 2 * R * Math.asin(Math.min(1, Math.sqrt(a)));
}

/** 以某点为中心、边长为 2*half 米的方格顶点（西北 → 东北 → 东南 → 西南） */
function squareAround(lng, lat, half) {
    return [
        offsetMeters(lng, lat, -half, +half),
        offsetMeters(lng, lat, +half, +half),
        offsetMeters(lng, lat, +half, -half),
        offsetMeters(lng, lat, -half, -half),
    ];
}

/** 各类别的 SVG 形状路径（24×24 视口） */
const SHAPE_PATHS = {
    circle: '<circle cx="12" cy="12" r="8"/>',
    square: '<rect x="5" y="5" width="14" height="14" rx="1"/>',
    triangle: '<polygon points="12,3 21,20 3,20"/>',
    triangleDown: '<polygon points="3,3 21,3 12,20"/>',
    diamond: '<polygon points="12,3 21,12 12,21 3,12"/>',
    cross: '<path d="M9.5,3 h5 v6.5 h6.5 v5 h-6.5 v6.5 h-5 v-6.5 h-3.5 v-5 h3.5 z"/>',
    star: '<polygon points="12,2.5 14.8,9.2 22,9.6 16.4,14.2 18.3,21 12,17.2 5.7,21 7.6,14.2 2,9.6 9.2,9.2"/>',
    hexagon: '<polygon points="12,3 20,7.5 20,16.5 12,21 4,16.5 4,7.5"/>',
    pentagon: '<polygon points="12,3 21,10 17.5,20 6.5,20 3,10"/>',
    rectV: '<rect x="7" y="3" width="10" height="18" rx="1"/>',
};

const Layers = {
    /** 可达性渐变色带：绿(便利) → 红(匮乏) */
    _ramp: [
        [0.0, [34, 197, 94]],
        [0.3, [132, 204, 22]],
        [0.5, [250, 204, 21]],
        [0.7, [249, 115, 22]],
        [1.0, [239, 68, 68]],
    ],

    /** 各类设施配色 */
    categoryColor: {
        菜市场: '#16a34a',
        药店: '#dc2626',
        小学: '#2563eb',
        幼儿园: '#7c3aed',
        医疗: '#0891b2',
        购物: '#ea580c',
        公园: '#4d7c0f',
        银行: '#ca8a04',
        养老: '#db2777',
        餐饮: '#0d9488',
    },

    /** 各类设施形状：与颜色配合，构成双重编码 */
    categoryShape: {
        菜市场: 'circle',
        药店: 'cross',
        小学: 'triangle',
        幼儿园: 'diamond',
        医疗: 'square',
        购物: 'star',
        公园: 'hexagon',
        银行: 'rectV',
        养老: 'pentagon',
        餐饮: 'triangleDown',
    },

    /** 生成某类别的图标（形状 + 颜色） */
    iconFor(category) {
        const color = this.categoryColor[category] || '#6b7280';
        const shape = this.categoryShape[category] || 'circle';
        const svg =
            '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">' +
            `<g fill="${color}" stroke="#ffffff" stroke-width="1.5" ` +
            `stroke-linejoin="round">${SHAPE_PATHS[shape]}</g>` +
            '</svg>';

        return new BMap.Icon(
            'data:image/svg+xml;utf8,' + encodeURIComponent(svg),
            new BMap.Size(24, 24)
        );
    },

    /** 生成图例用的小图标（纯 SVG 字符串，不依赖地图） */
    legendSvgFor(category) {
        const color = this.categoryColor[category] || '#6b7280';
        const shape = this.categoryShape[category] || 'circle';
        return (
            '<svg class="shape-icon" xmlns="http://www.w3.org/2000/svg" ' +
            'width="14" height="14" viewBox="0 0 24 24">' +
            `<g fill="${color}">${SHAPE_PATHS[shape]}</g></svg>`
        );
    },

    /**
     * 按 0~1 比例在色带上插值取色。
     * @param {number} ratio 0=可达性最好(绿)，1=可达性最差(红)
     */
    colorFor(ratio) {
        const r = Math.max(0, Math.min(1, ratio));
        const ramp = this._ramp;

        for (let i = 0; i < ramp.length - 1; i += 1) {
            const [t0, c0] = ramp[i];
            const [t1, c1] = ramp[i + 1];
            if (r >= t0 && r <= t1) {
                const k = (r - t0) / (t1 - t0 || 1);
                const mixed = c0.map((v, j) => Math.round(v + (c1[j] - v) * k));
                return `rgb(${mixed[0]}, ${mixed[1]}, ${mixed[2]})`;
            }
        }

        const last = ramp[ramp.length - 1][1];
        return `rgb(${last[0]}, ${last[1]}, ${last[2]})`;
    },

    /**
     * 绘制等时圈可达性热力图。
     *
     * 仅在等时圈（可达）范围内着色，因此图形外轮廓即为真实等时圈边界，
     * 凹陷与缺口完整保留；颜色表达该点的设施可达性。
     *
     * @param {Array} points 盲区点集（每项含 accessibility 0~1）
     * @param {number} stepM 网格间隔（米），即方块边长
     */
    drawAccessibility(points, stepM) {
        // 可达性得分的实际分布通常落在 0.25~0.80，
        // 若直接把它当作色带比例，整张图会挤在中段、一片黄而分不出差异，
        // 因此把这个区间线性拉伸到完整色域以增强对比
        const SCORE_LO = 0.25;
        const SCORE_HI = 0.8;

        this._fillSquares(points, stepM, (p) => {
            const score = typeof p.accessibility === 'number' ? p.accessibility : 0;
            const normalized = (score - SCORE_LO) / (SCORE_HI - SCORE_LO);
            return this.colorFor(1 - Math.max(0, Math.min(1, normalized)));
        });
    },

    /**
     * 绘制「步行耗时」热力图：颜色表达该点到中心点的真实步行耗时。
     *
     * 与可达性图的分工：
     *     可达性图回答「到了之后有没有配套用」，
     *     耗时图回答「路网让这段距离走起来到底多费劲」——
     *     后者才能证明等时圈不是圆：同一个直线距离上，
     *     路网稀疏的方向耗时会明显更长（颜色更深）。
     *
     * 着色范围是**全部采样点**（含圈外），因此图形外轮廓即采样范围，
     * 圈内外的分界由等时圈边界线给出，两者叠加即可读出「走到哪超时」。
     *
     * @param {Array} points 等时圈采样点（每项含 duration / reachable）
     * @param {number} stepM 网格间隔（米）
     * @param {number} thresholdSeconds 可达阈值（秒），用于把耗时归一化到 0~1
     */
    drawDuration(points, stepM, thresholdSeconds) {
        const T = thresholdSeconds || 900;

        this._fillSquares(
            points,
            stepM,
            (p) => {
                if (typeof p.duration !== 'number') return '#9ca3af'; // 算路失败
                if (!p.reachable) return '#7f1d1d';                   // 超出阈值：深红
                // 圈内：0 → 绿，接近阈值 → 红
                return this.colorFor(Math.max(0, Math.min(1, p.duration / T)));
            },
            0.62
        );
    },

    /**
     * 用统一的方格填充实现两种热力图。
     * @param {Array} points
     * @param {number} stepM
     * @param {(p:Object)=>string} colorOf 由点计算填充色
     * @param {number} [opacity]
     */
    _fillSquares(points, stepM, colorOf, opacity) {
        // 略微放大，消除浮点误差造成的细缝
        const half = (stepM / 2) * 1.03;
        const fillOpacity = opacity == null ? 0.72 : opacity;

        points.forEach((p) => {
            const polygon = new BMap.Polygon(
                squareAround(p.lng, p.lat, half).map((c) => new BMap.Point(c[0], c[1])),
                { strokeWeight: 0, fillColor: colorOf(p), fillOpacity }
            );
            MapManager.map.addOverlay(polygon);
        });
    },

    /**
     * 标注盲区点位。
     *
     * @param {Array} points 可达点集（每项含 blind / missing_categories）
     * @param {number} stepM 网格间隔（米）
     * @param {string} selected '__any__' 表示「缺失任一判定类别」；
     *                          否则为该类别名，只标注缺失该类的点
     * @returns {number} 被标注的点数
     */
    drawBlindMarks(points, stepM, selected) {
        const half = (stepM / 2) * 1.04;
        const any = !selected || selected === '__any__';

        const targets = points.filter((p) =>
            any ? !!p.blind : (p.missing_categories || []).indexOf(selected) >= 0
        );

        targets.forEach((p) => {
            const polygon = new BMap.Polygon(
                squareAround(p.lng, p.lat, half).map((c) => new BMap.Point(c[0], c[1])),
                {
                    strokeColor: '#b91c1c',
                    strokeWeight: 2,
                    strokeOpacity: 0.85,
                    fillColor: '#dc2626',
                    fillOpacity: 0.18,
                }
            );
            MapManager.map.addOverlay(polygon);
        });

        return targets.length;
    },

    /**
     * 绘制等时圈外轮廓。
     *
     * 色块能表达可达性，但边界不够锐利，看不出「圈到哪儿为止」。
     * 这里遍历每个可达格子，凡是某个方向没有相邻可达格子，就描出那条边——
     * 拼起来即为完整外轮廓，且**保留凹陷与缺口**（凸包做不到这一点）。
     *
     * @param {Array} points 盲区/可达点集
     * @param {number} stepM 网格间隔（米）
     */
    drawBoundary(points, stepM) {
        // 兼容两种入参：等时圈全量采样点（含 unreachable）与盲区点集。
        // 盲区点集（BlindSpotPoint）本身只包含可达点、没有 reachable 字段，
        // 若按 p.reachable 过滤会把整份数据判成空、边界永远画不出来。
        const reachable = points.filter((p) => p.reachable !== false);
        if (!reachable.length) return;

        // 量化精度约 11m：既能容忍浮点误差，又远小于网格间隔，不会误判邻接
        const PRECISION = 1e4;
        const keyOf = (lng, lat) =>
            `${Math.round(lng * PRECISION)}|${Math.round(lat * PRECISION)}`;

        const grid = new Set(reachable.map((p) => keyOf(p.lng, p.lat)));
        const hasNeighbor = (lng, lat, dEast, dNorth) => {
            const [nLng, nLat] = offsetMeters(lng, lat, dEast, dNorth);
            return grid.has(keyOf(nLng, nLat));
        };

        const half = (stepM / 2) * 1.02;

        reachable.forEach((p) => {
            const nw = offsetMeters(p.lng, p.lat, -half, +half);
            const ne = offsetMeters(p.lng, p.lat, +half, +half);
            const se = offsetMeters(p.lng, p.lat, +half, -half);
            const sw = offsetMeters(p.lng, p.lat, -half, -half);

            if (!hasNeighbor(p.lng, p.lat, 0, stepM)) this._addLine(nw, ne);      // 北
            if (!hasNeighbor(p.lng, p.lat, stepM, 0)) this._addLine(ne, se);      // 东
            if (!hasNeighbor(p.lng, p.lat, 0, -stepM)) this._addLine(se, sw);     // 南
            if (!hasNeighbor(p.lng, p.lat, -stepM, 0)) this._addLine(sw, nw);     // 西
        });
    },

    /** 画一段轮廓线 */
    _addLine(a, b) {
        const line = new BMap.Polyline(
            [new BMap.Point(a[0], a[1]), new BMap.Point(b[0], b[1])],
            { strokeColor: '#111827', strokeWeight: 2, strokeOpacity: 0.7 }
        );
        MapManager.map.addOverlay(line);
    },

    /**
     * 标注设施点位：形状 + 颜色双重编码，点击查看详情。
     * @param {Array} pois POI 列表
     */
    drawPois(pois) {
        pois.forEach((poi) => {
            const point = new BMap.Point(poi.lng, poi.lat);
            const color = this.categoryColor[poi.category] || '#6b7280';

            const marker = new BMap.Marker(point, { icon: this.iconFor(poi.category) });

            marker.addEventListener('click', () => {
                const info = new BMap.InfoWindow(
                    `<div style="font-size:13px;line-height:1.6">
                        <b>${poi.name}</b><br/>
                        类别：<span style="color:${color}">${poi.category}</span><br/>
                        地址：${poi.address || '—'}<br/>
                        距中心：${poi.distance_m != null ? Math.round(poi.distance_m) + ' m' : '—'}
                     </div>`
                );
                MapManager.map.openInfoWindow(info, point);
            });

            MapManager.map.addOverlay(marker);
        });
    },
};
