/**
 * 图层绘制。
 *
 * 热力图的语义（重要）：
 *     着色依据是该点的**综合设施可达性**，而不是步行耗时。
 *     耗时只反映「走得远近」，可达性才反映「到了之后有没有东西用」——
 *     这才是生活圈体检要表达的东西。
 *
 *     颜色含义：绿 = 周边设施便利；红 = 配套匮乏（即服务盲区）。
 *     因为只在等时圈范围内着色，一张图同时表达了
 *     「等时圈范围」与「盲区分布」，红区即盲区。
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
        // 略微放大，消除浮点误差造成的细缝
        const half = (stepM / 2) * 1.03;

        // 可达性得分的实际分布通常落在 0.25~0.80，
        // 若直接把它当作色带比例，整张图会挤在中段、一片黄而分不出差异，
        // 因此把这个区间线性拉伸到完整色域以增强对比
        const SCORE_LO = 0.25;
        const SCORE_HI = 0.8;

        points.forEach((p) => {
            const score = typeof p.accessibility === 'number' ? p.accessibility : 0;
            const normalized = (score - SCORE_LO) / (SCORE_HI - SCORE_LO);
            const color = this.colorFor(1 - Math.max(0, Math.min(1, normalized)));

            const nw = offsetMeters(p.lng, p.lat, -half, +half);
            const ne = offsetMeters(p.lng, p.lat, +half, +half);
            const se = offsetMeters(p.lng, p.lat, +half, -half);
            const sw = offsetMeters(p.lng, p.lat, -half, -half);

            const polygon = new BMap.Polygon(
                [nw, ne, se, sw].map((c) => new BMap.Point(c[0], c[1])),
                { strokeWeight: 0, fillColor: color, fillOpacity: 0.72 }
            );
            MapManager.map.addOverlay(polygon);
        });
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
        const reachable = points.filter((p) => p.reachable);
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
