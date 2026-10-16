"""配置解析：AK 是否「真的可用」的判定。

背景：`/api/health` 与 `/api/config` 原本用 `bool(BAIDU_SERVER_AK)` 判断就绪状态。
但 `.env.example` 里的占位符 `your_baidu_server_ak_here` 是非空字符串，
于是忘填 AK 时接口会报告「已配置」、页面顶部显示「后端已就绪」，
而随后**每一个分析请求都会失败**（百度返回 AK 参数错误）。

这类「界面说好了、一点就报错」的失败模式最难自查，因此把占位符
也视为「未配置」，并在这里把判定规则固定下来。
"""

import pytest

from app.core.config import Settings, _looks_unfilled

# 真实百度 AK 的形态：随机字母数字串，不含分隔符与提示词
REAL_AK = "Ab3Kd9XmQ2Lp7Rs1Zt5Yv8Nc"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        # .env.example 里实际使用的占位符
        "your_baidu_server_ak_here",
        "your-browser-ak",
        "<在此填入你的AK>",
        "xxx",
        "xxx_xxx",
        "请在控制台填入你的AK",
        "REPLACE_ME_placeholder",
    ],
)
def test_placeholder_is_treated_as_unfilled(value):
    assert _looks_unfilled(value) is True


@pytest.mark.parametrize(
    "value",
    [
        REAL_AK,
        "a1b2c3d4e5f6g7h8i9j0k1l2",
        # 含连字符/下划线的真实串也要认（不能因为符号就误判成占位符）
        "Ab3Kd9Xm-Q2Lp7Rs1Zt5Yv8Nc",
    ],
)
def test_real_looking_ak_is_accepted(value):
    assert _looks_unfilled(value) is False


def test_settings_ready_flags_follow_placeholder_rule():
    placeholder = Settings(
        BAIDU_SERVER_AK="your_baidu_server_ak_here",
        BAIDU_BROWSER_AK="your_baidu_browser_ak_here",
    )
    assert placeholder.server_ak_ready is False
    assert placeholder.browser_ak_ready is False

    ready = Settings(BAIDU_SERVER_AK=REAL_AK, BAIDU_BROWSER_AK=REAL_AK)
    assert ready.server_ak_ready is True
    assert ready.browser_ak_ready is True


def test_server_and_browser_ak_are_judged_independently():
    """两种 AK 必须分开判定。

    只配了服务端 AK 时，地图会因为浏览器端 AK 缺失而白屏——
    这时如果笼统报告「已就绪」，使用者会以为是网络或代码问题。
    """
    only_server = Settings(BAIDU_SERVER_AK=REAL_AK, BAIDU_BROWSER_AK="")
    assert only_server.server_ak_ready is True
    assert only_server.browser_ak_ready is False

    only_browser = Settings(BAIDU_SERVER_AK="", BAIDU_BROWSER_AK=REAL_AK)
    assert only_browser.server_ak_ready is False
    assert only_browser.browser_ak_ready is True
