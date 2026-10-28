"""笔记库落盘路径。目录函数在调用时才解析，测试 monkeypatch 本模块即可改道。"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


def active_segmenter() -> str:
    """当前生效的分段器版本（settings ``memory.notes_segmenter``），读不到按 v1。"""
    try:
        from config.integrated_config import get_settings

        value = str(get_settings().memory.notes_segmenter or "v1").strip().lower()
    except Exception:  # noqa: BLE001 - 配置不可用时按现行 v1
        return "v1"
    return value if value in {"v1", "v2"} else "v1"


def notes_dir_name() -> str:
    return "notes_v2" if active_segmenter() == "v2" else "notes"


def notes_dir(scope: str) -> Path:
    """``<scope>_data/memories/notes``（v2 分段为 ``notes_v2``）；测试替换本函数到临时目录。"""
    from core.utils.data.data_paths import get_role_memories_dir

    return Path(get_role_memories_dir(scope)) / notes_dir_name()


def notes_file_name(conversation_id: str) -> str:
    raw = str(conversation_id or "")
    safe = re.sub(r"[^0-9A-Za-z_.-]+", "_", raw)[:120] or "default"
    if safe != raw:  # 清洗过的名字加原值哈希，避免不同会话撞同一文件
        safe += "-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    return f"{safe}.json"


def notes_path(scope: str, conversation_id: str) -> Path:
    return notes_dir(scope) / notes_file_name(conversation_id)


def legacy_notes_dir(scope: str) -> Path | None:
    """v2 过渡期的旧梗概目录（与 ``notes_v2`` 同级的 ``notes``）；当前不是 v2 时为 None。

    由 ``notes_dir`` 推出：测试把 ``notes_dir`` 改道到临时目录时，旧目录也跟着在临时目录里。
    """
    current = notes_dir(scope)
    return current.parent / "notes" if current.name == "notes_v2" else None
