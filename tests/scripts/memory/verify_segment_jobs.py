"""验证按段作业编排（v3 F3 · WP3）：临时数据 + FakeExtractor 端到端跑两晚。

所有落盘都指到临时目录（聊天记录、游标、笔记库、账本），不碰真实 companion_data：

    venv_cpu/bin/python tests/scripts/memory/verify_segment_jobs.py

第一晚：两段已封口、尾段未封口 → 只提取两段；
第二晚：尾段封口并新增一段 → 只提取新封口的段，前两段不重跑；
最后换提取器版本 → 全部按新版本重算。
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.services.chat_history_store import ChatHistoryStore
from memory.nightly.config import DEFAULT_NIGHTLY_CONFIG
from memory.nightly.segment_jobs import run as seg_run
from memory.nightly.segment_jobs.testing import FakeExtractor

CONV = "verify_segment_jobs__scope__aveline"
BASE_TS = 1_700_000_000.0
HOUR = 3600.0


class _Manager:
    user_id = "shared__scope__aveline"
    storage_scope = "aveline"

    def __init__(self, history_dir: Path) -> None:
        self._memory_layout = {"history_dir": str(history_dir)}
        self.lock = threading.RLock()


def _isolate(tmp: Path, store: ChatHistoryStore) -> None:
    from core.utils.data import data_paths
    from memory.notes import paths as note_paths
    from memory.topology import cursors, read_gate, tree_registry

    cursors.base_dir_for = lambda scope: tmp / "cursors" / scope
    cursors.load_overlay = lambda _cid, _scope: None
    tree_registry._default_overlay_loader = lambda _cid, _scope: None
    read_gate._default_tree_reader = lambda cid: store.list_conversation_events(cid, limit=0)
    data_paths.get_role_chat_history_dir = lambda _scope: tmp / "chat_history"
    note_paths.notes_dir = lambda scope: tmp / "notes" / scope
    seg_run.resolve_distillation_perspective = lambda _m: {"role_id": "aveline"}
    cursors.reset_cursor_cache()
    tree_registry.reset_tree_registry()


def _chat(store: ChatHistoryStore, start: float, turns: int, tag: str) -> None:
    for index in range(turns):
        ts = BASE_TS + start + index * 60
        for role, offset in (("user", 0), ("assistant", 1)):
            store.append_event(
                conversation_id=CONV,
                role=role,
                content=f"{tag}-{role}-{index}",
                message_id=f"{tag}-m{index}",
                now_dt=datetime.fromtimestamp(ts + offset, tz=timezone.utc),
            )


def _night(manager, extractor, now: float) -> dict:
    config = {**DEFAULT_NIGHTLY_CONFIG, "segment_extraction_enabled": True}
    return asyncio.run(
        seg_run.run_segment_jobs(manager.user_id, manager, config, extractor=extractor, now=now)
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        store = ChatHistoryStore(tmp / "chat_history")
        _isolate(tmp, store)
        manager = _Manager(tmp / "memories")
        # 三段对话，各间隔 2 小时（空闲封口）；第一晚在最后一段结束后 10 分钟跑
        for index in range(3):
            _chat(store, index * 2 * HOUR, 3, f"s{index}")
        fake = FakeExtractor("fake-1")
        night1 = _night(manager, fake, BASE_TS + 4 * HOUR + 10 * 60)
        calls_after_1 = list(fake.calls)
        _chat(store, 6 * HOUR, 3, "s3")
        night2 = _night(manager, fake, BASE_TS + 30 * HOUR)
        upgraded = FakeExtractor("fake-2")
        night3 = _night(manager, upgraded, BASE_TS + 54 * HOUR)

        from memory.notes import NoteStore

        notes = NoteStore("aveline").list_notes(CONV)
        ledger_dir = seg_run.segment_ledger_path(manager).parent
        checks = {
            "第一晚只取封口段": night1["done"] == 2 and night1["segments_closed"] == 2,
            "第二晚不重跑旧段": night2["done"] == 2
            and not set(fake.calls[2:]) & set(calls_after_1),
            "换版本全部重算": night3["done"] == 4 and len(upgraded.calls) == 4,
            "笔记按段替换无重复": len(notes) == 4
            and all(note["extractor_version"] == "fake-2" for note in notes),
            "账本与旧蒸馏分开": [p.name for p in ledger_dir.iterdir()]
            == ["shared__scope__aveline_segment_jobs.json"],
        }
        keys = ("segments_closed", "pending", "picked", "done", "skipped", "failed", "released")
        summary = {
            name: {key: report.get(key) for key in keys}
            for name, report in (("night1", night1), ("night2", night2), ("night3", night3))
        }
        print(json.dumps({"nights": summary, "checks": checks}, ensure_ascii=False, indent=2))
        return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
