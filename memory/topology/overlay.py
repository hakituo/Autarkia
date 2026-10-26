"""旁挂拓扑覆盖层：给历史事件补消息树结构，但不改写原始事件（v3 D8 回填）。

背景：2026-10-25 前，客户端 message_id 在服务层被丢弃，Android 会话的原始事件
没有任何客户端节点 ID。手机端 Room 库里保存着完整消息树，可以按「时间 + 正文」把
服务端事件配回节点。spec §5.1 要求原始事件只追加不改写，所以配对结果不写回 JSONL，
而是存成每会话一份覆盖文件，建树时叠加：

- ``nodes``：手机整棵树 ``node_id -> [parent_id, timestamp, is_user]``，拓扑以手机为准；
- ``events``：服务端 ``event_id -> node_id``（默认只收高置信度配对）；
- ``active_leaf``：导出时手机上的激活Ye，可作该会话游标的初始值。

没有服务端事件的节点（多气泡回复的中间节点、窗口外父节点等）作为无正文的结构节点
入树，保证父链连通，但 ``content_eligible=False``，不会进入提炼。
删除覆盖文件即完全回退。文件只含 ID 与时间戳，不含正文。
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

OVERLAY_VERSION = 1
STRUCTURAL_EVENT_TYPE = "structural"
STRUCTURAL_PREFIX = "struct:"

_cache: Dict[str, Tuple[float, Optional[Dict[str, Any]]]] = {}
_cache_lock = threading.Lock()


def _safe_name(conversation_id: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", str(conversation_id or ""))[:160] or "default"


def overlay_path(conversation_id: str, scope: str) -> Path:
    from core.utils.data.data_paths import get_role_memories_dir

    base = Path(get_role_memories_dir(scope or "aveline"))
    return base / "topology" / "overlays" / f"{_safe_name(conversation_id)}.json"


def load_overlay(conversation_id: str, scope: str) -> Optional[Dict[str, Any]]:
    """按文件修改时间缓存；文件不存在或格式不对时返回 ``None``。"""
    path = overlay_path(conversation_id, scope)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    key = str(path)
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None and cached[0] == mtime:
            return cached[1]
    from core.utils.atomic_io import safe_json_load

    raw = safe_json_load(path, default=None)
    overlay = raw if _valid(raw, conversation_id) else None
    with _cache_lock:
        _cache[key] = (mtime, overlay)
    return overlay


def clear_overlay_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _valid(raw: Any, conversation_id: str) -> bool:
    return (
        isinstance(raw, dict)
        and raw.get("version") == OVERLAY_VERSION
        and str(raw.get("conversation_id") or "") == str(conversation_id or "")
        and isinstance(raw.get("nodes"), dict)
        and isinstance(raw.get("events"), dict)
    )


def scope_of(payloads: Sequence[Mapping[str, Any]], conversation_id: str) -> str:
    """覆盖文件放在会话所属角色目录下：优先取事件自己的 storage_scope。"""
    for payload in payloads:
        scope = str(payload.get("storage_scope") or "").strip()
        if scope:
            return scope
    try:
        from core.utils.data_paths import resolve_data_scope_from_conversation_id

        return resolve_data_scope_from_conversation_id(conversation_id, default="aveline")
    except Exception:  # noqa: BLE001
        return "aveline"


def apply_overlay(
    payloads: Sequence[Mapping[str, Any]],
    overlay: Optional[Mapping[str, Any]],
    *,
    conversation_id: str,
    scope: str = "",
) -> List[Dict[str, Any]]:
    """给缺节点的事件补节点字段，并补上结构节点；已带节点的事件原样保留。"""
    items = [dict(payload) for payload in payloads if isinstance(payload, Mapping)]
    if not overlay:
        return items
    nodes: Mapping[str, Any] = overlay.get("nodes") or {}
    events: Mapping[str, Any] = overlay.get("events") or {}
    covered: set = set()
    for item in items:
        node_id = str(item.get("client_node_id") or "")
        if not node_id:
            node_id = str(events.get(str(item.get("event_id") or "")) or "")
            if node_id and node_id in nodes:
                item["client_node_id"] = node_id
                item["parent_node_id"] = _parent(nodes, node_id)
                item["topology_source"] = "overlay"
        if node_id:
            covered.add(node_id)
    for node_id, spec in nodes.items():
        if node_id in covered:
            continue
        parent_id, timestamp, is_user = _unpack(spec)
        items.append(
            {
                "event_id": f"{STRUCTURAL_PREFIX}{node_id}",
                "conversation_id": conversation_id,
                "role": "user" if is_user else "assistant",
                "content": "",
                "timestamp": timestamp,
                "event_type": STRUCTURAL_EVENT_TYPE,
                "client_node_id": node_id,
                "parent_node_id": parent_id,
                "storage_scope": scope,
                "topology_source": "overlay",
            }
        )
    return items


def _unpack(spec: Any) -> Tuple[str, float, bool]:
    if isinstance(spec, (list, tuple)) and len(spec) >= 3:
        return str(spec[0] or ""), float(spec[1] or 0.0), bool(spec[2])
    return "", 0.0, False


def _parent(nodes: Mapping[str, Any], node_id: str) -> str:
    return _unpack(nodes.get(node_id))[0]


def is_structural_event_id(event_id: str) -> bool:
    return str(event_id or "").startswith(STRUCTURAL_PREFIX)


__all__ = [
    "OVERLAY_VERSION",
    "STRUCTURAL_EVENT_TYPE",
    "apply_overlay",
    "clear_overlay_cache",
    "is_structural_event_id",
    "load_overlay",
    "overlay_path",
    "scope_of",
]
