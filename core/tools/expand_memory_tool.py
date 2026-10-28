"""ExpandMemoryTool — 按 search_memory 给出的梗概编号展开原话。

spec §9 第 2 条：需要原话时按 ``source_event_ids`` 回原始事件取，展开同样走读闸门。

- 只在当前会话所属 scope 的梗概库里找（与 search_memory 的梗概检索同一范围）；
- 来源事件先过分支边界、再过世界线读闸门，任何一条被隐藏、缺失或闸门出错都整条不展开
  （失败即关闭，不像检索那样退回放行）；
- SFW 时与 search_memory 同一套敏感判定（``is_sensitive_note``），梗概或任一原话命中即不展开；
- 找不到 / 无权限只回一句话，不抛异常。
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, Field

from core.tools.base import BaseTool
from core.utils.logger import get_logger

logger = get_logger("ExpandMemoryTool")

NOTE_PREFIX = "note_"
#: 梗概行尾短编号的长度（``note_`` + 8 位十六进制）
SHORT_REF_LEN = len(NOTE_PREFIX) + 8
DEFAULT_MAX_CHARS = 1500

MSG_NO_REF = "请提供 search_memory 结果里梗概行尾的编号（如 #note_1a2b3c4d）。"
MSG_NOT_FOUND = "没有找到这条梗概：编号可能有误，或不在当前会话的记忆范围内。"
MSG_AMBIGUOUS = "这个编号对应多条梗概，请使用更完整的编号。"
MSG_UNAVAILABLE = "这条梗概的原话当前无法展开（不可见或无权限）。"
MSG_FAILED = "展开原话失败，请直接依据梗概回答。"

_ROLE_LABELS = {"user": "用户", "assistant": "我"}


def short_note_ref(note_id: Any) -> str:
    """梗概在 search_memory 结果里显示的短编号；不是笔记编号时返回空串。"""
    text = str(note_id or "")
    return text[:SHORT_REF_LEN] if text.startswith(NOTE_PREFIX) else ""


def note_ref_suffix(note_id: Any) -> str:
    """梗概行尾的 `` #note_xxxxxxxx``；没有编号时为空串。"""
    ref = short_note_ref(note_id)
    return f" #{ref}" if ref else ""


def _normalize_ref(ref: Any) -> str:
    text = str(ref or "").strip().lstrip("#").strip().lower()
    if text and not text.startswith(NOTE_PREFIX):
        text = NOTE_PREFIX + text
    return text if len(text) > len(NOTE_PREFIX) else ""


def find_note(scope: str, ref: str, *, store: Any = None) -> tuple[dict | None, str]:
    """在 scope 的梗概库里按完整编号或前缀找笔记，返回 (笔记, 失败提示)。"""
    from memory.notes import legacy
    from memory.notes.store import NoteStore

    store = store or NoteStore(scope)
    matches: dict[str, dict[str, Any]] = {}
    for conversation_id in legacy.readable_conversations(store):  # v2 过渡期新旧双读
        for note in legacy.readable_notes(store, conversation_id):
            note_id = str(note.get("note_id") or "")
            if note_id == ref:
                return note, ""
            if note_id.startswith(ref):
                matches[note_id] = note
    if not matches:
        return None, MSG_NOT_FOUND
    if len(matches) > 1:
        return None, MSG_AMBIGUOUS
    return next(iter(matches.values())), ""


def _load_source_events(note: dict[str, Any], history_store: Any) -> list[dict] | None:
    """按 source_event_ids 取原始事件；任何一条缺失返回 None。"""
    wanted = [str(e) for e in note.get("source_event_ids") or [] if str(e)]
    if not wanted:
        return None
    events = history_store.list_conversation_events(
        str(note.get("conversation_id") or ""), limit=0
    )
    by_id = {str(item.get("event_id") or ""): item for item in events}
    if any(event_id not in by_id for event_id in wanted):
        return None
    return [by_id[event_id] for event_id in dict.fromkeys(wanted)]


def _all_visible(events: list[dict[str, Any]], conversation_id: str) -> bool:
    """分支边界 + 世界线读闸门（与 search_memory 原文段同一套）；全部可见才算通过。"""
    from core.agents.chat_agent_components.message_branch import (
        filter_events_by_branch_scope,
    )
    from memory.topology.read_gate import filter_raw_events

    scoped = filter_events_by_branch_scope(events, conversation_id=conversation_id)
    visible = filter_raw_events(scoped, conversation_id=conversation_id).events
    visible_ids = {str(item.get("event_id") or "") for item in visible}
    return all(str(item.get("event_id") or "") in visible_ids for item in events)


