"""生产读路径的世界线闸门（v3 E2 / E9）。

生产默认 ``compat`` 起步：历史事件几乎全是 ``topology=unknown``，strict 会
清空检索。compat 的取舍写在 ``COMPAT_PASS_REASONS``：

- ``legacy_unknown`` / ``tree_unresolvable`` / ``anchor_missing`` /
  ``topology_incomplete`` 放行，但每次放行都计入原因码；
- 一旦有明确 anchor，节点不在祖先路径上（兄弟线）仍然隐藏；
- namespace / perspective / as-of / 未被允许的 tree 永不放宽。

闸门只做纯过滤，不写任何状态；建树失败时退回放行并记 ``gate_error``，
避免拓扑故障把搜索清空。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

from .anchor_resolution import resolve_gate_anchors
from .events import normalize_event
from .read_context import (
    MODE_COMPAT,
    MODE_STRICT,
    build_read_context,
    event_visibility_reason,
)
from .tree import TreeBuildResult, build_tree

#: compat 模式下允许「带着原因码放行」的缺失型原因
COMPAT_PASS_REASONS = frozenset(
    {
        "legacy_unknown",
        "tree_unresolvable",
        "anchor_missing",
        "topology_incomplete",
    }
)

LoggerLike = Any


@dataclass
class GateOutcome:
    """过滤结果；``reasons`` 同时统计放行与隐藏的原因码。"""

    events: List[Dict[str, Any]] = field(default_factory=list)
    reasons: Dict[str, int] = field(default_factory=dict)

    @property
    def visible(self) -> int:
        return len(self.events)

    @property
    def hidden(self) -> int:
        return sum(
            count
            for reason, count in self.reasons.items()
            if not reason.startswith("compat_pass:")
        )


def filter_raw_events(
    events: Sequence[Mapping[str, Any]],
    *,
    conversation_id: str = "",
    mode: str = MODE_COMPAT,
    branch_scope: Optional[Mapping[str, Any]] = None,
    tree_reader: Optional[Callable[[str], Sequence[Mapping[str, Any]]]] = None,
    logger: Optional[LoggerLike] = None,
) -> GateOutcome:
    """按统一可见性谓词过滤原始事件，保持输入顺序。

    ``conversation_id`` 只用于把 ``branch_scope`` 的活跃路径 ID 绑到对应会话；
    其它会话的事件各自按自己的树判定，不共享这个 anchor。
    """
    raw = [dict(item) for item in events if isinstance(item, Mapping)]
    if not raw:
        return GateOutcome(events=[], reasons={})

    try:
        judged = raw
        if tree_reader is None:
            # 历史事件本身没有节点 ID：按常驻树（含覆盖层回填）补上再判定，
            # 返回给调用方的仍是原始 payload
            from .tree_registry import get_tree_registry

            judged = get_tree_registry().with_known_nodes(raw)
        normalized = [
            normalize_event(
                payload,
                storage_scope=str(payload.get("storage_scope") or ""),
                recorded_at=_as_float(payload.get("timestamp")),
            )
            for payload in judged
        ]
        node_conversations = sorted(
            {
                event.conversation_id
                for event in normalized
                if event.client_node_id
            }
        )
        trees = load_trees(node_conversations, tree_reader)
        anchors = resolve_gate_anchors(
            trees,
            conversation_id=conversation_id,
            branch_scope=branch_scope if branch_scope is not None else context_branch_scope(),
        )
        ctx = build_read_context(
            mode=mode,
            anchors_by_tree=anchors,
            allowed_trees=trees.keys(),
        )
        # 先用 strict 算出「真实原因」，再由 compat 策略决定是否放行
        strict_ctx = replace(ctx, mode=MODE_STRICT)
        visible: List[Dict[str, Any]] = []
        reasons: Counter = Counter()
        for payload, event in zip(raw, normalized):
            reason = event_visibility_reason(strict_ctx, event, trees)
            if reason is None:
                visible.append(payload)
                continue
            if mode != MODE_STRICT and reason in COMPAT_PASS_REASONS:
                visible.append(payload)
                reasons[f"compat_pass:{reason}"] += 1
                continue
            reasons[reason] += 1
        outcome = GateOutcome(events=visible, reasons=dict(sorted(reasons.items())))
        _log_outcome(outcome, conversation_id=conversation_id, mode=mode, logger=logger)
        return outcome
    except Exception as exc:  # noqa: BLE001 - 拓扑故障不得清空搜索
        _log_failure(exc, logger=logger)
        if mode == MODE_STRICT:
            return GateOutcome(events=[], reasons={"gate_error": len(raw)})
        return GateOutcome(
            events=raw,
            reasons={"compat_pass:gate_error": len(raw)},
        )


def _as_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _default_tree_reader(conversation_id: str) -> Sequence[Mapping[str, Any]]:
    from core.services.chat_history_store import get_chat_history_store

    return get_chat_history_store().list_conversation_events(
        conversation_id, limit=0
    )


def load_trees(
    conversation_ids: Iterable[str],
    tree_reader: Optional[Callable[[str], Sequence[Mapping[str, Any]]]],
) -> Dict[str, TreeBuildResult]:
    """``tree_reader=None`` 走按会话常驻、随写入增量更新的树（不再现场全量读）。"""
    trees: Dict[str, TreeBuildResult] = {}
    if tree_reader is None:
        from .tree_registry import get_tree_registry

        registry = get_tree_registry()
        for conversation_id in conversation_ids:
            tree = registry.tree(conversation_id)
            trees[tree.tree_id] = tree
        return trees
    for conversation_id in conversation_ids:
        payloads = tree_reader(conversation_id) or []
        events = [
            normalize_event(
                payload,
                storage_scope=str(payload.get("storage_scope") or ""),
                recorded_at=_as_float(payload.get("timestamp")),
            )
            for payload in payloads
            if isinstance(payload, Mapping)
        ]
        tree = build_tree(events, conversation_id=conversation_id)
        trees[tree.tree_id] = tree
    return trees


def context_branch_scope() -> Optional[Dict[str, Any]]:
    try:
        from core.agents.chat_agent_components.message_branch import (
            get_chat_history_branch_scope,
        )

        return get_chat_history_branch_scope()
    except Exception:  # noqa: BLE001 - 独立审计脚本没有该模块也能跑
        return None


def _log_outcome(
    outcome: GateOutcome,
    *,
    conversation_id: str,
    mode: str,
    logger: Optional[LoggerLike],
) -> None:
    sink = logger or _module_logger()
    if sink is None:
        return
    summary = (
        f"read_gate mode={mode} conversation={conversation_id or '-'} "
        f"visible={outcome.visible} hidden={outcome.hidden} reasons={outcome.reasons}"
    )
    if outcome.hidden:
        sink.info(summary)
    else:
        sink.debug(summary)


def _log_failure(exc: Exception, *, logger: Optional[LoggerLike]) -> None:
    sink = logger or _module_logger()
    if sink is not None:
        sink.warning(f"read_gate 拓扑判定失败，按 compat 放行: {type(exc).__name__}: {exc}")


def _module_logger() -> Optional[LoggerLike]:
    try:
        from core.utils.logger import get_logger

        return get_logger("MemoryReadGate")
    except Exception:  # noqa: BLE001
        return None


__all__ = [
    "COMPAT_PASS_REASONS",
    "GateOutcome",
    "context_branch_scope",
    "filter_raw_events",
    "load_trees",
    "resolve_gate_anchors",
]
