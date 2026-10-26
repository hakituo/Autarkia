"""验证世界线可见性：strict 跨线为 0、切线回退 A→B→A 一致、compat 风险单列。

不读写真实记忆池，只用内存合成树：
    venv_cpu\\Scripts\\python.exe tests\\scripts\\memory\\verify_worldline_visibility.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from memory.topology.events import normalize_event  # noqa: E402
from memory.topology.read_context import (  # noqa: E402
    MODE_COMPAT,
    MODE_STRICT,
    build_read_context,
    note_visibility_reason,
)
from memory.topology.read_gate import filter_raw_events  # noqa: E402
from memory.topology.tree import build_tree  # noqa: E402

CONV = "shared__scope__aveline"
NAMESPACE = "aveline"


def _payload(node: str, parent: str = "", *, ts: float = 1.0) -> dict:
    payload = {
        "event_id": f"evt-{node}",
        "conversation_id": CONV,
        "role": "user",
        "content": f"正文-{node}",
        "timestamp": ts,
        "event_type": "chat_message",
        "namespace": NAMESPACE,
        "perspective_role": NAMESPACE,
    }
    if node:
        payload["client_node_id"] = node
        payload["parent_node_id"] = parent
    return payload


def _fixture():
    return [
        _payload("root", ts=1.0),
        _payload("a", "root", ts=2.0),
        _payload("b", "a", ts=3.0),
        _payload("c", "a", ts=4.0),
        _payload("", ts=0.5),
    ]


def _scope(node_ids):
    return {"allowed_message_ids": set(node_ids), "not_after_ts": None}


def _run(events, *, mode=MODE_STRICT, node_ids=()):
    return filter_raw_events(
        events,
        conversation_id=CONV,
        mode=mode,
        branch_scope=_scope(node_ids),
        tree_reader=lambda _cid: events,
    )


def _event_ids(outcome):
    return sorted(str(item.get("event_id") or "") for item in outcome.events)


def _tree_of(events):
    return build_tree(
        [
            normalize_event(item, storage_scope=NAMESPACE, perspective_role=NAMESPACE)
            for item in events
        ],
        conversation_id=CONV,
    )


def _check_strict_isolation() -> bool:
    events = _fixture()
    view_a = _run(events, node_ids={"root", "a", "b"})
    view_b = _run(events, node_ids={"root", "a", "c"})
    ok = (
        _event_ids(view_a) == ["evt-a", "evt-b", "evt-root"]
        and _event_ids(view_b) == ["evt-a", "evt-c", "evt-root"]
    )
    print(f"[{'OK' if ok else 'FAIL'}] strict 兄弟线互不可见（A={_event_ids(view_a)} / B={_event_ids(view_b)}）")
    return ok


def _check_switch_back() -> bool:
    events = _fixture()
    first = _event_ids(_run(events, node_ids={"root", "a", "b"}))
    _run(events, node_ids={"root", "a", "c"})
    again = _event_ids(_run(events, node_ids={"root", "a", "b"}))
    ok = first == again
    print(f"[{'OK' if ok else 'FAIL'}] 切线 A→B→A 后可见集完全一致")
    return ok


def _check_cross_line_zero() -> bool:
    events = _fixture()
    tree = _tree_of(events)
    total_cross = 0
    for anchor in ("b", "c"):
        visible = _run(events, node_ids=set(tree.ancestors(anchor))).events
        allowed = set(tree.ancestors(anchor))
        for item in visible:
            node = str(item.get("client_node_id") or "")
            if node and node not in allowed:
                total_cross += 1
    ok = total_cross == 0
    print(f"[{'OK' if ok else 'FAIL'}] strict 跨线可见事件 = {total_cross}（要求 0）")
    return ok


def _check_note_follows_anchor() -> bool:
    events = [item for item in _fixture() if item.get("client_node_id")]
    tree = _tree_of(events)
    by_id = {
        event.event_id: event
        for event in (
            normalize_event(item, storage_scope=NAMESPACE, perspective_role=NAMESPACE)
            for item in events
        )
    }
    note = {
        "visibility": "tree_local",
        "namespace": NAMESPACE,
        "source_event_ids": ["evt-b"],
    }
    ctx_a = build_read_context(
        namespace=NAMESPACE,
        anchors_by_tree={tree.tree_id: "b"},
    )
    ctx_b = build_read_context(
        namespace=NAMESPACE,
        anchors_by_tree={tree.tree_id: "c"},
    )
    visible_a = note_visibility_reason(ctx_a, note, by_id, {tree.tree_id: tree}) is None
    hidden_b = note_visibility_reason(ctx_b, note, by_id, {tree.tree_id: tree}) is not None
    again_a = note_visibility_reason(ctx_a, note, by_id, {tree.tree_id: tree}) is None
    ok = visible_a and hidden_b and again_a
    print(f"[{'OK' if ok else 'FAIL'}] 旧分支笔记无需重新激活：A 可见 → B 隐藏 → 切回 A 仍可见")
    return ok


def _check_compat_risk_listed() -> bool:
    events = _fixture() + [_payload("orphan", "missing-parent", ts=5.0)]
    outcome = _run(events, mode=MODE_COMPAT, node_ids={"root", "a", "b"})
    reasons = outcome.reasons
    ok = (
        outcome.hidden == 1
        and reasons.get("not_on_anchor_path") == 1
        and reasons.get("compat_pass:legacy_unknown") == 1
        and reasons.get("compat_pass:topology_incomplete") == 1
    )
    print(
        "[{}] compat 兼容范围单列：放行原因={} 隐藏原因={}".format(
            "OK" if ok else "FAIL",
            {k: v for k, v in reasons.items() if k.startswith("compat_pass:")},
            {k: v for k, v in reasons.items() if not k.startswith("compat_pass:")},
        )
    )
    return ok


def main() -> int:
    checks = [
        _check_strict_isolation,
        _check_switch_back,
        _check_cross_line_zero,
        _check_note_follows_anchor,
        _check_compat_risk_listed,
    ]
    results = [check() for check in checks]
    passed = sum(1 for item in results if item)
    print(f"\n结果：{passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
