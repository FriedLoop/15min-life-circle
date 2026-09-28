"""百度地图 Web 服务 API 统一客户端。

集中处理四件事，让上层服务只关心业务逻辑：
    1. AK 注入与缺失校验
    2. 超时与指数退避重试（仅对网络类错误重试）
    3. 并发限流（个人开发者并发上限 3，超出会被限流）
    4. 错误归一化，全部抛 BaiduApiError

配额说明：批量算路等服务按「最终路线数」计费，而非请求数，
因此调用量优化（分批、缓存、粗筛）直接决定日配额够不够用。
"""

import asyncio
from typing import Any

import httpx

from app.core.config import settings


class BaiduApiError(Exception):
    """百度地图 API 调用失败。"""

    def __init__(self, message: str, status: int | None = None):
        self.message = message
        self.status = status
        super().__init__(message)


class BaiduClient:
    """百度地图 HTTP 客户端（异步）。"""

    def __init__(self) -> None:
        self._base = settings.BAIDU_API_BASE
        self._timeout = settings.HTTP_TIMEOUT
        self._retries = settings.HTTP_RETRIES
        self._semaphore: asyncio.Semaphore | None = None
        self._semaphore_loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------
    # 并发控制
    # ------------------------------------------------------------------
    def _get_semaphore(self) -> asyncio.Semaphore:
        """懒加载信号量。

        asyncio.Semaphore 绑定事件循环，跨循环复用会报错，
        因此换成新的事件循环时重建。
        """
        loop = asyncio.get_running_loop()
        if self._semaphore is None or self._semaphore_loop is not loop:
            self._semaphore_loop = loop
            self._semaphore = asyncio.Semaphore(settings.HTTP_MAX_CONCURRENCY)
        return self._semaphore

    # ------------------------------------------------------------------
    # 核心请求
    # ------------------------------------------------------------------
    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        """发起一次 GET 请求并返回解析后的 JSON。

        Raises:
            BaiduApiError: AK 未配置、网络异常或接口返回非 0 状态码。
        """
        ak = settings.BAIDU_SERVER_AK
        if not ak:
            raise BaiduApiError("未配置 BAIDU_SERVER_AK，请检查 backend/.env 文件")

        query = {**(params or {}), "ak": ak, "output": "json"}
        url = f"{self._base}{path}"

        async with self._get_semaphore():
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                last_error: Exception | None = None

                for attempt in range(self._retries + 1):
                    try:
                        resp = await client.get(url, params=query)
                        data = resp.json()
                    except (httpx.RequestError, ValueError) as exc:
                        last_error = exc
                        if attempt < self._retries:
                            await asyncio.sleep(0.5 * 2**attempt)
                            continue
                        raise BaiduApiError(f"请求百度地图网络异常：{exc}") from exc

                    status = data.get("status")
                    if status == 0:
                        return data

                    # 业务错误（参数错误、配额超限、AK 无效等）重试无意义，直接抛出
                    raise BaiduApiError(
                        data.get("message") or "百度地图接口返回未知错误",
                        status=status,
                    )

                raise BaiduApiError(f"请求百度地图失败：{last_error}")

    async def gather(
        self, requests: list[tuple[str, dict[str, Any] | None]]
    ) -> list[dict]:
        """并发发起多个请求，按输入顺序返回结果。

        用于批量算路等需要把大矩阵切成多个小请求的场景。
        """
        tasks = [self.get(path, params) for path, params in requests]
        return list(await asyncio.gather(*tasks))


# 全局单例，复用连接与限流状态
baidu_client = BaiduClient()
