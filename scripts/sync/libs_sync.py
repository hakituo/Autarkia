"""组件库双向同步入口（薄壳，逻辑在 scripts/sync/libs/ 下）。

常用：

    python scripts/sync/libs_sync.py status    # 看哪边领先、Windows 是否一致
    python scripts/sync/libs_sync.py task      # 生成双向移植任务
    python scripts/sync/libs_sync.py push      # 提交+推送组件库改动
    python scripts/sync/libs_sync.py mirror    # Linux ↔ Windows 快进同步

``auto_commit_push.py`` 默认会调用同一套逻辑：主仓改到映射文件、或组件库
有未提交改动时，两边一起提交推送。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.sync.libs.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
