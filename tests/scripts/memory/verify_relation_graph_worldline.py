"""验证关系图的世界线闸门（v3 E3）：种子、逐跳扩展、最终返回的跨线证据均为 0。

合成一棵「共享前缀 + 三条兄弟线」的树，所有记忆两两强连接（同一 turn key），
对每个Ye anchor 跑一次 rerank / cluster，统计返回里不在 anchor 祖先路径上的记忆。
不读写真实记忆池：
    venv_cpu\\Scripts\\python.exe tests\\scripts\\memory\\verify_relation_graph_worldline.py
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from memory.core.relation_graph import (  # noqa: E402
    get_relation_cluster,
    rerank_with_relation_graph,
)
from memory.topology.memory_gate import build_memory_visibility  # noqa: E402
from memory.topology.read_context import MODE_COMPAT, MODE_STRICT  # noqa: E402

CONV = "shared__scope__aveline"
# root → a → {b1 → b2, c1 → c2, d1}
PARENTS = {"root": "", "a": "root", "b1": "a", "b2": "b1", "c1": "a", "c2": "c1", "d1": "a"}
LEAVES = ("b2", "c2", "d1")


class _Manager:
    def __init__(self, memories):
        self.weighted_memories = memories
        self.lock = threading.RLock()
        self._use_rw_lock = False


def _events():
    return [
        {
            "event_id": f"evt-{node}",
            "conversation_id": CONV,
            "role": "user",
            "content": node,
            "timestamp": float(index),
            "event_type": "chat_message",
            "client_node_id": node,
            "parent_node_id": parent,
        }
        for index, (node, parent) in enumerate(PARENTS.items(), start=1)
    ]


def _memories():
    return {
        f"m-{node}": {
            "id": f"m-{node}",
            "content": node,
            "timestamp": float(index),
            "weight": 5.0,
            "topics": ["同一话题"],
            "role": "user",
            "source": "user",
            "category": "event",
            "memory_type": "dialogue",
            "status": "active",
            "scopes": ["sfw"],
            "metadata": {
                "conversation_id": CONV,
                "event_ref": {"event_id": f"evt-{node}"},
                "turn_id": "same-turn",
            },
        }
        for index, node in enumerate(PARENTS, start=1)
    }


def _path(leaf):
    chain, node = [], leaf
    while node:
        chain.append(node)
        node = PARENTS[node]
    return set(chain)


def _gate(leaf, mode):
    events = _events()
    scope = {"allowed_message_ids": _path(leaf), "not_after_ts": None, "conversation_id": CONV}
    return build_memory_visibility(mode=mode, branch_scope=scope, tree_reader=lambda _cid: events)


def _cross_line(ids, leaf):
    allowed = {f"m-{node}" for node in _path(leaf)}
    return [item for item in ids if item not in allowed]


def _check(mode) -> bool:
    manager = _Manager(_memories())
    seeds = [{**memory, "hybrid_score": 0.9} for memory in manager.weighted_memories.values()]
    total, details = 0, {}
    for leaf in LEAVES:
        ranked = rerank_with_relation_graph(manager, seeds, limit=20, visibility=_gate(leaf, mode))
        cluster = get_relation_cluster(
            manager, "m-root", limit=20, max_depth=3, visibility=_gate(leaf, mode)
        )
        expanded = rerank_with_relation_graph(
            manager, seeds[:1], limit=20, visibility=_gate(leaf, mode)
        )
        cross = (
            _cross_line([item["id"] for item in ranked], leaf)
            + _cross_line([item["id"] for item in cluster], leaf)
            + _cross_line([item["id"] for item in expanded], leaf)
        )
        details[leaf] = len(cross)
        total += len(cross)
    ok = total == 0
    print(f"[{'OK' if ok else 'FAIL'}] {mode} 关系图跨线证据 = {total}（要求 0）逐 anchor={details}")
    return ok


def _check_ungated_baseline_leaks() -> bool:
    """对照组：不加闸门时同一数据确实会跨线，证明上面的 0 不是数据太稀疏。"""
    manager = _Manager(_memories())
    seeds = [{**manager.weighted_memories["m-b2"], "hybrid_score": 0.9}]
    ranked = rerank_with_relation_graph(manager, seeds, limit=20, visibility=None)
    leaked = _cross_line([item["id"] for item in ranked], "b2")
    ok = bool(leaked)
    print(f"[{'OK' if ok else 'FAIL'}] 对照组（无闸门）会扩散到兄弟线：{sorted(leaked)}")
    return ok


def main() -> int:
    results = [_check(MODE_STRICT), _check(MODE_COMPAT), _check_ungated_baseline_leaks()]
    passed = sum(1 for item in results if item)
    print(f"\n结果：{passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
