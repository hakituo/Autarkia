import asyncio
import re
from typing import Any, Dict, List, Optional, Tuple

from core.services.chat_history_store import get_chat_history_store
from core.utils.logger import get_logger
from memory.core.lock_utils import get_read_lock

logger = get_logger("MemoryHistoryOps")


def _apply_read_guards(
    items: List[Dict[str, Any]], conversation_id: str
) -> List[Dict[str, Any]]:
    """所有原始事件读路径共用的分支边界 + 世界线闸门（v3 E2）。"""
    try:
        from core.agents.chat_agent_components.message_branch import (
            filter_events_by_branch_scope,
        )
        from memory.topology.read_gate import filter_raw_events

        items = filter_events_by_branch_scope(
            items, conversation_id=conversation_id
        )
        # 不传 tree_reader：走按会话常驻、随写入增量更新的消息树
        return filter_raw_events(items, conversation_id=conversation_id).events
    except Exception as exc:  # noqa: BLE001 - 过滤故障不得清空历史
        logger.warning(f"事件历史可见性过滤失败，按原样返回: {exc}")
        return items


async def get_recent_history(
    manager: Any,
    *,
    session_id: Optional[str] = None,
    limit: int = 100,
    allowed_categories: Optional[List[str]] = None,
    before: Optional[float] = None,
) -> List[Dict[str, Any]]:
    with get_read_lock(manager):
        all_memory = manager.short_term_memory + list(manager.weighted_memories.values())
        unique_memory = {m["id"]: m for m in all_memory}
        sorted_memory = sorted(unique_memory.values(), key=lambda x: x.get("timestamp", 0))

        result = []
        for msg in sorted_memory:
            if not msg.get("content"):
                continue
            if allowed_categories is not None:
                msg_category = msg.get("category")
                effective_category = msg_category if msg_category else "chat"
                if (
                    effective_category != "global_fact"
                    and effective_category not in allowed_categories
                ):
                    continue

            entry = {
                "role": msg.get("role") or msg.get("source", "assistant"),
                "content": msg.get("content", ""),
                "timestamp": msg.get("timestamp", 0),
                "id": msg.get("id", ""),
                "is_important": msg.get("is_important", False),
                "category": msg.get("category"),
            }
            meta = msg.get("metadata")
            if isinstance(meta, dict) and meta:
                for k in (
                    "image_url",
                    "image_base64",
                    "image_path",
                    "audio_base64",
                    "audio_path",
                    "voice_id",
                    "message_type",
                    "image_prompt",
                ):
                    if k in meta:
                        entry[k] = meta.get(k)
            result.append(entry)

        deduped: List[Dict[str, Any]] = []
        last_seen_ts: Dict[tuple, float] = {}
        for entry in result:
            role = entry.get("role")
            content = entry.get("content")
            ts = float(entry.get("timestamp", 0) or 0)
            key = (role, content)
            prev_ts = last_seen_ts.get(key)
            if prev_ts is not None and abs(ts - prev_ts) <= 8.0:
                continue
            deduped.append(entry)
            last_seen_ts[key] = ts
        result = deduped

        if before is not None:
            result = [
                entry for entry in result if float(entry.get("timestamp", 0) or 0) < before
            ]
        if len(result) > limit:
            return result[-limit:]
        return result


