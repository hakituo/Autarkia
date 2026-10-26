"""客户端消息树分支元数据辅助函数。

Android 仍使用 ``history_override`` 决定本轮 LLM 看见的激活路径；本模块只承载
消息树 ID / parent / variant 关系，供 WeightedMemory 关系图使用。
分支元数据通过 ContextVar 随当前请求传播，不进入模型消息正文。
"""
from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any, Dict, Iterable, List, Optional


_MAX_ID_LENGTH = 128
_MAX_VARIANT_INDEX = 10000
_request_branch_metadata: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "xiaoyou_request_branch_metadata", default=None
)


def _clean_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text or len(text) > _MAX_ID_LENGTH:
        return ""
    return text


def _clean_non_negative_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(number, _MAX_VARIANT_INDEX))


def normalize_branch_metadata(raw: Any) -> Optional[Dict[str, Any]]:
    """校验并归一化一轮 user/assistant 的消息树关系。"""
    if not isinstance(raw, dict):
        return None

    user_message_id = _clean_id(raw.get("user_message_id"))
    assistant_message_id = _clean_id(raw.get("assistant_message_id"))
    if not user_message_id or not assistant_message_id:
        return None

    user_variant_index = _clean_non_negative_int(raw.get("user_variant_index"), 0)
    assistant_variant_index = _clean_non_negative_int(
        raw.get("assistant_variant_index"), 0
    )
    user_variant_count = max(
        user_variant_index + 1,
        _clean_non_negative_int(raw.get("user_variant_count"), 1),
        1,
    )
    assistant_variant_count = max(
        assistant_variant_index + 1,
        _clean_non_negative_int(raw.get("assistant_variant_count"), 1),
        1,
    )

    return {
        "user_message_id": user_message_id,
        "user_parent_id": _clean_id(raw.get("user_parent_id")) or None,
        "user_variant_index": user_variant_index,
        "user_variant_count": user_variant_count,
        "user_variant_of": _clean_id(raw.get("user_variant_of")) or None,
        "assistant_message_id": assistant_message_id,
        "assistant_parent_id": _clean_id(raw.get("assistant_parent_id")) or None,
        "assistant_variant_index": assistant_variant_index,
        "assistant_variant_count": assistant_variant_count,
        "assistant_variant_of": _clean_id(raw.get("assistant_variant_of")) or None,
        "branch_id": _clean_id(raw.get("branch_id")) or None,
    }


def set_request_branch_metadata(raw: Any) -> Token:
    """绑定当前请求的分支元数据；无效 payload 会显式绑定为 None。"""
    return _request_branch_metadata.set(normalize_branch_metadata(raw))


def reset_request_branch_metadata(token: Token) -> None:
    _request_branch_metadata.reset(token)


def get_request_branch_metadata() -> Optional[Dict[str, Any]]:
    value = _request_branch_metadata.get()
    return dict(value) if isinstance(value, dict) else None


def branch_metadata_for_role(
    branch_metadata: Optional[Dict[str, Any]], role: str
) -> Dict[str, Any]:
    """投影为一条 WeightedMemory 记录可直接合并的关系字段。"""
    normalized = normalize_branch_metadata(branch_metadata)
    role_key = str(role or "").strip().lower()
    if normalized is None or role_key not in {"user", "assistant"}:
        return {}

    prefix = "user" if role_key == "user" else "assistant"
    client_message_id = _clean_id(normalized.get(f"{prefix}_message_id"))
    if not client_message_id:
        return {}

    result: Dict[str, Any] = {
        "client_message_id": client_message_id,
        "variant_index": int(normalized.get(f"{prefix}_variant_index") or 0),
        "variant_count": int(normalized.get(f"{prefix}_variant_count") or 1),
    }
    parent_id = _clean_id(normalized.get(f"{prefix}_parent_id"))
    variant_of = _clean_id(normalized.get(f"{prefix}_variant_of"))
    branch_id = _clean_id(normalized.get("branch_id"))
    if parent_id:
        result["parent_id"] = parent_id
    if variant_of:
        result["variant_of"] = variant_of
    if branch_id:
        result["branch_id"] = branch_id
    return result


def request_branch_fields(role: str, turn_id: str) -> Dict[str, Any]:
    """当前请求这一轮的节点关系；不是这一轮就返回空字典。

    ``turn_id`` 用落库的 message_id 比对：只有 ``save_history`` 为当前这轮
    写入的 user/assistant 才能继承 branch context。请求期间派生出的后台任务
    即使复制了 ContextVar，也不会被误标成这条世界线。
    """
    metadata = get_request_branch_metadata()
    if not metadata:
        return {}
    expected_turn = _clean_id(metadata.get("assistant_message_id"))
    if not expected_turn or _clean_id(turn_id) != expected_turn:
        return {}
    return branch_metadata_for_role(metadata, role)


