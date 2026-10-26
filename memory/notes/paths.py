"""笔记库落盘路径。目录函数在调用时才解析，测试 monkeypatch 本模块即可改道。"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


def notes_dir(scope: str) -> Path:
    """``<scope>_data/memories/notes``；测试替换本函数到临时目录。"""
    from core.utils.data.data_paths import get_role_memories_dir

    return Path(get_role_memories_dir(scope)) / "notes"


def notes_path(scope: str, conversation_id: str) -> Path:
    raw = str(conversation_id or "")
    safe = re.sub(r"[^0-9A-Za-z_.-]+", "_", raw)[:120] or "default"
    if safe != raw:  # 清洗过的名字加原值哈希，避免不同会话撞同一文件
        safe += "-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    return notes_dir(scope) / f"{safe}.json"
