"""议程文件路径（测试通过 monkeypatch 本模块的 ``agenda_file`` 隔离到临时目录）。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.utils.data_paths import get_active_care_dir, resolve_data_scope_from_conversation_id

AGENDA_FILENAME = "agenda.json"


def agenda_file(scope: str) -> Path:
    """``companion_data/<scope>_data/active_care/agenda.json``：每个角色一份。"""
    return get_active_care_dir(scope) / AGENDA_FILENAME


def scope_for_conversation(conversation_id: Optional[str]) -> str:
    """会话 ID → 角色数据 scope。

    议程按角色存而不是按会话存：主动消息从 QQ 发出、用户在 App 回复时，
    两边会话 ID 不同（``shared__persona__core_aveline`` / ``web_role_aveline``），
    但都解析到同一个 scope。
    """
    return resolve_data_scope_from_conversation_id(conversation_id, default="aveline")


#: 不注入议程的会话：群聊、角色互聊；后台车道只在会话 ID 中段出现
_EXCLUDED_SESSION_PREFIXES = ("group_", "peer_", "telegram_group_")
_EXCLUDED_LANE_TOKENS = ("__circle__", "__bg__")


def is_agenda_conversation(conversation_id: Optional[str]) -> bool:
    """这个会话是不是主人和角色的私聊（议程只在私聊里带）。

    议程按角色存，同一角色的群聊、和室友的互聊也会解析到同一 scope，
    不排除就会在群里或互聊里提主人的事。
    """
    lowered = str(conversation_id or "").strip().lower()
    if not lowered:
        return False
    session_part = lowered.split("__", 1)[0]
    if session_part.startswith(_EXCLUDED_SESSION_PREFIXES):
        return False
    return not any(token in lowered for token in _EXCLUDED_LANE_TOKENS)


__all__ = ["AGENDA_FILENAME", "agenda_file", "is_agenda_conversation", "scope_for_conversation"]
