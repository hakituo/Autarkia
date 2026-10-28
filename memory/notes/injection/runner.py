"""梗概自动注入的取数（同步，跑在工作线程）：读梗概、检索、读闸门、隐私过滤、缓存。

- 相关梗概走 ``NoteRetriever.search``（自带闸门）；计划 / 偏好不经检索，用同一个
  ``read_gate_hidden`` 判定：任一来源事件被隐藏就整条丢弃（与 retrieval 口径一致）。
- 全量梗概按「scope + 各会话文件 mtime」缓存（与闸门无关）。最终结果**不缓存**：读闸门还看
  会话树的当前游标，切分支后旧结果可能把兄弟线的梗概带进来，宁可每轮重算。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from . import selection

QUERY_CHARS = 200

_lock = threading.Lock()
_corpus_cache: dict[str, tuple[tuple, list[dict[str, Any]]]] = {}


def reset_injection_cache() -> None:
    with _lock:
        _corpus_cache.clear()


def _stamps(store: Any) -> tuple:
    """各会话的新旧梗概文件 mtime（v2 过渡期新旧双读，见 ``memory.notes.legacy``）。"""
    from memory.notes import legacy

    return tuple(
        (cid, legacy.readable_stamp(store, cid)) for cid in legacy.readable_conversations(store)
    )


def _all_notes(store: Any, stamps: tuple) -> list[dict[str, Any]]:
    from memory.notes import legacy

    with _lock:
        cached = _corpus_cache.get(store.scope)
        if cached and cached[0] == stamps:
            return cached[1]
    notes = [
        n
        for cid, _ in stamps
        for n in legacy.readable_notes(store, cid)
        if str(n.get("text") or "").strip()
    ]
    with _lock:
        _corpus_cache[store.scope] = (stamps, notes)
    return notes


def _gate_visible(
    notes: Sequence[dict[str, Any]], scope: str, conversation_id: str, gate: Callable
) -> list[dict[str, Any]]:
    payloads = [
        {
            "event_id": str(event_id),
            "conversation_id": str(note.get("conversation_id") or ""),
            "storage_scope": scope,
            "timestamp": float(note.get("occurred_from") or note.get("recorded_from") or 0),
        }
        for note in notes
        for event_id in note.get("source_event_ids") or []
    ]
    hidden = gate(payloads, conversation_id, None) if payloads else set()
    # 没有来源事件的梗概写入时已被拒，这里仍保守丢弃
    return [
        n for n in notes if n.get("source_event_ids") and not hidden & set(n["source_event_ids"])
    ]


def _is_sensitive(note: Mapping[str, Any]) -> bool:
    from core.tools.memory_notes_search import is_sensitive_note

    return is_sensitive_note(str(note.get("text") or ""))


def build_block(
    *,
    user_id: str,
    query: str,
    exclude_sensitive: bool,
    existing: Sequence[str] = (),
    now: float | None = None,
    store: Any = None,
    retriever: Any = None,
    gate: Callable | None = None,
) -> str:
    """组装本轮注入块（同步）；``store`` / ``retriever`` / ``gate`` 供测试注入。"""
    if store is None:
        from core.utils.data.data_paths import resolve_data_scope_from_conversation_id
        from memory.notes.store import NoteStore

        store = NoteStore(resolve_data_scope_from_conversation_id(user_id))
    if gate is None:
        from memory.notes.retrieval import read_gate_hidden as gate
    now = time.time() if now is None else now
    query = str(query or "").strip()[:QUERY_CHARS]

    stamps = _stamps(store)
    if not stamps:
        return ""
    relevant: list[dict[str, Any]] = []
    if query:
        if retriever is None:
            from memory.notes.retrieval import NoteRetriever

            retriever = NoteRetriever(store.scope, store=store, gate=gate)
        relevant = list(
            retriever.search(
                query,
                conversation_id=user_id,
                limit=selection.RELEVANT.limit * selection.CANDIDATE_FACTOR,
            )
        )
    notes = _all_notes(store, stamps)
    # 计划要连同「已完成 / 已取消」的收尾条目一起过闸门：兄弟线上的收尾不能关掉本线的计划
    standing = selection.plan_pool(notes, now) + selection.pick_preferences(notes)
    standing = _gate_visible(standing, store.scope, user_id, gate)
    sections = {
        "relevant": relevant,
        "plan": selection.pick_plans(standing, now),
        "preference": [n for n in standing if n.get("kind") == "preference"],
    }
    if exclude_sensitive:
        sections = {k: [n for n in v if not _is_sensitive(n)] for k, v in sections.items()}
    return selection.render(selection.compose(sections, existing))


__all__ = ["build_block", "reset_injection_cache"]
