#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 README.md 架构图（Mermaid）一致性。

检查项：
1. README.md 包含有效的 mermaid 代码块；
2. Mermaid 图中包含预期的分层与关键模块。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
README_PATH = ROOT / "readme.md"

EXPECTED_MERMAID_KEYWORDS = [
    "客户端 / 机器人",
    "接口层",
    "核心层",
    "记忆层",
    "调度层",
    "存储层",
    "AvelineService",
    "active_care",
    "agents",
    "/v1 OpenAI 兼容",
    "Obsidian",
    "ChromaDB",
]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def check_mermaid_block(readme: str) -> tuple[bool, str]:
    pattern = r"```mermaid\s*\n(.*?)\n```"
    match = re.search(pattern, readme, re.DOTALL)
    if not match:
        return False, "README.md 中未找到 ```mermaid ... ``` 代码块"
    mermaid = match.group(1)
    missing = [kw for kw in EXPECTED_MERMAID_KEYWORDS if kw not in mermaid]
    if missing:
        return False, f"Mermaid 图中缺少关键字: {missing}"
    return True, f"Mermaid 图包含全部 {len(EXPECTED_MERMAID_KEYWORDS)} 个预期关键字"


def main() -> int:
    errors: list[str] = []

    if not README_PATH.exists():
        errors.append(f"README 文件不存在: {README_PATH}")
        print("\n".join(errors))
        return 1

    readme = read_text(README_PATH)
    ok, msg = check_mermaid_block(readme)
    print(f"[{'PASS' if ok else 'FAIL'}] {msg}")
    if not ok:
        errors.append(msg)

    if errors:
        print("\n验证失败，请检查架构图内容。")
        return 1

    print("\n所有架构图验证通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
