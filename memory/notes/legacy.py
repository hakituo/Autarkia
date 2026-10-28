"""分段器 v2 的双读：新梗概（``notes_v2``）与旧梗概（``notes``）一起读。

- 新库写，旧库只读，旧梗概不删不重跑；
- 检索 / 自动注入 / 展开原话默认新旧**都读**，同一段对话的旧梗概也不隐藏：2026-10-28 aveline
  39 题答题，新旧一起 18.3–18.7 > 只读新 17.3–17.7 > 只读旧 16.0–16.3。旧梗概一条覆盖一大段、
  原话保留得多，补新梗概按话题改写后丢原词的短板（时间题尤其明显）；
- 人物线索仍按「覆盖」去重（``include_covered=False``）：旧梗概只要有一条来源事件已被新库某段
  覆盖（段条目的 ``source_event_ids``，没有时退回该段梗概的来源并集）就不再计入，免得同一段
  的人物线索算两遍；
- 当前不是 v2（``paths.legacy_notes_dir`` 为 None）时，与只读当前库完全相同。

写入与「哪些段已完成」的判断仍只看当前库。
"""

from __future__ import annotations

import os
from typing import Any

from . import paths
from .store import NoteStore


def legacy_store(store: NoteStore) -> NoteStore | None:
    if store.root is not None:
        return None
    root = paths.legacy_notes_dir(store.scope)
    if root is None or not root.exists():
        return None
    return NoteStore(store.scope, perspective_role=store.perspective_role, root=root)


def readable_conversations(store: NoteStore) -> list[str]:
    found = list(store.list_conversations())
    old = legacy_store(store)
    if old is not None:
        found += [cid for cid in old.list_conversations() if cid not in set(found)]
    return found


def covered_events(store: NoteStore, conversation_id: str) -> set[str]:
    covered: set[str] = set()
    for entry in store.segment_entries(conversation_id).values():
        ids = entry.get("source_event_ids")
        if ids is None:
            ids = [e for note in entry.get("notes") or [] for e in note.get("source_event_ids") or []]
        covered.update(str(e) for e in ids)
    return covered


def readable_notes(
    store: NoteStore, conversation_id: str, *, include_covered: bool = True
) -> list[dict[str, Any]]:
    notes = store.list_notes(conversation_id)
    old = legacy_store(store)
    if old is None:
        return notes
    if include_covered:
        return notes + old.list_notes(conversation_id)
    covered = covered_events(store, conversation_id)
    for note in old.list_notes(conversation_id):
        sources = {str(e) for e in note.get("source_event_ids") or []}
        if not sources & covered:
            notes.append(note)
    return notes


def readable_stamp(store: NoteStore, conversation_id: str) -> tuple[float, float]:
    """新旧两个文件的 mtime，作检索 / 注入缓存的失效键。"""

    def mtime(target: NoteStore | None) -> float:
        if target is None:
            return 0.0
        try:
            return os.path.getmtime(target.path(conversation_id))
        except OSError:
            return 0.0

    return mtime(store), mtime(legacy_store(store))


__all__ = [
    "covered_events",
    "legacy_store",
    "readable_conversations",
    "readable_notes",
    "readable_stamp",
]
