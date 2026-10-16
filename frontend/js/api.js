/**
 * 后端接口封装。
 *
 * 统一处理错误：后端返回 {"detail": "..."} 时，把 detail 作为错误信息抛出，
 * 便于直接展示给用户（例如「未配置百度地图服务端 AK」这类提示）。
 *
 * 坐标系约定：所有分析接口都接受 coord_type（bd09 / gcj02 / wgs84），
 * 非 BD09 时由后端先转换为 BD09 再分析。前端只在「用户明确声明了来源坐标系」
 * 时才传非 bd09 的值——地图点击与示例点位本来就是 BD09。
 */
const Api = {
    async _post(path, body) {
        const res = await fetch(`${AppConfig.backendBase}${path}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });

        const text = await res.text();
        let data = {};
        try {
            data = JSON.parse(text);
        } catch (e) {
            // 非 JSON 响应（如网关错误页），保留原始文本便于排查
        }

        if (!res.ok) {
            throw new Error(data.detail || `请求失败（HTTP ${res.status}）`);
        }
        return data;
    },

    /**
     * 生成体检报告（等时圈 + 设施覆盖 + 盲区 + 健康度评分）。
     * @param {number} lng
     * @param {number} lat
     * @param {number} walkMinutes 步行时间阈值
     * @param {string[]|null} categories 关注类别；传 null 表示全部
     * @param {number|null} stepM 网格间隔（米）；传 null 使用后端默认值
     * @param {string} coordType 输入坐标所属坐标系 bd09 / gcj02 / wgs84
     * @param {boolean} coarseGrid 是否启用「分级网格 + IDW 插值」优化
     */
    async getReport(lng, lat, walkMinutes, categories, stepM, coordType, coarseGrid) {
        return this._post('/api/report', {
            lng,
            lat,
            walk_minutes: walkMinutes,
            step_m: stepM || null,
            categories: categories && categories.length ? categories : null,
            coord_type: coordType || 'bd09',
            coarse_grid: !!coarseGrid,
            with_address: true,
        });
    },

    /** 地名 -> 坐标（BD09） */
    async geocode(address) {
        return this._post('/api/geocode', { address, city: '东莞市' });
    },

    /**
     * 坐标转换：把其它坐标系的坐标统一转成 BD09。
     * @param {Array<{lng:number,lat:number}>} points
     * @param {string} coordType 输入坐标系
     */
    async convert(points, coordType) {
        return this._post('/api/convert', {
            points,
            coord_type: coordType,
            use_api: true,
        });
    },

    /**
     * 检索中心点周边的原始 POI（按类别分别检索）。
     * @param {number} lng
     * @param {number} lat
     * @param {number} radius 检索半径（米）
     * @param {string[]|null} categories 只检索指定类别；null 表示全部
     * @param {string} coordType 输入坐标系
     */
    async getPoi(lng, lat, radius, categories, coordType) {
        return this._post('/api/get_poi', {
            lng,
            lat,
            radius,
            categories: categories && categories.length ? categories : null,
            coord_type: coordType || 'bd09',
        });
    },
};
