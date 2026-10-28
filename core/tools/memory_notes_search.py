"""search_memory 的派生笔记检索段（v3 G）：按会话归属的 scope 查每段梗概。

梗概走 ``memory.notes.retrieval``（BM25 + 向量 RRF → 世界线闸门），这里只负责
开关、scope 解析和把命中转成工具结果条目。任何异常都退回空结果，不拖垮旧检索。
"""

from __future__ import annotations

from typing import Any

from core.utils.logger import get_logger

logger = get_logger("SearchMemoryTool")

SOURCE_NOTES = "notes"


def notes_retrieval_enabled() -> bool:
    try:
        from config.integrated_config import get_settings

        return bool(get_settings().memory.notes_retrieval_enabled)
    except Exception:  # noqa: BLE001 - 读不到配置按默认开启
        return True


def is_sensitive_note(text: str) -> bool:
    """与旧加权记忆同一套话题判定；梗概一段混多个话题，前 3 个话题里有 sensitive 就算。"""
    from memory.core.taxonomy import detect_topics

    return "sensitive" in detect_topics(str(text or ""), max_topics=3)


def search_note_entries(
    user_id: str, query: str, limit: int, *, request_scope: str | None = None
) -> list[dict[str, Any]]:
    """返回与旧结果同形的条目（content / timestamp / source / category），附时间段与来源。

    ``request_scope`` 是请求的内容作用域（sfw / private）：与旧加权记忆一致，SFW 且开了隐私隔离时
    排除敏感梗概（``core.utils.privacy.should_exclude_sensitive``）。
    """
    if not notes_retrieval_enabled() or not str(query or "").strip():
        return []
    try:
        from core.utils.data.data_paths import resolve_data_scope_from_conversation_id
        from core.utils.privacy import should_exclude_sensitive
        from memory.notes.retrieval import NoteRetriever

        exclude = should_exclude_sensitive(scope=request_scope)
        scope = resolve_data_scope_from_conversation_id(user_id)
        hits = NoteRetriever(scope).search(
            query, conversation_id=user_id, limit=limit * 3 if exclude else limit
        )
        if exclude:
            hits = [hit for hit in hits if not is_sensitive_note(hit.get("text") or "")]
        hits = hits[:limit]
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"梗概检索失败，退回旧检索: {type(exc).__name__}: {exc}")
        return []
    return [
        {
            "content": hit["text"],
            "timestamp": hit.get("occurred_from") or 0,
            "occurred_to": hit.get("occurred_to"),
            "source": SOURCE_NOTES,
            # episode 梗概 / fact / preference / plan（提取器 v8 起的短事实）
            "category": hit.get("kind") or "episode",
            "importance": hit.get("importance"),
            "status": hit.get("status"),
            "note_id": hit["note_id"],
            "source_event_ids": hit.get("source_event_ids") or [],
        }
        for hit in hits
    ]


#: 派生笔记在工具结果里的标签（模型读的是中文）
NOTE_LABELS = {"episode": "梗概", "fact": "事实", "preference": "偏好", "plan": "计划"}
#: plan 状态后缀：做完 / 取消的计划不能看着像还没做
STATUS_LABELS = {"done": "·已完成", "cancelled": "·已取消", "expired": "·已过期"}


def note_label(entry: dict[str, Any]) -> str:
    """``- [梗概] [10-26 14:00–14:20] …`` 里的「[梗概] [时间段]」部分（跨天时结束带日期）。"""
    from core.utils.time_utils import format_timestamp

    label = NOTE_LABELS.get(str(entry.get("category") or ""), "梗概")
    label += STATUS_LABELS.get(str(entry.get("status") or ""), "")
    start, end = entry.get("timestamp"), entry.get("occurred_to")
    if not start:
        return f"[{label}]"
    text = format_timestamp(float(start), "%m-%d %H:%M")
    if end and float(end) - float(start) >= 60:
        same_day = format_timestamp(float(end), "%m-%d") == format_timestamp(float(start), "%m-%d")
        text += "–" + format_timestamp(float(end), "%H:%M" if same_day else "%m-%d %H:%M")
    return f"[{label}] [{text}]"


def merge_with_notes(
    notes: list[dict[str, Any]], others: list[dict[str, Any]], limit: int
) -> list[dict[str, Any]]:
    """梗概在前（C8：梗概是更好的主检索单元），给旧记忆 / 原文留 1 个位置。

    原文与梗概不同池排序：原文补在后面，用于需要原话的场景。原先留 2 个位置时，
    默认 5 条里梗概只剩 3 条、主动关怀（3 条）只剩 1 条；四分之一实测证据@3→@5 多 2 题。
    """
    if not notes:
        return others[:limit]
    quota = max(1, limit - 1) if others else limit
    picked = notes[:quota]
    return picked + others[: max(limit - len(picked), 0)]


__all__ = [
    "NOTE_LABELS",
    "SOURCE_NOTES",
    "is_sensitive_note",
    "merge_with_notes",
    "note_label",
    "notes_retrieval_enabled",
    "search_note_entries",
]
