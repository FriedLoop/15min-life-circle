/**
 * 地图管理。
 *
 * 百度地图 JS API 需要 AK，而 AK 由后端下发，
 * 因此这里动态创建 <script> 加载，而不是写死在 HTML 里。
 */
const MapManager = {
    map: null,
    centerMarker: null,
    /** 用户在地图上点击选点时的回调 */
    onSelect: null,

    /**
     * 动态加载百度地图脚本。
     * @param {string} ak 浏览器端 AK
     * @returns {Promise<void>}
     */
    loadScript(ak) {
        return new Promise((resolve, reject) => {
            if (window.BMap) {
                resolve();
                return;
            }
            if (!ak) {
                reject(new Error('未获取到地图 AK，请检查后端 .env 中的 BAIDU_BROWSER_AK'));
                return;
            }

            // 百度 JS API 通过 callback 参数回调全局函数
            window.__baiduMapReady = () => resolve();

            const script = document.createElement('script');
            script.src =
                `https://api.map.baidu.com/api?v=3.0&ak=${ak}&callback=__baiduMapReady`;
            script.onerror = () => reject(new Error('百度地图脚本加载失败，请检查网络或 AK'));
            document.body.appendChild(script);
        });
    },

    /**
     * 初始化地图。
     * @param {{lng:number, lat:number}} center
     */
    init(center) {
        this.map = new BMap.Map('map-container');
        const point = new BMap.Point(center.lng, center.lat);
        this.map.centerAndZoom(point, 16);
        this.map.enableScrollWheelZoom(true);
        this.map.addControl(new BMap.NavigationControl());
        this.map.addControl(new BMap.ScaleControl());

        this.map.addEventListener('click', (e) => {
            this.setCenter(e.point.lng, e.point.lat);
            if (this.onSelect) this.onSelect(e.point.lng, e.point.lat);
        });
    },

    /** 设置中心点并放置标记 */
    setCenter(lng, lat) {
        const point = new BMap.Point(lng, lat);
        this.map.setCenter(point);

        if (this.centerMarker) {
            this.map.removeOverlay(this.centerMarker);
        }

        // 使用百度默认标记（红色气球）：形状独特、辨识度高于自定义圆点
        this.centerMarker = new BMap.Marker(point);
        this.map.addOverlay(this.centerMarker);
    },

    /** 移除中心标记以外的所有覆盖物 */
    clearOverlays() {
        const keep = this.centerMarker;
        this.map.clearOverlays();
        if (keep) {
            this.centerMarker = keep;
            this.map.addOverlay(keep);
        } else {
            this.centerMarker = null;
        }
    },
};
