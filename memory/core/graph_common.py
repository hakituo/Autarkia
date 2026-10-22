# -*- coding: utf-8 -*-
"""加权记忆关系视图的共享投影工具。

``relation_graph`` 给出的是「记忆 id → 边」的稀疏邻接表；本模块只做与具体视图
无关的基础转换：关系命名、预览文本、可见性过滤、单节点负载、边收集。
邻域/子图视图见 :mod:`memory.core.graph_view`，地标视图见
:mod:`memory.core.graph_anchors`。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Sequence, Set

# 边类型的中文说明：只在后端维护一份，前端直接用 relation_label，避免第二套映射
RELATION_LABELS: Dict[str, str] = {
    "self": "本条",
    "anchor": "一件事",
    "parent": "上游对话",
    "related": "手动关联",
    "event": "同一件事",
    "turn": "同一轮",
    "continuation": "接着说",
    "topic": "同一话题",
    "alternate": "改写版本",
}
RELATION_LABEL_FALLBACK = "相关记忆"

PREVIEW_LIMIT = 120
MIN_EDGE_STRENGTH = 0.35

_EXCLUDED_STATUSES = frozenset({"deleted", "superseded"})


def relation_label(relation: str) -> str:
    """边类型的中文说明；未知类型统一落到「相关记忆」。"""
    return RELATION_LABELS.get(str(relation or "").strip().lower(), RELATION_LABEL_FALLBACK)


def preview_text(memory: Dict[str, Any], limit: int = PREVIEW_LIMIT) -> str:
    """优先取原文，没有原文再退到蒸馏摘要。"""
    for field in ("content", "readable_summary", "summary", "readable_title"):
        text = str(memory.get(field) or "").strip()
        if not text:
            continue
        if len(text) > limit:
            return text[:limit].rstrip() + "…"
        return text
    return ""


def is_visible_memory(memory: Dict[str, Any], *, include_thinking: bool = False) -> bool:
    """过滤掉不该出现在视图里的记忆（隐藏分类与已删除/已替代状态）。"""
    if not isinstance(memory, dict):
        return False
    status = str(memory.get("status") or "active").strip().lower()
    if status in _EXCLUDED_STATUSES:
        return False
    if not include_thinking:
        category = str(memory.get("category") or "").strip().lower()
        if category == "thinking":
            return False
    return True


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def memory_salience(memory: Dict[str, Any]) -> float:
    """挑种子/地标用的显著度：权重 + 重要标记加成。

    只按时间衰减后的 ``weight`` 排序会让旧记忆彻底消失，所以重要性单独加一档。
    """
    return _safe_float(memory.get("weight")) + (3.0 if memory.get("is_important") else 0.0)


def node_payload(
    memory: Dict[str, Any],
    *,
    relation: str,
    strength: float,
    distance: int,
) -> Dict[str, Any]:
    """单个图节点的对外结构；字段与安卓 ``MemoryRelationDto`` 一一对应。"""
    return {
        "id": str(memory.get("id") or ""),
        "relation": str(relation or ""),
        "relation_label": relation_label(relation),
        "strength": round(_safe_float(strength), 3),
        "graph_distance": int(distance),
        "preview": preview_text(memory),
        "created_at": memory.get("created_at"),
        "timestamp": memory.get("timestamp"),
        "weight": round(_safe_float(memory.get("weight")), 3),
        "category": memory.get("category"),
        "topics": [str(item) for item in (memory.get("topics") or [])][:6],
        "emotion": memory.get("emotion"),
        "is_important": bool(memory.get("is_important")),
    }


def collect_edges(
    graph: Dict[str, Sequence[Any]],
    node_ids: Iterable[str],
    *,
    min_strength: float = MIN_EDGE_STRENGTH,
) -> List[Dict[str, Any]]:
    """只保留两端都在结果集里的边，同一条边只输出一次。"""
    ids: Set[str] = {str(item) for item in node_ids if item}
    seen: Set[tuple] = set()
    edges: List[Dict[str, Any]] = []
    for source in ids:
        for edge in graph.get(source, ()) or ():
            target = str(getattr(edge, "target_id", "") or "")
            strength = _safe_float(getattr(edge, "strength", 0.0))
            if target not in ids or target == source or strength < min_strength:
                continue
            key = (source, target) if source < target else (target, source)
            if key in seen:
                continue
            seen.add(key)
            relation = str(getattr(edge, "relation", "") or "")
            edges.append(
                {
                    "source": source,
                    "target": target,
                    "relation": relation,
                    "relation_label": relation_label(relation),
                    "strength": round(strength, 3),
                }
            )
    edges.sort(key=lambda item: (-item["strength"], item["source"], item["target"]))
    return edges