def _format(events: list[dict[str, Any]], max_chars: int) -> str:
    lines = []
    for item in sorted(events, key=lambda e: float(e.get("timestamp") or 0.0)):
        label = _ROLE_LABELS.get(str(item.get("role") or "").lower())
        content = str(item.get("content") or "").strip()
        if label and content:  # 思考 / 系统事件只参与闸门，不展示
            lines.append(f"{label}：{content}")
    if not lines:
        return ""
    shown: list[str] = []
    used = 0
    for index, line in enumerate(lines):
        if used + len(line) > max_chars:
            room = max_chars - used
            if room > 20 or not shown:
                shown.append(line[: max(room, 1)] + "……")
                index += 1
            rest = len(lines) - index
            tail = f"，另有 {rest} 条未显示" if rest > 0 else ""
            return "\n".join(shown) + f"\n（原话超过 {max_chars} 字已截断{tail}）"
        shown.append(line)
        used += len(line) + 1
    return "\n".join(shown)


def expand_note(
    conversation_id: str,
    note_ref: str,
    *,
    request_scope: str | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
    note_store: Any = None,
    history_store: Any = None,
) -> str:
    """工具主体（同步）：返回给模型的一段文本，任何失败都只回一句话。"""
    ref = _normalize_ref(note_ref)
    if not ref:
        return MSG_NO_REF
    try:
        from core.tools.memory_notes_search import is_sensitive_note
        from core.utils.data.data_paths import resolve_data_scope_from_conversation_id
        from core.utils.privacy import should_exclude_sensitive

        scope = resolve_data_scope_from_conversation_id(conversation_id)
        note, error = find_note(scope, ref, store=note_store)
        if note is None:
            return error
        exclude = should_exclude_sensitive(scope=request_scope)
        if exclude and is_sensitive_note(note.get("text") or ""):
            return MSG_UNAVAILABLE
        if history_store is None:
            from core.services.chat_history_store import get_chat_history_store

            history_store = get_chat_history_store()
        events = _load_source_events(note, history_store)
        if not events or not _all_visible(events, conversation_id):
            return MSG_UNAVAILABLE
        if exclude and any(is_sensitive_note(e.get("content") or "") for e in events):
            return MSG_UNAVAILABLE
        body = _format(events, max(int(max_chars), 1))
    except Exception as exc:  # noqa: BLE001 - 工具不向模型抛异常
        logger.warning(f"展开梗概原话失败: {type(exc).__name__}: {exc}")
        return MSG_FAILED
    if not body:
        return MSG_UNAVAILABLE
    return f"梗概 #{short_note_ref(note.get('note_id'))} 的原话（按时间顺序）：\n{body}"


class ExpandMemoryInput(BaseModel):
    note_id: str = Field(description="search_memory 结果里梗概行尾的编号，如 note_1a2b3c4d")
    max_chars: int = Field(
        default=DEFAULT_MAX_CHARS,
        description="原话最多返回的字数（200-6000），默认 1500",
        ge=200,
        le=6000,
    )


class ExpandMemoryTool(BaseTool):
    name = "expand_memory"
    description = (
        "按编号展开一条记忆梗概对应的原话。只在 search_memory 返回的梗概不够、"
        "确实需要当时的原话（具体措辞、细节）时调用；参数是梗概行尾的 #note_ 编号。"
        "梗概已经够用时不要调用。"
    )
    short_description = "展开梗概对应的原话（梗概不够时才用）"
    args_schema = ExpandMemoryInput
    category = "memory"
    enabled_by_default = True

    async def _run(self, note_id: str, max_chars: int = DEFAULT_MAX_CHARS) -> str:
        user_id = self._get_ctx("user_id")
        if not user_id:
            return "Error: 缺少 user_id，无法展开。"
        return await asyncio.to_thread(
            expand_note,
            str(user_id),
            note_id,
            request_scope=self._get_ctx("scope", "sfw"),
            max_chars=max_chars,
        )


__all__ = ["ExpandMemoryTool", "expand_note", "find_note", "note_ref_suffix", "short_note_ref"]
