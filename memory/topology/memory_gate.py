"""加权记忆 / 关系图的世界线闸门（v3 E3）。

``read_gate`` 管原始聊天事件；这里把同一套谓词套到 WeightedMemory 记录上，
供关系图的种子、逐跳扩展与最终返回三处共用：

1. 回滚边界：与 ``filter_events_by_branch_scope`` 同一判据（活跃路径 ID /
   分支点时间），只对边界所属会话生效；
2. 树路径：记忆的来源节点取 ``metadata.client_message_id``，没有时按
   ``event_ref.event_id`` 在该会话的树里反查节点（E09：按来源事件判断，
   不信 lineage 标签）；节点不在 anchor 祖先路径上即隐藏。

compat 策略与 ``read_gate`` 一致：缺失型原因放行并计数，兄弟线永远隐藏。
请求里既没有回滚边界也没有显式 anchor 时 ``build_memory_visibility`` 返回
``None``，调用方走零开销快路径。
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

from .events import normalize_event
from .read_context import MODE_COMPAT, MODE_STRICT, build_read_context, event_visibility_reason
from .read_gate import COMPAT_PASS_REASONS, context_branch_scope, load_trees, resolve_gate_anchors
from .tree import TreeBuildResult

#: 记忆特有的缺失型原因：旧记录没写会话 ID，无法判断属于哪棵树
CONVERSATION_UNKNOWN = "conversation_unknown"
#: 被回滚掉的分支（与原始事件同一判据），任何模式都隐藏
BRANCH_ROLLED_BACK = "branch_rolled_back"

_PASS_REASONS = COMPAT_PASS_REASONS | {CONVERSATION_UNKNOWN}

TreeReader = Callable[[str], Sequence[Mapping[str, Any]]]

def _metadata(memory: Mapping[str, Any]) -> Dict[str, Any]:
    value = memory.get("metadata")
    return value if isinstance(value, dict) else {}


def memory_conversation_id(memory: Mapping[str, Any]) -> str:
    """记忆所属会话：显式字段优先，其次取来源事件引用里的会话。

    Android 聊天的记忆落在 ``shared__scope__<角色>`` 文件里，metadata 不带会话 ID，
    只有 ``event_ref.conversation_id`` 指向真正的 ``web_role_*`` 会话。
    """
    metadata = _metadata(memory)
    explicit = str(metadata.get("conversation_id") or memory.get("conversation_id") or "").strip()
    if explicit:
        return explicit
    event_ref = metadata.get("event_ref")
    if isinstance(event_ref, dict):
        return str(event_ref.get("conversation_id") or "").strip()
    return ""


def _event_ref_id(memory: Mapping[str, Any]) -> str:
    event_ref = _metadata(memory).get("event_ref")
    if isinstance(event_ref, dict):
        return str(event_ref.get("event_id") or event_ref.get("id") or "").strip()
    source_ref = memory.get("source_ref")
    if isinstance(source_ref, dict) and source_ref.get("kind") == "event":
        return str(source_ref.get("event_id") or "").strip()
    return ""


def memory_event_payload(memory: Mapping[str, Any]) -> Dict[str, Any]:
    """把一条记忆投影成回滚边界判据需要的事件形状。"""
    metadata = _metadata(memory)
    return {
        "event_id": _event_ref_id(memory),
        "conversation_id": memory_conversation_id(memory),
        "message_id": str(metadata.get("message_id") or "").strip(),
        "timestamp": memory.get("timestamp") or metadata.get("timestamp") or 0.0,
        "role": str(memory.get("role") or memory.get("source") or ""),
        "content": "",
        "metadata": {"is_proactive": bool(metadata.get("is_proactive"))},
    }


class MemoryVisibility:
    """一次检索内复用的可见性判定器；树按会话懒加载并缓存。"""

    def __init__(
        self,
        *,
        branch_scope: Optional[Mapping[str, Any]],
        explicit_anchors: Optional[Mapping[str, str]] = None,
        mode: str = MODE_COMPAT,
        tree_reader: Optional[TreeReader] = None,
    ) -> None:
        self.branch_scope = dict(branch_scope) if branch_scope else None
        self.scope_conversation = str((branch_scope or {}).get("conversation_id") or "").strip()
        self.explicit_anchors = dict(explicit_anchors or {})
        self.mode = MODE_STRICT if mode == MODE_STRICT else MODE_COMPAT
        self._tree_reader = tree_reader
        self._trees: Dict[str, Optional[TreeBuildResult]] = {}
        self._event_nodes: Dict[str, Dict[str, str]] = {}
        self._verdicts: Dict[str, bool] = {}
        self.reasons: Counter = Counter()

    # ---- 公共接口 ---------------------------------------------------------
    def is_visible(self, memory: Mapping[str, Any]) -> bool:
        """同一条记忆在一次检索内只判定一次（种子/逐跳会反复问到）。"""
        memory_id = str(memory.get("id") or "")
        if memory_id and memory_id in self._verdicts:
            return self._verdicts[memory_id]
        verdict = self._judge(memory)
        if memory_id:
            self._verdicts[memory_id] = verdict
        return verdict

    def _judge(self, memory: Mapping[str, Any]) -> bool:
        try:
            reason = self._strict_reason(memory)
        except Exception:  # noqa: BLE001 - 拓扑故障不得清空检索
            reason = "gate_error"
            if self.mode != MODE_STRICT:
                self.reasons["compat_pass:gate_error"] += 1
                return True
        if reason is None:
            return True
        if self.mode != MODE_STRICT and reason in _PASS_REASONS:
            self.reasons[f"compat_pass:{reason}"] += 1
            return True
        self.reasons[reason] += 1
        return False

    def filter(self, memories: Iterable[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
        return [memory for memory in memories if self.is_visible(memory)]

    @property
    def hidden(self) -> int:
        return sum(
            count for reason, count in self.reasons.items() if not reason.startswith("compat_pass:")
        )

    # ---- 判定 -------------------------------------------------------------
    def _strict_reason(self, memory: Mapping[str, Any]) -> Optional[str]:
        payload = memory_event_payload(memory)
        conversation_id = payload["conversation_id"]
        if not conversation_id:
            return CONVERSATION_UNKNOWN
        if self.branch_scope and self.scope_conversation == conversation_id:
            from core.agents.chat_agent_components.message_branch import (
                is_event_visible_in_branch,
            )

            if not is_event_visible_in_branch(
                payload, conversation_id=conversation_id, scope=self.branch_scope
            ):
                return BRANCH_ROLLED_BACK
        if (
            conversation_id != self.scope_conversation
            and not self.explicit_anchors
            and not _cursor_for(conversation_id)
        ):
            # 这棵树没有任何 anchor 来源（请求路径 / 显式 anchor / 持久化游标）
            return "anchor_missing"
        if not payload["event_id"] and not _metadata(memory).get("client_message_id"):
            return "legacy_unknown"  # 无来源指针：不必为它读整棵树
        tree = self._tree_for(conversation_id)
        if tree is None:
            return "tree_unresolvable"
        node_id = self._node_for(memory, payload, tree)
        if not node_id:
            return "legacy_unknown"
        anchors = resolve_gate_anchors(
            {tree.tree_id: tree},
            conversation_id=self.scope_conversation,
            branch_scope=self.branch_scope,
        )
        node = tree.nodes[node_id]
        event = normalize_event(
            {
                **payload,
                "client_node_id": node_id,
                "parent_node_id": node.parent_id,
            },
            tree_id=tree.tree_id,
        )
        ctx = build_read_context(
            mode=MODE_STRICT, anchors_by_tree=anchors, allowed_trees=[tree.tree_id]
        )
        return event_visibility_reason(ctx, event, {tree.tree_id: tree})

    def _tree_for(self, conversation_id: str) -> Optional[TreeBuildResult]:
        if conversation_id not in self._trees:
            if self._tree_reader is None:
                from .tree_registry import get_tree_registry

                tree, index = get_tree_registry().snapshot(conversation_id)
            else:
                trees = load_trees([conversation_id], self._tree_reader)
                tree = next(iter(trees.values()), None)
                index = {}
                if tree is not None:
                    for node_id, node in tree.nodes.items():
                        for event_id in node.event_ids:
                            index[str(event_id)] = node_id
            self._trees[conversation_id] = tree
            self._event_nodes[conversation_id] = index
        return self._trees[conversation_id]

    def _node_for(
        self, memory: Mapping[str, Any], payload: Mapping[str, Any], tree: TreeBuildResult
    ) -> str:
        client_id = str(_metadata(memory).get("client_message_id") or "").strip()
        if client_id and client_id in tree.nodes:
            return client_id
        event_id = str(payload.get("event_id") or "")
        if event_id:
            return self._event_nodes.get(tree.conversation_id, {}).get(event_id, "")
        return ""


def build_memory_visibility(
    *,
    mode: str = MODE_COMPAT,
    branch_scope: Optional[Mapping[str, Any]] = None,
    tree_reader: Optional[TreeReader] = None,
    use_cursors: bool = True,
) -> Optional[MemoryVisibility]:
    """按当前请求上下文构造判定器。

    没有请求路径与显式 anchor 时（nightly、主动消息、QQ 侧检索），仍返回一个
    只看持久化游标的判定器：有游标的会话照样隐藏兄弟线，没有游标的会话缺 anchor
    放行，且不会为它读树。``use_cursors=False`` 时退回旧行为（返回 ``None``）。
    """
    scope = branch_scope if branch_scope is not None else context_branch_scope()
    try:
        from .anchors import get_request_anchors

        explicit = get_request_anchors() or {}
    except Exception:  # noqa: BLE001
        explicit = {}
    has_scope = bool(scope and str(scope.get("conversation_id") or "").strip())
    if not has_scope and not explicit and not use_cursors:
        return None
    return MemoryVisibility(
        branch_scope=scope if has_scope else None,
        explicit_anchors=explicit,
        mode=mode,
        tree_reader=tree_reader,
    )


def _cursor_for(conversation_id: str) -> str:
    try:
        from .cursors import cursor_for

        return cursor_for(conversation_id)
    except Exception:  # noqa: BLE001 - 游标读失败按缺 anchor 处理
        return ""


__all__ = [
    "BRANCH_ROLLED_BACK",
    "CONVERSATION_UNKNOWN",
    "MemoryVisibility",
    "build_memory_visibility",
    "memory_conversation_id",
    "memory_event_payload",
]
