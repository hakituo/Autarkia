"""统一读取上下文与可见性谓词（v3 E1）。

五段硬过滤，顺序固定，任何一段失败都不进入向量/BM25/图候选：

1. namespace / ACL
2. perspective（归谁的第一人称视角）
3. continuity（叙事连续性）
4. ``anchors_by_tree`` 祖先路径（逐来源 tree 验证）
5. as-of（系统收录时间）

``namespace_shared`` 只豁免派生 note 本身，展开其 source refs 时重新走完整路径；
这条规则写在 ``note_visibility_reason`` 里，不允许调用方自行放宽。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional

from .events import (
    TOPOLOGY_COMPLETE,
    TOPOLOGY_UNKNOWN,
    VISIBILITY_CONTINUITY_LOCAL,
    VISIBILITY_LEGACY_UNKNOWN,
    VISIBILITY_NAMESPACE_SHARED,
    VISIBILITY_TREE_LOCAL,
    NormalizedEvent,
)
from .tree import TreeBuildResult

MODE_STRICT = "strict"
MODE_COMPAT = "compat"

_KNOWN_VISIBILITIES = frozenset(
    {
        VISIBILITY_TREE_LOCAL,
        VISIBILITY_CONTINUITY_LOCAL,
        VISIBILITY_NAMESPACE_SHARED,
        VISIBILITY_LEGACY_UNKNOWN,
    }
)


@dataclass(frozen=True)
class MemoryReadContext:
    namespace: str = ""
    perspective_role: str = ""
    continuity_id: str = ""
    anchors_by_tree: Mapping[str, str] = field(default_factory=dict)
    as_of: Optional[float] = None
    mode: str = MODE_STRICT
    allowed_trees: frozenset = frozenset()

    @property
    def strict(self) -> bool:
        return self.mode == MODE_STRICT


def build_read_context(
    *,
    namespace: str = "",
    perspective_role: str = "",
    continuity_id: str = "",
    anchors_by_tree: Optional[Mapping[str, Optional[str]]] = None,
    as_of: Optional[float] = None,
    mode: str = MODE_STRICT,
    allowed_trees: Iterable[str] = (),
) -> MemoryReadContext:
    anchors = {
        str(tree_id).strip(): str(node_id).strip()
        for tree_id, node_id in (anchors_by_tree or {}).items()
        if str(tree_id).strip() and str(node_id or "").strip()
    }
    trees = frozenset(str(item).strip() for item in allowed_trees if str(item).strip())
    return MemoryReadContext(
        namespace=str(namespace or "").strip().lower(),
        perspective_role=str(perspective_role or "").strip().lower(),
        continuity_id=str(continuity_id or "").strip(),
        anchors_by_tree=anchors,
        as_of=as_of,
        mode=MODE_STRICT if mode == MODE_STRICT else MODE_COMPAT,
        allowed_trees=trees or frozenset(anchors),
    )


def _event_tree_id(event: NormalizedEvent, trees: Mapping[str, TreeBuildResult]) -> str:
    if event.tree_id:
        return event.tree_id
    if not event.client_node_id:
        return ""
    matched = [
        tree_id
        for tree_id, tree in trees.items()
        if event.client_node_id in tree.nodes
    ]
    return matched[0] if len(matched) == 1 else ""


def event_visibility_reason(
    ctx: MemoryReadContext,
    event: NormalizedEvent,
    trees: Mapping[str, TreeBuildResult],
) -> Optional[str]:
    """返回不可见原因；``None`` 表示通过硬过滤。"""
    if ctx.namespace and event.namespace and event.namespace.lower() != ctx.namespace:
        return "namespace_mismatch"
    if ctx.perspective_role and event.perspective_role:
        if event.perspective_role.lower() != ctx.perspective_role:
            return "perspective_mismatch"
    if ctx.as_of is not None and event.recorded_at > float(ctx.as_of):
        return "as_of_excluded"

    if event.topology_status == TOPOLOGY_UNKNOWN or not event.client_node_id:
        return None if not ctx.strict else "legacy_unknown"

    tree_id = _event_tree_id(event, trees)
    if not tree_id:
        return None if not ctx.strict else "tree_unresolvable"
    if ctx.allowed_trees and tree_id not in ctx.allowed_trees:
        return "tree_not_allowed"
    anchor = ctx.anchors_by_tree.get(tree_id)
    if not anchor:
        return "anchor_missing"
    tree = trees.get(tree_id)
    if tree is None:
        return "tree_unresolvable"
    node_id = event.client_node_id
    if tree.topology_status != TOPOLOGY_COMPLETE and node_id in tree.pending:
        return "topology_incomplete"
    if not tree.is_visible(node_id, anchor):
        return "not_on_anchor_path"
    return None


def _note_sources(note: Mapping[str, Any]) -> list:
    sources = note.get("source_event_ids")
    if sources is None:
        sources = (note.get("source_ref") or {}).get("event_ids")
    if isinstance(sources, str):
        return [sources]
    return [str(item) for item in (sources or []) if str(item or "").strip()]


def note_visibility_reason(
    ctx: MemoryReadContext,
    note: Mapping[str, Any],
    events_by_id: Mapping[str, NormalizedEvent],
    trees: Mapping[str, TreeBuildResult],
) -> Optional[str]:
    """派生 note 的可见性；shared 只豁免 note 自身。"""
    visibility = str(note.get("visibility") or VISIBILITY_TREE_LOCAL).strip().lower()
    if visibility not in _KNOWN_VISIBILITIES:
        return "unknown_visibility"
    note_namespace = str(note.get("namespace") or "").strip().lower()
    if ctx.namespace and note_namespace and note_namespace != ctx.namespace:
        return "namespace_mismatch"
    if ctx.perspective_role and note.get("perspective_role"):
        if str(note.get("perspective_role")).lower() != ctx.perspective_role:
            return "perspective_mismatch"
    recorded_from = note.get("recorded_from")
    if ctx.as_of is not None and recorded_from is not None:
        try:
            if float(recorded_from) > float(ctx.as_of):
                return "as_of_excluded"
        except (TypeError, ValueError):
            pass

    if visibility == VISIBILITY_LEGACY_UNKNOWN:
        return None if not ctx.strict else "legacy_unknown"
    if visibility == VISIBILITY_NAMESPACE_SHARED:
        # 只豁免 tree/continuity；source refs 展开时仍按 raw 路径复核
        return None

    if visibility == VISIBILITY_CONTINUITY_LOCAL:
        note_continuity = str(note.get("continuity_id") or "")
        if ctx.continuity_id and note_continuity and note_continuity != ctx.continuity_id:
            return "continuity_mismatch"

    sources = _note_sources(note)
    if not sources:
        return "source_unresolvable"
    for event_id in sources:
        event = events_by_id.get(event_id)
        if event is None:
            if ctx.strict:
                return "source_unresolvable"
            continue
        reason = event_visibility_reason(ctx, event, trees)
        if reason is not None:
            return f"source_{reason}"
    return None


def filter_visible_events(
    ctx: MemoryReadContext,
    events: Iterable[NormalizedEvent],
    trees: Mapping[str, TreeBuildResult],
) -> list:
    return [event for event in events if event_visibility_reason(ctx, event, trees) is None]


def filter_visible_notes(
    ctx: MemoryReadContext,
    notes: Iterable[Mapping[str, Any]],
    events_by_id: Mapping[str, NormalizedEvent],
    trees: Mapping[str, TreeBuildResult],
) -> list:
    return [
        note
        for note in notes
        if note_visibility_reason(ctx, note, events_by_id, trees) is None
    ]


__all__ = [
    "MODE_COMPAT",
    "MODE_STRICT",
    "MemoryReadContext",
    "build_read_context",
    "event_visibility_reason",
    "filter_visible_events",
    "filter_visible_notes",
    "note_visibility_reason",
]
