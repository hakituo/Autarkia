"""悬空 parent 的补挂：parent 一直没到的待定节点在建树结果里找挂点（v3 E10 修复）。

只作用于 ``TreeBuilder.build()`` 的结果副本，不改写 builder 状态；结果只由事件集
与嫁接记录决定，与到达顺序无关。真正的 parent 一到，``add`` 会照常挂上去，
这里就不再介入。

1. ``segment_alias``：Android 把一条多句回复拆成 ``X``、``X-1``、``X-2`` 多个气泡，
   服务端只有 ``X``；下一句用户消息的 parent 是最后一个气泡 → 归到 assistant 节点 ``X``。
2. ``cursor_graft``：游标保护记下的嫁接（孤立链根 → 当时的游标），见 ``cursors.py``。
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Dict, Mapping

if TYPE_CHECKING:
    from .tree import TreeNode

INFER_SEGMENT = "segment_alias"
INFER_GRAFT = "cursor_graft"

_SEGMENT_SUFFIX = re.compile(r"^(?P<base>.+)-(?P<index>\d{1,3})$")


def resolve_dangling(
    nodes: Dict[str, TreeNode],
    pending: Mapping[str, Any],
    grafts: Mapping[str, str],
) -> Dict[str, str]:
    """``pending``：待定节点 → 其事件；就地替换 ``nodes`` 里补挂的节点，返回 节点 → 原因码。"""
    inferred: Dict[str, str] = {}
    for node_id in sorted(pending):
        parent = str(getattr(pending[node_id], "parent_node_id", "") or "")
        if not parent or node_id not in nodes:
            continue
        target, code = segment_base(nodes, parent), INFER_SEGMENT
        if not target:
            target, code = str(grafts.get(node_id) or ""), INFER_GRAFT
        if not target or target not in nodes or _reaches(nodes, target, node_id):
            continue
        nodes[node_id] = replace(nodes[node_id], parent_id=target)
        inferred[node_id] = code
    return inferred


def segment_base(nodes: Mapping[str, TreeNode], parent_id: str) -> str:
    """``X-<序号>`` 且 ``X`` 是树里的 assistant 节点 → ``X``；否则空串。"""
    match = _SEGMENT_SUFFIX.match(str(parent_id or ""))
    if not match:
        return ""
    base = nodes.get(match.group("base"))
    return base.node_id if base is not None and "assistant" in base.speaker_roles else ""


def _reaches(nodes: Mapping[str, TreeNode], start: str, target: str) -> bool:
    """从 ``start`` 沿 parent 往上能否走到 ``target``（防止补挂成环）。"""
    seen: set[str] = set()
    current = start
    while current and current not in seen:
        if current == target:
            return True
        seen.add(current)
        node = nodes.get(current)
        current = node.parent_id if node is not None else ""
    return False


__all__ = ["INFER_GRAFT", "INFER_SEGMENT", "resolve_dangling", "segment_base"]
