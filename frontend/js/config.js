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

    /**
     * 后端地址：本应用由 FastAPI **同源**托管前端（单端口部署），
     * 因此一律用相对路径即可，不需要猜端口。
     *
     * 这里曾经写成「端口是 8000 才用相对路径，否则硬编码 127.0.0.1:8000」，
     * 后果是任何非 8000 端口的部署都会去连那个写死的地址：
     * 换端口跑（含 IDE 里换端口预览）时页面能打开、接口全 404/连错服务，
     * 而错误信息只表现为「无法连接后端」，极难定位。
     * 同源是部署模型本身决定的，不该靠猜。
     */
    detectBackendBase() {
        return '';
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
