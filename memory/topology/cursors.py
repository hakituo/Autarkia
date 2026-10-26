"""按会话持久化的分支游标：没有请求路径的读也知道「当前在哪条线上」（v3 E10）。

在线 Android 请求的 anchor 来自 ``history_override``；nightly、主动消息、QQ 侧跨会话
搜索都没有这份路径，过去只能对整棵树按 compat 放行，兄弟线照样混进来。

- 写：``ChatHistoryStore`` 每次落盘带节点的事件后调 ``advance_cursors``，把该会话游标
  推进到最新节点；只在位置变化时追加一行审计。新节点不在旧游标的后代上时记为
  ``branch_switch``（用户在手机上切到别的分支后继续聊）。
- 读：``cursor_for(conversation_id)``；还没有游标时退到覆盖文件里手机导出时的
  ``active_leaf``（历史回填会话）。

孤立链保护（2026-10-26 线上实例：回复主动消息时 parent 是服务端不认识的节点）：
新节点的父链停在一个 parent 没到的待定节点上，就不算切线——不让游标跳到孤立根上
（那样没有请求路径的读会把整段回填历史判成 ``not_on_anchor_path``）。旧游标是真树
节点时，把孤立链根嫁接到旧游标下（``cursor_grafts.json``，``orphan_grafted``），游标照常
前进；旧游标也不可靠时游标不动（``orphan_held``）。嫁接只在 parent 一直没到时生效，
真 parent 到了以真 parent 为准（见 ``dangling.py``）。

键用会话 ID 而不是 tree_id：tree_id 由根节点算出，写入路径拿不到；一个会话对应一棵树。
存储复用 ``AnchorStore``（快照 + ``anchor_events.jsonl``），按 scope 分目录。
游标是会话状态，不改任何事件或笔记——切回旧分支只是游标换了位置（取消全局 inactive）。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .anchors import AnchorStore
from .overlay import is_structural_event_id, load_overlay

REASON_TURN = "turn_written"
REASON_SWITCH = "branch_switch"
REASON_GRAFT = "orphan_grafted"
REASON_HELD = "orphan_held"

GRAFTS_FILE = "cursor_grafts.json"

_stores: Dict[str, AnchorStore] = {}
_snapshots: Dict[str, Tuple[float, Dict[str, str]]] = {}
_grafts: Dict[str, Tuple[float, Dict[str, Dict[str, str]]]] = {}
_lock = threading.RLock()


def scope_for(conversation_id: str) -> str:
    from core.utils.data_paths import resolve_data_scope_from_conversation_id

    return resolve_data_scope_from_conversation_id(str(conversation_id or ""), default="aveline")


def base_dir_for(scope: str) -> Optional[Path]:
    """``None`` = AnchorStore 默认目录（``<scope>_data/memories/topology``）；测试会替换它。"""
    return None


def _store(scope: str) -> AnchorStore:
    with _lock:
        store = _stores.get(scope)
        if store is None:
            store = AnchorStore(scope, base_dir=base_dir_for(scope))
            _stores[scope] = store
        return store


def _load(scope: str) -> Dict[str, str]:
    """按快照文件修改时间缓存；检索时每条记忆都会问到，不能每次读盘。"""
    store = _store(scope)
    try:
        mtime = store.snapshot_path.stat().st_mtime
    except OSError:
        mtime = -1.0
    with _lock:
        cached = _snapshots.get(scope)
        if cached is not None and cached[0] == mtime:
            return cached[1]
    anchors = store.load() if mtime >= 0 else {}
    with _lock:
        _snapshots[scope] = (mtime, anchors)
    return anchors


def cursor_for(conversation_id: str) -> str:
    cid = str(conversation_id or "").strip()
    if not cid:
        return ""
    scope = scope_for(cid)
    stored = _load(scope).get(cid, "")
    if stored:
        return stored
    return overlay_leaf(cid)


def overlay_leaf(conversation_id: str) -> str:
    """覆盖文件里手机导出时的激活Ye（历史回填会话的游标初值）。"""
    cid = str(conversation_id or "").strip()
    overlay = load_overlay(cid, scope_for(cid)) if cid else None
    return str((overlay or {}).get("active_leaf") or "")


def advance_cursors(payloads: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """落盘后推进游标；返回本次实际写入的记录（会话 → 记录）。"""
    latest: Dict[str, Mapping[str, Any]] = {}
    for payload in payloads:
        if not isinstance(payload, Mapping):
            continue
        node_id = str(payload.get("client_node_id") or "").strip()
        if not node_id or is_structural_event_id(str(payload.get("event_id") or "")):
            continue
        conversation_id = str(payload.get("conversation_id") or "").strip()
        if conversation_id:
            latest[conversation_id] = payload  # 组内按写入顺序，最后一条即最新
    written: Dict[str, Dict[str, Any]] = {}
    for conversation_id, payload in latest.items():
        node_id = str(payload["client_node_id"]).strip()
        previous = cursor_for(conversation_id)
        if previous == node_id:
            continue
        scope = scope_for(conversation_id)
        reason, orphan_root = _judge(conversation_id, previous, node_id)
        if reason == REASON_HELD:
            _audit(scope, conversation_id, "anchor_held", node_id, previous)
            continue
        if orphan_root:
            _add_graft(scope, conversation_id, orphan_root, previous)
        record = _store(scope).set(
            conversation_id, node_id, reason=reason, source="chat_history_store"
        )
        with _lock:
            _snapshots.pop(scope, None)
        written[conversation_id] = record
    return written


def _judge(conversation_id: str, previous: str, node_id: str) -> Tuple[str, str]:
    """返回 (原因码, 需要嫁接的孤立链根)。只有父链连到真根的节点才算有效切线。"""
    if not previous:
        return REASON_TURN, ""
    try:
        from .tree_registry import get_tree_registry

        tree = get_tree_registry().tree(conversation_id)
    except Exception:  # noqa: BLE001 - 判不出就按普通推进记
        return REASON_TURN, ""
    if node_id not in tree.nodes:
        return REASON_TURN, ""
    path = tree.ancestors(node_id)
    if previous in path:
        return REASON_TURN, ""  # 同一条链上往下走（包括孤立链内部）
    if tree.is_grounded(node_id):
        return REASON_SWITCH, ""
    if previous in tree.nodes and tree.is_grounded(previous):
        return REASON_GRAFT, path[0]
    return REASON_HELD, ""


def proactive_node_fields(conversation_id: str, client_message_id: str) -> Dict[str, str]:
    """主动消息的节点字段：推送 message_id 作节点，挂在该会话当前游标下。

    Android 收到主动消息后用推送里的 message_id 当本地节点 ID（多句拆成 ``id``、
    ``id-1``…，后者由 ``dangling.segment_base`` 归回 ``id``），并挂在本地激活Ye下；
    服务端游标跟踪的就是该会话最新写入的节点，两边一致。没有游标时不给节点
    （否则主动消息自己成了新根）。
    """
    node_id = str(client_message_id or "").strip()
    parent = cursor_for(conversation_id) if node_id else ""
    if not node_id or not parent or parent == node_id:
        return {}
    return {"client_message_id": node_id, "parent_id": parent}


# ---- 孤立链嫁接记录 ---------------------------------------------------------
def _grafts_path(scope: str) -> Path:
    return _store(scope).base_dir / GRAFTS_FILE


def _load_grafts(scope: str) -> Dict[str, Dict[str, str]]:
    path = _grafts_path(scope)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    with _lock:
        cached = _grafts.get(scope)
        if cached is not None and cached[0] == mtime:
            return cached[1]
    try:
        raw = json.loads(path.read_text(encoding="utf-8")).get("grafts") or {}
    except Exception:  # noqa: BLE001
        raw = {}
    grafts = {
        str(cid): {str(k): str(v) for k, v in items.items() if k and v}
        for cid, items in raw.items()
        if isinstance(items, dict)
    }
    with _lock:
        _grafts[scope] = (mtime, grafts)
    return grafts


def grafts_for(conversation_id: str) -> Dict[str, str]:
    """孤立链根 → 嫁接目标；建树时只对仍悬空的节点生效。"""
    cid = str(conversation_id or "").strip()
    return dict(_load_grafts(scope_for(cid)).get(cid) or {}) if cid else {}


def _add_graft(scope: str, conversation_id: str, orphan_root: str, parent: str) -> None:
    from core.utils.atomic_io import safe_json_dump

    with _lock:
        grafts = {cid: dict(items) for cid, items in _load_grafts(scope).items()}
        grafts.setdefault(conversation_id, {})[orphan_root] = parent
        path = _grafts_path(scope)
        path.parent.mkdir(parents=True, exist_ok=True)
        safe_json_dump({"version": 1, "scope": scope, "grafts": grafts}, path, encoding="utf-8")
        _grafts.pop(scope, None)
    _audit(scope, conversation_id, "graft_added", orphan_root, parent)
    try:
        from .tree_registry import get_tree_registry

        get_tree_registry().invalidate(conversation_id)
    except Exception:  # noqa: BLE001, S110 - 失效失败最多晚一个刷新周期生效
        pass


def _audit(scope: str, conversation_id: str, kind: str, node_id: str, other: str) -> None:
    """只追加审计行，不动游标快照（只含节点 ID）。"""
    record = {
        "type": kind,
        "tree_id": conversation_id,
        "node_id": node_id,
        "previous" if kind == "anchor_held" else "parent": other,
        "reason": REASON_HELD if kind == "anchor_held" else REASON_GRAFT,
        "source": "chat_history_store",
        "changed_at": time.time(),
    }
    store = _store(scope)
    try:
        store.base_dir.mkdir(parents=True, exist_ok=True)
        with open(store.events_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def reset_cursor_cache() -> None:
    with _lock:
        _stores.clear()
        _snapshots.clear()
        _grafts.clear()


__all__ = [
    "REASON_GRAFT",
    "REASON_HELD",
    "REASON_SWITCH",
    "REASON_TURN",
    "advance_cursors",
    "base_dir_for",
    "cursor_for",
    "grafts_for",
    "overlay_leaf",
    "proactive_node_fields",
    "reset_cursor_cache",
    "scope_for",
]