async def get_event_history(
    manager: Any,
    *,
    conversation_id: Optional[str] = None,
    limit: int = 100,
    before: Optional[float] = None,
    query: Optional[str] = None,
    roles: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    target_conversation_id = str(
        conversation_id or getattr(manager, "user_id", "default") or "default"
    ).strip() or "default"
    store = get_chat_history_store()
    items = store.list_conversation_events(
        target_conversation_id,
        limit=limit,
        before=before,
        query=query,
        roles=roles,
    )
    items = await asyncio.to_thread(
        _apply_read_guards, items, target_conversation_id
    )
    result: List[Dict[str, Any]] = []
    for item in items:
        metadata = item.get("metadata") if isinstance(item, dict) else {}
        result.append(
            {
                "event_id": str(item.get("event_id") or ""),
                "conversation_id": str(item.get("conversation_id") or target_conversation_id),
                "role": str(item.get("role") or "system"),
                "content": str(item.get("content") or ""),
                "timestamp": float(item.get("timestamp") or 0.0),
                "event_type": str(item.get("event_type") or "message"),
                "source_layer": "event_history",
                "storage_scope": str(item.get("storage_scope") or ""),
                "metadata": metadata if isinstance(metadata, dict) else {},
            }
        )
    return result


#: 主动消息把心想嵌在正文开头的形态：``（心想：…）\n\n正文``
_INLINE_THOUGHT_RE = re.compile(
    r"^\s*[（(]\s*心想\s*[:：]?\s*(?P<thought>.*?)\s*[）)]\s*", re.DOTALL
)
#: 【历史摘要】不是对话条目，聊天记录里不展示
_SUMMARY_PREFIX = "【历史摘要】"
#: 普通聊天的心想以独立事件落盘（role=system），与对话事件共享 message_id
_THOUGHT_EVENT_TYPE = "chat_thought"
#: 聊天记录只保留真正的对话角色
_DIALOGUE_ROLES = ("user", "assistant")
#: 一轮普通对话落盘的事件数（user + assistant + 心想），用于把「记录条数」换算成事件取数
_EVENTS_PER_TURN = 3
#: 对话条目允许透传的媒体字段（与 get_recent_history 对齐）
_MEDIA_KEYS = (
    "image_url",
    "image_base64",
    "image_path",
    "video_url",
    "audio_base64",
    "audio_path",
)


def _split_inline_thought(content: Any) -> Tuple[str, Optional[str]]:
    """把正文开头的「（心想：…）」抠出来；返回 (去前缀正文，心想或 None)。"""
    text = str(content or "")
    match = _INLINE_THOUGHT_RE.match(text)
    if match is None:
        return text, None
    thought = (match.group("thought") or "").strip()
    return text[match.end() :].strip(), (thought or None)


async def get_conversation_records(
    *,
    conversation_id: str,
    limit: int = 300,
    before: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """真实聊天记录（事件流），供客户端聊天记录树还原世界线。

    与 :func:`get_event_history` 的区别：结果只保留真正的对话条目
    （``role=user/assistant``），并把心想归一化成统一的 ``thought`` 字段：

    - 普通聊天的心想是独立事件（``role=system`` + ``event_type=chat_thought``），
      与对话事件共享 ``message_id``，这里按 ``message_id`` 关联到 assistant 条目；
    - 主动消息的心想嵌在正文开头，这里抠掉前缀放入 ``thought``；
    - ``【历史摘要】`` 开头的内容不是对话，直接丢弃。

    返回条目按时间升序（与 ``/history`` 一致）；``limit`` 是**聊天记录条数**，
    内部按 :data:`_EVENTS_PER_TURN` 放大成事件取数后再过滤，因此心想 / system
    事件不会挤占条数。若某条心想事件的对话配对刚好落在取数窗口之外，则该条不带心想。
    """
    target_conversation_id = str(conversation_id or "").strip() or "default"
    record_limit = max(int(limit), 1)
    store = get_chat_history_store()
    items = store.list_conversation_events(
        target_conversation_id,
        limit=record_limit * _EVENTS_PER_TURN,
        before=before,
    )
    items = await asyncio.to_thread(
        _apply_read_guards, items, target_conversation_id
    )

    thoughts_by_message_id: Dict[str, str] = {}
    dialogue: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        event_type = str(item.get("event_type") or "").strip().lower()
        role = str(item.get("role") or "system").strip().lower()
        if event_type == _THOUGHT_EVENT_TYPE:
            message_id = str(item.get("message_id") or "").strip()
            thought_text = str(item.get("content") or "").strip()
            if message_id and thought_text:
                thoughts_by_message_id[message_id] = thought_text
            continue
        if role not in _DIALOGUE_ROLES:
            continue
        dialogue.append(item)

    records: List[Dict[str, Any]] = []
    for item in dialogue:
        role = str(item.get("role") or "assistant").strip().lower()
        content, inline_thought = _split_inline_thought(item.get("content"))
        content = content.strip()
        if content.startswith(_SUMMARY_PREFIX):
            continue

        thought = inline_thought
        if thought is None and role == "assistant":
            # user / assistant 共享同一 message_id，心想只挂在 assistant 一侧
            thought = thoughts_by_message_id.get(
                str(item.get("message_id") or "").strip()
            )
        if not content and not thought:
            continue

        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        entry: Dict[str, Any] = {
            "id": str(item.get("event_id") or ""),
            "role": role,
            "content": content,
            "timestamp": float(item.get("timestamp") or 0.0),
            "message_type": str(metadata.get("message_type") or "text"),
        }
        if thought:
            entry["thought"] = thought
        for key in _MEDIA_KEYS:
            if metadata.get(key):
                entry[key] = metadata.get(key)
        records.append(entry)
    if len(records) > record_limit:
        return records[-record_limit:]
    return records
