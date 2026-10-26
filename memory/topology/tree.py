"""确定性消息树：同一事件集无论到达顺序都能重建同一棵树（v3 D6）。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .dangling import resolve_dangling
from .events import (
    TOPOLOGY_COMPLETE,
    TOPOLOGY_PARTIAL,
    TOPOLOGY_UNKNOWN,
    NormalizedEvent,
)

ADDED = "added"
DUPLICATE = "duplicate"
PENDING = "pending"
REJECTED = "rejected"


@dataclass
class TreeNode:
    node_id: str
    parent_id: str = ""
    variant_of: str = ""
    event_ids: List[str] = field(default_factory=list)
    turn_ids: List[str] = field(default_factory=list)
    speaker_roles: List[str] = field(default_factory=list)
    content_eligible: bool = False
    occurred_at: float = 0.0


@dataclass
class TreeBuildResult:
    tree_id: str
    conversation_id: str = ""
    nodes: Dict[str, TreeNode] = field(default_factory=dict)
    roots: List[str] = field(default_factory=list)
    pending: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    unknown_event_ids: List[str] = field(default_factory=list)
    topology_status: str = TOPOLOGY_COMPLETE
    reasons: List[str] = field(default_factory=list)
    #: 原本悬空、在 build 时补挂的节点 → 原因码（见 dangling.py）
    inferred_parents: Dict[str, str] = field(default_factory=dict)

    # ---- 路径查询 -------------------------------------------------------
    def ancestors(self, node_id: str, *, include_self: bool = True) -> List[str]:
        """从根到该节点的路径；遇到断链/环立即停止（fail-closed）。"""
        chain: List[str] = []
        seen: set[str] = set()
        current = node_id if include_self else self.nodes.get(node_id, TreeNode(node_id)).parent_id
        while current:
            if current in seen:
                break
            seen.add(current)
            node = self.nodes.get(current)
            if node is None:
                break
            chain.append(current)
            current = node.parent_id
        chain.reverse()
        return chain

    def is_visible(self, node_id: str, anchor_id: str) -> bool:
        """anchor 路径上的节点才可见；未知 anchor 一律不可见。"""
        if not anchor_id or anchor_id not in self.nodes:
            return False
        if node_id not in self.nodes:
            return False
        path = self.ancestors(anchor_id)
        if not path or path[-1] != anchor_id:
            # anchor 自身断链（parent 缺失）→ 只信到断点为止
            return node_id in path
        return node_id in path

    def is_grounded(self, node_id: str) -> bool:
        """节点的父链能走到真正的根（而不是停在一个 parent 还没到的待定节点上）。"""
        chain = self.ancestors(node_id)
        if not chain or chain[-1] != node_id:
            return False
        return chain[0] not in set(self.pending)

    def visible_event_ids(self, anchor_id: str) -> set[str]:
        visible: set[str] = set()
        for node_id in self.ancestors(anchor_id):
            node = self.nodes.get(node_id)
            if node is not None:
                visible.update(node.event_ids)
        return visible

    def path_event_ids(self, anchor_id: str, *, eligible_only: bool = False) -> List[str]:
        """按路径顺序返回事件 ID，供分段与提炼使用。"""
        result: List[str] = []
        for node_id in self.ancestors(anchor_id):
            node = self.nodes.get(node_id)
            if node is None:
                continue
            if eligible_only and not node.content_eligible:
                continue
            result.extend(node.event_ids)
        return result

    # ---- 审计 -----------------------------------------------------------
    def canonical_hash(self) -> str:
        """规范哈希：只由图结构决定，与输入顺序、事件到达时间无关。"""
        payload = [
            {
                "node_id": node.node_id,
                "parent_id": node.parent_id,
                "variant_of": node.variant_of,
                "event_ids": sorted(node.event_ids),
            }
            for node in sorted(self.nodes.values(), key=lambda item: item.node_id)
        ]
        blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def to_report(self) -> Dict[str, Any]:
        return {
            "tree_id": self.tree_id,
            "conversation_id": self.conversation_id,
            "node_count": len(self.nodes),
            "root_count": len(self.roots),
            "pending_count": len(self.pending),
            "conflict_count": len(self.conflicts),
            "unknown_event_count": len(self.unknown_event_ids),
            "inferred_parent_count": len(self.inferred_parents),
            "topology_status": self.topology_status,
            "reasons": list(self.reasons),
            "canonical_hash": self.canonical_hash(),
        }


class TreeBuilder:
    """增量建树；``build()`` 幂等，可对同一事件集重复调用。"""

    def __init__(self, *, tree_id: str = "", conversation_id: str = "") -> None:
        self.tree_id = tree_id
        self.conversation_id = conversation_id
        self._nodes: Dict[str, TreeNode] = {}
        self._pending: Dict[str, NormalizedEvent] = {}
        self._conflicts: List[str] = []
        self._unknown_event_ids: List[str] = []
        self._seen_event_ids: set[str] = set()
        self._seen_keys: set[str] = set()
        self._reasons: List[str] = []

    # ---- 写入 -----------------------------------------------------------
    def add(self, event: NormalizedEvent) -> str:
        event_id = event.event_id or event.idempotency_key
        node_id = event.client_node_id
        if not node_id:
            if event_id not in self._seen_event_ids:
                self._seen_event_ids.add(event_id)
                self._unknown_event_ids.append(event_id)
                self._reasons.append(f"event {event_id} 缺客户端节点 ID，拓扑未知")
            return REJECTED
        if event.event_id and event.event_id in self._seen_event_ids:
            return DUPLICATE
        if event.idempotency_key and event.idempotency_key in self._seen_keys:
            return DUPLICATE
        if event.event_id:
            self._seen_event_ids.add(event.event_id)
        if event.idempotency_key:
            self._seen_keys.add(event.idempotency_key)

        node = self._nodes.get(node_id)
        if node is None:
            node = TreeNode(node_id=node_id, occurred_at=event.occurred_at)
            self._nodes[node_id] = node
        node.event_ids.append(event.event_id or event.idempotency_key)
        if event.turn_id and event.turn_id not in node.turn_ids:
            node.turn_ids.append(event.turn_id)
        if event.speaker_role and event.speaker_role not in node.speaker_roles:
            node.speaker_roles.append(event.speaker_role)
        node.content_eligible = node.content_eligible or event.content_eligible
        node.occurred_at = node.occurred_at or event.occurred_at

        parent_id = event.parent_node_id
        variant_of = event.variant_of_node_id
        if variant_of:
            old = self._nodes.get(variant_of)
            if old is None:
                if not parent_id:
                    # 既没 parent 又找不到旧版本：只能等旧版本到达后继承它的 parent
                    self._pending[node_id] = event
                    return PENDING
                # 有 parent 就直接挂：分支关系由 parent 决定，variant_of 只是提示。
                # 旧版本可能永远不会到（手机上改写过、或首次发送失败），不能为它
                # 把整段后续对话挂起（2026-10-26 线上 web_role_lin 实例）。
                node.variant_of = variant_of
                old = None
            elif parent_id and old.parent_id and parent_id != old.parent_id:
                self._conflicts.append(
                    f"node {node_id} parent={parent_id} 与旧版本 {variant_of} "
                    f"parent={old.parent_id} 不一致"
                )
            if old is not None:
                parent_id = parent_id or old.parent_id
                node.variant_of = variant_of

        if parent_id and parent_id not in self._nodes and parent_id != node_id:
            self._pending[node_id] = event
            return PENDING

        node.parent_id = parent_id
        self._pending.pop(node_id, None)
        self._drain_pending()
        return ADDED

    def _drain_pending(self) -> None:
        """child-before-parent：父节点到达后按稳定顺序重放。"""
        progressed = True
        while progressed:
            progressed = False
            for node_id in sorted(
                self._pending,
                key=lambda key: (self._pending[key].occurred_at, key),
            ):
                event = self._pending[node_id]
                old = self._nodes.get(event.variant_of_node_id) if event.variant_of_node_id else None
                parent_id = event.parent_node_id or (old.parent_id if old else "")
                if parent_id and parent_id not in self._nodes:
                    continue
                node = self._nodes.get(node_id)
                if node is None:
                    continue
                node.parent_id = parent_id
                if old is not None:
                    node.variant_of = event.variant_of_node_id
                self._pending.pop(node_id, None)
                progressed = True

    # ---- 结果 -----------------------------------------------------------
    def build(self, *, grafts: Optional[Mapping[str, str]] = None) -> TreeBuildResult:
        """``grafts``：待定节点 → 补挂目标（游标保护记录的嫁接，见 cursors.py）。"""
        nodes = dict(self._nodes)
        inferred = resolve_dangling(nodes, self._pending, grafts or {})
        roots = sorted(
            (node_id for node_id, node in nodes.items() if not node.parent_id),
            key=lambda node_id: (nodes[node_id].occurred_at, node_id),
        )
        pending = sorted(node_id for node_id in self._pending if node_id not in inferred)
        for node_id in pending:
            if node_id not in self._reasons:
                parent = self._pending[node_id].parent_node_id
                self._reasons.append(f"node {node_id} 的 parent {parent or '未知'} 未到达")

        status = TOPOLOGY_COMPLETE
        if pending or self._conflicts or inferred:
            status = TOPOLOGY_PARTIAL
        elif len(roots) > 1:
            status = TOPOLOGY_PARTIAL
            self._reasons.append(f"存在 {len(roots)} 个根节点，父链不唯一")
        elif self._unknown_event_ids and not self._nodes:
            status = TOPOLOGY_UNKNOWN
        elif self._unknown_event_ids:
            status = TOPOLOGY_PARTIAL

        reasons = list(self._reasons) + [
            f"node {node_id} 的 parent 悬空，按 {code} 补挂到 {nodes[node_id].parent_id}"
            for node_id, code in sorted(inferred.items())
        ]
        tree_id = self.tree_id or compute_tree_id(self.conversation_id, roots)
        return TreeBuildResult(
            tree_id=tree_id,
            conversation_id=self.conversation_id,
            nodes=nodes,
            roots=roots,
            pending=pending,
            conflicts=list(self._conflicts),
            unknown_event_ids=list(self._unknown_event_ids),
            topology_status=status,
            reasons=list(dict.fromkeys(reasons)),
            inferred_parents=inferred,
        )


def compute_tree_id(conversation_id: str, root_node_ids: Sequence[str]) -> str:
    """tree_id 由会话与根节点决定：同一棵树重复计算得到同一 ID。"""
    basis = "|".join([str(conversation_id or ""), ",".join(sorted(root_node_ids))])
    return "tree_" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def build_tree(
    events: Iterable[NormalizedEvent],
    *,
    conversation_id: str = "",
) -> TreeBuildResult:
    """一次性建树（审计/回放用）。输入顺序不影响结果。"""
    builder = TreeBuilder(conversation_id=conversation_id)
    # 先按稳定顺序添加，减少 pending 重放次数；正确性不依赖该排序
    for event in sorted(events, key=lambda item: (item.occurred_at, item.event_id)):
        builder.add(event)
    return builder.build()
