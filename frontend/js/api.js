/**
 * 后端接口封装。
 *
 * 统一处理错误：后端返回 {"detail": "..."} 时，把 detail 作为错误信息抛出，
 * 便于直接展示给用户（例如「未配置百度地图服务端 AK」这类提示）。
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
     */
    async getReport(lng, lat, walkMinutes, categories, stepM) {
        return this._post('/api/report', {
            lng,
            lat,
            walk_minutes: walkMinutes,
            step_m: stepM || null,
            categories: categories && categories.length ? categories : null,
            with_address: true,
        });
    },

    /** 地名 -> 坐标（BD09） */
    async geocode(address) {
        return this._post('/api/geocode', { address, city: '东莞市' });
    },
};
