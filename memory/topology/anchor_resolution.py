"""读闸门的 anchor 解析：显式请求 anchor → 活跃路径最深节点 → 持久化游标（v3 E2 / E10）。

持久化游标必须落在父链连到真根的节点上，孤立链上的游标不用（见 ``_persisted_cursor``）。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional

from .tree import TreeBuildResult


def resolve_gate_anchors(
    trees: Mapping[str, TreeBuildResult],
    *,
    conversation_id: str,
    branch_scope: Optional[Mapping[str, Any]],
) -> Dict[str, str]:
    """显式请求 anchor 优先，其次由活跃路径 ID 选出最深节点，最后是持久化游标。"""
    explicit = _context_anchors()
    anchors: Dict[str, str] = {}
    allowed_ids = {
        str(item).strip()
        for item in ((branch_scope or {}).get("allowed_message_ids") or ())
        if str(item).strip()
    }
    for tree_id, tree in trees.items():
        anchor = str(explicit.get(tree_id) or "").strip()
        if anchor:
            anchors[tree_id] = anchor
            continue
        if conversation_id and tree.conversation_id == conversation_id and allowed_ids:
            deepest = _deepest_node(tree, allowed_ids)
            if deepest:
                anchors[tree_id] = deepest
                continue
        cursor = _persisted_cursor(tree)
        if cursor:
            anchors[tree_id] = cursor  # 没有请求路径时退到该会话的持久化游标（E10）
    return anchors


def _persisted_cursor(tree: TreeBuildResult) -> str:
    """持久化游标，但只认父链连到真根的节点。

    游标停在孤立链上（parent 没到的待定节点下面）时，拿它当 anchor 会把整段主线
    判成 ``not_on_anchor_path``；退到覆盖层的激活Ye，再不行就不给 anchor（compat 放行）。
    """
    try:
        from .cursors import cursor_for, overlay_leaf

        for candidate in (cursor_for(tree.conversation_id), overlay_leaf(tree.conversation_id)):
            if candidate and candidate in tree.nodes and tree.is_grounded(candidate):
                return candidate
    except Exception:  # noqa: BLE001
        return ""
    return ""


def _context_anchors() -> Dict[str, str]:
    try:
        from .anchors import get_request_anchors

        return get_request_anchors() or {}
    except Exception:  # noqa: BLE001
        return {}


def _deepest_node(tree: TreeBuildResult, allowed_ids: Iterable[str]) -> str:
    best = ""
    best_depth = -1
    for node_id in allowed_ids:
        if node_id not in tree.nodes:
            continue
        depth = len(tree.ancestors(node_id))
        if depth > best_depth:
            best = node_id
            best_depth = depth
    return best


__all__ = ["resolve_gate_anchors"]
