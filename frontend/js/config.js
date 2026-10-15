/**
 * 全局配置。
 *
 * 后端地址、地图 AK、示例点位、设施类别全部从后端 /api/config 拉取，
 * 不在前端源码里硬编码任何密钥——这样仓库可以直接开源，
 * 更换 AK 也只需改后端 .env，无需改动代码。
 */
const AppConfig = {
    backendBase: '',
    baiduAk: '',
    defaultCenter: null,
    samples: [],
    categories: [],
    keyCategories: [],
    backendReady: false,

    /** 推断后端地址：同源部署用相对路径，开发时后端在 8000 端口 */
    detectBackendBase() {
        const port = window.location.port;
        if (port === '8000') return '';          // 由 FastAPI 同源提供
        return 'http://127.0.0.1:8000';          // 独立静态服务时的后端地址
    },

    /** 启动时加载配置；失败时抛出错误由入口处理 */
    async load() {
        this.backendBase = this.detectBackendBase();

        const res = await fetch(`${this.backendBase}/api/config`);
        if (!res.ok) {
            throw new Error(`无法连接后端（${res.status}），请确认已启动：uvicorn main:app --port 8000`);
        }

        const data = await res.json();
        this.baiduAk = data.baidu_browser_ak || '';
        this.defaultCenter = data.default_center;
        this.samples = data.samples || [];
        this.categories = data.categories || [];
        this.keyCategories = data.key_categories || [];
        this.backendReady = !!data.backend_ready;

        return this;
    },
};