# ---------------------------------------------------------------------------
# 聊天记录检索的「当前分支可见范围」
#
# 背景：search_chat_history 是常驻工具，直接搜 ChatHistoryStore 的原始记录。
# 而后端落库是**线性**的——安卓端每次回滚 + 重新生成都会往里追加一份 exchange，
# 于是被回滚掉的分支内容也堆在同一个会话文件里（实测同一句用户输入出现 7 次）。
# history_override 只保证「本轮 LLM 的对话历史」是分支正确的；模型一调
# search_chat_history，被回滚掉的后续聊天就又回到它眼前——用户看到的就是
# 「回滚到之前的 input 重新生成，它居然看得到之后的聊天记录」。
#
# 这里把 history_override 投影成一条检索边界，随请求 ContextVar 传播：
# - allowed_message_ids：当前活跃路径上每条消息的客户端节点 ID
#   （落库事件的 message_id 就是该轮 assistant 的客户端节点 ID，正好一一对应）；
# - not_after_ts：路径最后一条消息的时间戳（秒）。晚于它、且不在路径上的
#   同会话事件，全部属于被回滚掉的分支。
# 旧历史（早于分支点）不受影响，照常可搜——否则长会话下旧往事会搜不到。
# 只有带 history_override 的请求（安卓端）才设置；QQ / Obsidian 等不受影响。
# ---------------------------------------------------------------------------
_chat_history_branch_scope: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "xiaoyou_chat_history_branch_scope", default=None
)


def set_chat_history_branch_scope(
    allowed_message_ids: Iterable[str],
    not_after_ts: Optional[float],
    conversation_id: Optional[str] = None,
) -> Token:
    """绑定本轮请求的聊天记录检索边界。

    ``not_after_ts=None`` 表示客户端没带时间戳（老版本 App），只按 ID 规则过滤，
    不搞时间兜底——否则会把长会话的旧历史一起挡掉；``0.0`` 表示显式空路径
    （从零重生成第一轮回复），本会话此前的记录全部不可见。
    ``conversation_id`` 标明边界属于哪个会话，供不带会话参数的读路径
    （加权记忆检索 / 关系图）判断「本会话」，缺省时这些读路径不套用边界。
    """
    cleaned = {str(item).strip() for item in (allowed_message_ids or ()) if str(item).strip()}
    boundary: Optional[float]
    if not_after_ts is None:
        boundary = None
    else:
        try:
            boundary = float(not_after_ts)
        except (TypeError, ValueError):
            boundary = None
    return _chat_history_branch_scope.set(
        {
            "allowed_message_ids": cleaned,
            "not_after_ts": boundary,
            "conversation_id": str(conversation_id or "").strip(),
        }
    )


def reset_chat_history_branch_scope(token: Token) -> None:
    _chat_history_branch_scope.reset(token)


def get_chat_history_branch_scope() -> Optional[Dict[str, Any]]:
    value = _chat_history_branch_scope.get()
    if not isinstance(value, dict):
        return None
    return dict(value)


def is_event_visible_in_branch(
    event: Dict[str, Any],
    *,
    conversation_id: str,
    scope: Optional[Dict[str, Any]],
) -> bool:
    """判断一条聊天记录事件在当前分支下是否可见。

    纯函数，供 search_chat_history 在合并候选后、截断前统一过滤：
    - 非本会话事件（QQ / 旧会话 / 归档）原样放行，避免误伤跨会话回忆；
    - 主动消息按墙上时钟发生，不属于任何分支内容，原样放行；
    - 本会话事件：在活跃路径上（message_id 命中）或早于分支点的旧历史放行；
    - 其余（晚于分支点且不在路径上）= 被回滚掉的分支，不可见。
    """
    if not scope:
        return True
    if not isinstance(event, dict):
        return True

    event_cid = str(event.get("conversation_id") or "").strip()
    if conversation_id and event_cid and event_cid != conversation_id:
        return True

    metadata = event.get("metadata")
    if isinstance(metadata, dict) and metadata.get("is_proactive"):
        return True

    allowed = scope.get("allowed_message_ids") or frozenset()
    message_id = str(event.get("message_id") or "").strip()
    if message_id and message_id in allowed:
        return True

    raw_boundary = scope.get("not_after_ts")
    if raw_boundary is None:
        # 没带时间戳的客户端：只按 ID 规则过滤，不误伤旧历史。
        return True
    try:
        boundary = float(raw_boundary)
    except (TypeError, ValueError):
        return True
    try:
        ts = float(event.get("timestamp") or 0.0)
    except (TypeError, ValueError):
        ts = 0.0
    return ts <= boundary


def filter_events_by_branch_scope(
    events: Iterable[Dict[str, Any]],
    *,
    conversation_id: str,
    scope: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """按当前请求的回滚边界过滤事件；没有边界时原样返回。

    多个读入口（search_chat_history / search_memory / 事件历史 / 提示词回填）
    共用这一份实现，避免各自维护一套「哪些算被回滚掉」的判断。
    """
    items = list(events)
    active = scope if scope is not None else get_chat_history_branch_scope()
    if not active:
        return items
    return [
        event
        for event in items
        if is_event_visible_in_branch(
            event, conversation_id=conversation_id, scope=active
        )
    ]
