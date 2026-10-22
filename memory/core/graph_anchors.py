# -*- coding: utf-8 -*-
"""加权记忆的地标（anchor）视图。

全量关系图在手机上既画不动也看不懂，所以先给一层「地标」：把记忆按
「同一天 × 同一话题」压成若干片段，取片段里最显著的一条当代表，点击后
再用 :func:`memory.core.graph_view.build_graph_view` 展开它的邻域。

地标不是新的记忆真源：id 始终指向真实加权记忆，成员数量与总权重只是聚合结果，
换了算法也不影响数据本身。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

from core.utils.time.time_utils import ts_to_str
from memory.core.graph_common import is_visible_memory, memory_salience, node_payload, preview_text
from memory.core.lock_utils import get_read_lock

MAX_ANCHORS = 16
DEFAULT_ANCHOR_LIMIT = 12
ANCHOR_PREVIEW_LIMIT = 60

TOPIC_LABELS: Dict[str, str] = {
    "daily": "日常",
    "learning": "学习",
    "work": "工作",
    "festival": "节日",
    "health": "健康",
    "profile": "画像",
    "entertainment": "娱乐",
    "finance": "财务",
    "tech": "技术",
    "emotion": "情绪",
    "relationship": "关系",
    "sensitive": "私密",
    "preference": "偏好",
    "state": "状态",
    "task": "任务",
    "thinking": "思考",
    "uncategorized": "未分类",
}

# topics 里混入的结构词不参与地标命名
_GENERIC_TOPICS = frozenset(
    {"chat", "dialogue", "general", "other", "其他", "uncategorized", "event"}
)


def _day_key(memory: Dict[str, Any]) -> str:
    """记忆归属的日期：优先用 created_at 的日期部分，缺失时按时间戳换算。"""
    created = str(memory.get("created_at") or "").strip()
    if len(created) >= 10 and created[4] == "-" and created[7] == "-":
        return created[:10]
    try:
        timestamp = float(memory.get("timestamp") or 0.0)
    except (TypeError, ValueError):
        return ""
    return ts_to_str(timestamp, "%Y-%m-%d") if timestamp > 0 else ""


def _primary_topic(memory: Dict[str, Any]) -> str:
    for topic in memory.get("topics") or []:
        key = str(topic).strip().lower()
        if key and key not in _GENERIC_TOPICS:
            return key
    return str(memory.get("category") or "").strip().lower()


def _topic_label(topic: str) -> str:
    return TOPIC_LABELS.get(topic, topic or "未分类")


def _day_label(day: str) -> str:
    parts = str(day or "").split("-")
    if len(parts) != 3:
        return ""
    try:
        return f"{int(parts[1])}月{int(parts[2])}日"
    except ValueError:
        return ""


def _anchor_title(day: str, topic: str) -> str:
    """地标名：日期为主，话题只在有信息量时才拼上去。

    大量历史记忆的 topics 是空的、category 是 uncategorized，拼出
    「10月14日 · 未分类」只会更吵，不如只留日期。
    """
    day_text = _day_label(day)
    topic_text = "" if topic in {"", "uncategorized", "unknown", "thinking"} else _topic_label(topic)
    return " · ".join(part for part in (day_text, topic_text) if part) or "未命名的片段"


def build_anchor_view(
    manager: Any,
    *,
    limit: int = DEFAULT_ANCHOR_LIMIT,
    include_thinking: bool = False,
) -> List[Dict[str, Any]]:
    """返回按聚合权重降序排列的地标列表（最多 ``MAX_ANCHORS`` 条）。"""
    cap = max(1, min(int(limit or DEFAULT_ANCHOR_LIMIT), MAX_ANCHORS))
    with get_read_lock(manager):
        snapshot = [
            (str(mid), dict(memory))
            for mid, memory in manager.weighted_memories.items()
            if is_visible_memory(memory, include_thinking=include_thinking)
        ]
    if not snapshot:
        return []

    buckets: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for memory_id, memory in snapshot:
        memory["id"] = str(memory.get("id") or memory_id)
        buckets[(_primary_topic(memory), _day_key(memory) or "unknown")].append(memory)

    anchors: List[Dict[str, Any]] = []
    for (topic, day), members in buckets.items():
        members.sort(
            key=lambda item: (
                memory_salience(item),
                float(item.get("timestamp") or 0.0),
            ),
            reverse=True,
        )
        representative = members[0]
        item = node_payload(representative, relation="anchor", strength=1.0, distance=0)
        item["weight"] = round(
            sum(float(member.get("weight") or 0.0) for member in members), 3
        )
        item["member_count"] = len(members)
        item["title"] = _anchor_title(day, topic)
        item["preview"] = preview_text(representative, ANCHOR_PREVIEW_LIMIT)
        anchors.append(item)

    anchors.sort(key=lambda item: (-item["weight"], -item["member_count"], item["id"]))
    return anchors[:cap]
