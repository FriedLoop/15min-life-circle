"""pytest 公共配置：把 backend 目录加入模块搜索路径。

测试文件位于 backend/tests/，业务代码在 backend/app/。
无论从仓库根目录还是 backend 目录执行 pytest，
这里都统一插入 backend 的绝对路径，保证 `import app.xxx` 可用。
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
