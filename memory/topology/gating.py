"""内容门控（v3 D3）：哪些正文可以进提炼，与拓扑保留完全解耦。

原则：空白 / 媒体占位 / debug / 系统调度 / 内心独白都可以 ``content_eligible=false``，
但事件本身与父链必须保留——提炼过滤永远不允许砍断世界线。
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional

#: 结构节点：保留拓扑，不进入提炼正文
TOPOLOGY_ONLY_EVENT_TYPES = frozenset({"chat_thought", "system_prompt", "scheduled_task"})

#: 纯媒体/占位标记，例如 "[图片]"、"[IMG:1]"
_MEDIA_PLACEHOLDER = re.compile(
    r"^\s*(?:\[(?:图片|照片|视频|语音|表情|文件|贴纸|IMG|BM|VOICE|FILE|STICKER)"
    r"(?:[:：][^\]]{0,32})?\]\s*)+$"
)


def content_hash(content: str) -> str:
    normalized = " ".join(str(content or "").strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def is_media_placeholder(content: str) -> bool:
    return bool(_MEDIA_PLACEHOLDER.match(str(content or "").strip()))


def is_content_eligible(content: str, *, event_type: str = "") -> bool:
    """判断内容能否进入提炼正文；不影响事件与拓扑是否保留。"""
    from core.utils.debug_markers import is_debug_context_message

    raw = str(content or "").strip()
    if not raw:
        return False
    if str(event_type or "").strip().lower() in TOPOLOGY_ONLY_EVENT_TYPES:
        return False
    if is_debug_context_message(raw):
        return False
    if is_media_placeholder(raw):
        return False
    return True


def content_gate_reason(content: str, *, event_type: str = "") -> Optional[str]:
    """不可提炼时给出原因，供审计报告分类。"""
    from core.utils.debug_markers import is_debug_context_message

    if is_content_eligible(content, event_type=event_type):
        return None
    raw = str(content or "").strip()
    if not raw:
        return "empty"
    if str(event_type or "").strip().lower() in TOPOLOGY_ONLY_EVENT_TYPES:
        return "topology_only_event_type"
    if is_debug_context_message(raw):
        return "debug_marker"
    if is_media_placeholder(raw):
        return "media_placeholder"
    return "ineligible"
