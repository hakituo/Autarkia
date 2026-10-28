"""分段器 v2 的切点账本：已封口会话的切点只算一次，重放读账本，保证同输入同段号。

落盘 ``<scope>_data/memories/topology/segment_cuts.json``：
``{"version": 1, "sessions": {session_digest: {"cuts": [event_id...], "segmenter": "2",
"embed_model": "...", "recorded_at": ts}}}``。账本是派生缓存，删掉会按同一模型重算。
路径函数在调用时解析，测试 monkeypatch 本模块即可改道。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from core.utils.atomic_io import safe_json_dump, safe_json_load
from memory.topology.topic_split import SEGMENTER_V2

EMBED_MODEL = "bge-small-zh"
_lock = threading.Lock()


def ledger_path(scope: str) -> Path:
    from core.utils.data.data_paths import get_role_memories_dir

    return Path(get_role_memories_dir(scope)) / "topology" / "segment_cuts.json"


class CutLedger:
    def __init__(self, scope: str, path: Path | None = None) -> None:
        self.scope = scope
        self.path = path or ledger_path(scope)
        data = safe_json_load(self.path, default=None)
        sessions = data.get("sessions") if isinstance(data, dict) else None
        self._sessions: dict[str, dict[str, Any]] = dict(sessions or {})
        self._dirty = False
        self.hits = 0
        self.recorded = 0

    def lookup(self, digest: str, _session: Any = None) -> list[str] | None:
        entry = self._sessions.get(digest)
        if not entry or entry.get("segmenter") != SEGMENTER_V2:
            return None
        self.hits += 1
        return [str(item) for item in entry.get("cuts") or []]

    def record(self, digest: str, cuts: list[str]) -> None:
        if digest in self._sessions:
            return
        self._sessions[digest] = {
            "cuts": list(cuts),
            "segmenter": SEGMENTER_V2,
            "embed_model": EMBED_MODEL,
            "recorded_at": time.time(),
        }
        self._dirty = True
        self.recorded += 1

    def save(self) -> None:
        if not self._dirty:
            return
        with _lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            safe_json_dump({"version": 1, "sessions": self._sessions}, self.path)
        self._dirty = False


__all__ = ["EMBED_MODEL", "CutLedger", "ledger_path"]
