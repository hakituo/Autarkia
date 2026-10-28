"""按段提取的会话跳过名单（探针 / 系统问候等零信息量会话）。

这些 cid 认不出角色，落盘时被 ``resolve_data_scope_from_conversation_id`` 兜底进角色聊天目录，
于是夜间按段提取会把每一次探针当成独立一段去调模型：必然 ``no_reusable_info``，还挤占
「每角色每晚 N 段」的预算。名单在 ``DEFAULT_NIGHTLY_CONFIG["segment_skip_conversations"]``，
可用 ``segment_skip_conversations`` 覆盖，传空列表即关闭跳过。

支持 ``fnmatch`` 通配（大小写不敏感），例如 ``tg_*`` 一次挡掉所有 Telegram 散会话。
"""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable

__all__ = ["default_skip_patterns", "is_skipped_conversation"]


def is_skipped_conversation(conversation_id: str, patterns: Iterable[str]) -> bool:
    """会话是否命中跳过名单；空名单 / 空 cid 一律不跳过。"""
    cid = str(conversation_id or "").strip().lower()
    if not cid:
        return False
    return any(
        fnmatch.fnmatchcase(cid, str(pattern).strip().lower())
        for pattern in patterns or ()
        if str(pattern).strip()
    )


def default_skip_patterns() -> tuple[str, ...]:
    """未显式传名单时取 nightly 默认值（探针 / 系统问候 / 单条主动推送）。"""
    from ..config import DEFAULT_NIGHTLY_CONFIG

    return tuple(DEFAULT_NIGHTLY_CONFIG.get("segment_skip_conversations") or ())
