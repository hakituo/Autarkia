# -*- coding: utf-8 -*-
"""加权记忆关系图的邻域/子图视图。

关系图本体是 :mod:`memory.core.relation_graph` 的稀疏投影，本模块只做
「裁剪 + 命名」，不复制正文、不引入第二份记忆真源。共享的命名与过滤规则在
:mod:`memory.core.graph_common`，地标（锚点）视图在
:mod:`memory.core.graph_anchors`。

产物结构（与 HTTP 层一一对应）::

    {"root_id": "...", "nodes": [...], "edges": [...], "truncated": false}
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from memory.core.graph_common import (  # noqa: F401  （PREVIEW_LIMIT/relation_label 为对外兼容导出）
    MIN_EDGE_STRENGTH,
    PREVIEW_LIMIT,
    collect_edges,
    is_visible_memory,
    memory_salience,
    node_payload,
    relation_label,
)
from memory.core.lock_utils import get_read_lock
from memory.core.relation_graph import ensure_relation_graph, get_relation_cluster

MAX_NEIGHBORS = 24
MAX_GRAPH_NODES = 120
# overview 时按「权重 + 重要标记」挑几个种子，再各自展开邻域
OVERVIEW_SEED_COUNT = 6


def _empty_view(root_id: str = "") -> Dict[str, Any]:
    return {"root_id": root_id, "nodes": [], "edges": [], "truncated": False}


def build_neighbor_view(
    manager: Any,
    memory_id: str,
    *,
    limit: int = 12,
    max_depth: int = 1,
    include_thinking: bool = False,
) -> Optional[Dict[str, Any]]:
    """单条记忆的邻域视图；记忆不存在时返回 None。

    结果不含中心节点本身（前端已经有它），按「跳数 → 边强度 → 权重」排序，
    直接对应详情页的「想起…」列表。
    """
    root = str(memory_id or "").strip()
    if not root:
        return _empty_view()

    cap = max(1, min(int(limit or 12), MAX_NEIGHBORS))
    depth = max(1, min(int(max_depth or 1), 2))
    cluster = get_relation_cluster(manager, root, limit=cap + 1, max_depth=depth)
    if not cluster:
        return None

    nodes: List[Dict[str, Any]] = []
    for item in cluster:
        node_id = str(item.get("id") or "")
        if not node_id or node_id == root:
            continue
        if not is_visible_memory(item, include_thinking=include_thinking):
            continue
        context = item.get("relation_context") or {}
        nodes.append(
            node_payload(
                item,
                relation=str(context.get("relation") or ""),
                strength=float(context.get("path_strength") or 0.0),
                distance=int(context.get("graph_distance") or 1),
            )
        )

    nodes.sort(
        key=lambda item: (item["graph_distance"], -item["strength"], -item["weight"])
    )
    nodes = nodes[:cap]

    graph = ensure_relation_graph(manager)
    edges = collect_edges(graph, [root] + [item["id"] for item in nodes])
    return {
        "root_id": root,
        "nodes": nodes,
        "edges": edges,
        "truncated": len(cluster) > len(nodes) + 1,
    }


def _overview_seed_ids(manager: Any, *, include_thinking: bool, count: int) -> List[str]:
    with get_read_lock(manager):
        snapshot = [
            (str(mid), dict(memory))
            for mid, memory in manager.weighted_memories.items()
            if is_visible_memory(memory, include_thinking=include_thinking)
        ]
    snapshot.sort(key=lambda item: memory_salience(item[1]), reverse=True)
    return [memory_id for memory_id, _ in snapshot[: max(1, int(count))]]


def build_graph_view(
    manager: Any,
    *,
    seed_id: Optional[str] = None,
    limit: int = 80,
    max_depth: int = 2,
    include_thinking: bool = False,
) -> Dict[str, Any]:
    """记忆网络子图：给定种子就以它为中心，否则按显著度挑种子再合并邻域。

    放大到全量记忆不现实（手机上几千个节点既画不动也看不懂），所以这里
    始终返回「有限大小的子图」；前端换种子等于在图里走一步。
    """
    cap = max(2, min(int(limit or 80), MAX_GRAPH_NODES))
    depth = max(1, min(int(max_depth or 2), 3))
    root = str(seed_id or "").strip()

    if root:
        seeds = [root]
    else:
        seeds = _overview_seed_ids(
            manager,
            include_thinking=include_thinking,
            count=OVERVIEW_SEED_COUNT,
        )
    if not seeds:
        return _empty_view(root)

    graph = ensure_relation_graph(manager)
    with get_read_lock(manager):
        memories = {str(mid): dict(memory) for mid, memory in manager.weighted_memories.items()}

    nodes: Dict[str, Dict[str, Any]] = {}
    truncated = False
    for seed in seeds:
        memory = memories.get(seed)
        if not memory or not is_visible_memory(memory, include_thinking=include_thinking):
            continue
        if seed not in nodes:
            nodes[seed] = node_payload(
                memory,
                relation="self" if root else "topic",
                strength=1.0,
                distance=0,
            )
        if len(nodes) >= cap:
            truncated = True
            break
        cluster = get_relation_cluster(manager, seed, limit=cap, max_depth=depth)
        for item in cluster:
            node_id = str(item.get("id") or "")
            if not node_id or node_id in nodes:
                continue
            if not is_visible_memory(item, include_thinking=include_thinking):
                continue
            context = item.get("relation_context") or {}
            nodes[node_id] = node_payload(
                item,
                relation=str(context.get("relation") or ""),
                strength=float(context.get("path_strength") or 0.0),
                distance=int(context.get("graph_distance") or 1),
            )
            if len(nodes) >= cap:
                truncated = True
                break
        if truncated:
            break

    if not nodes:
        return _empty_view(root)

    ordered = sorted(
        nodes.values(),
        key=lambda item: (item["graph_distance"], -item["weight"]),
    )
    edges = collect_edges(graph, [item["id"] for item in ordered])
    return {
        "root_id": root,
        "nodes": ordered,
        "edges": edges,
        "truncated": truncated,
    }
