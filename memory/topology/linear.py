"""线性来源（QQ / Telegram 等）的服务端 parent 附着（v3 D5）。

这类平台不提供消息树，每条消息只有到达顺序。若不给服务端节点 ID，
所有消息都会变成"无 parent"，建树时就成了多个根 = 多条世界线。
这里在**落盘同一临界区**内把新事件附到当前会话文件的队尾节点上：

- 节点 ID 由服务端生成（``srv:<event_id>``），可审计、可重算；
- head 先查进程内缓存，未命中时读该 JSONL 的最后一行（进程重启也能接上）；
- 文件被清空/删除后尾部读不到节点 → 返回空 head，事件退化为 partial，
  不会伪造新根，也不会静默接错。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Dict, Optional

#: 线性来源平台：没有客户端消息树，只能按到达顺序附着
LINEAR_PLATFORMS = frozenset({"qq", "telegram"})

SERVER_NODE_PREFIX = "srv:"


def is_linear_source(platform: str, client_node_id: str = "") -> bool:
    """是否为"需要服务端附着"的线性来源。"""
    if str(client_node_id or "").strip():
        return False
    return str(platform or "").strip().lower() in LINEAR_PLATFORMS


def server_node_id(event_id: str) -> str:
    return f"{SERVER_NODE_PREFIX}{str(event_id or '').strip()}"


def read_tail_node(file_path: Path) -> str:
    """读取 JSONL 最后一个事件的节点 ID；读不到返回空串。"""
    try:
        with open(file_path, "r", encoding="utf-8") as handle:
            last = ""
            for line in handle:
                if line.strip():
                    last = line
    except OSError:
        return ""
    if not last:
        return ""
    try:
        payload = json.loads(last)
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    node_id = str(payload.get("client_node_id") or "").strip()
    if node_id:
        return node_id
    event_id = str(payload.get("event_id") or "").strip()
    return server_node_id(event_id) if event_id else ""


class LinearHeadTracker:
    """每个会话文件的当前队尾节点；线程安全，进程内缓存。"""

    def __init__(self) -> None:
        self._heads: Dict[str, str] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _key(file_path: Path) -> str:
        try:
            return str(Path(file_path).resolve())
        except OSError:
            return str(file_path)

    def head(self, file_path: Path) -> str:
        key = self._key(file_path)
        with self._lock:
            if key in self._heads:
                return self._heads[key]
            resolved = read_tail_node(file_path)
            self._heads[key] = resolved
            return resolved

    def advance(self, file_path: Path, node_id: str) -> None:
        value = str(node_id or "").strip()
        if not value:
            return
        with self._lock:
            self._heads[self._key(file_path)] = value

    def forget(self, file_path: Path) -> None:
        with self._lock:
            self._heads.pop(self._key(file_path), None)

    def clear(self) -> None:
        with self._lock:
            self._heads.clear()


_TRACKER = LinearHeadTracker()


def get_linear_head_tracker() -> LinearHeadTracker:
    return _TRACKER


def attach_linear_parent(
    payload: Dict[str, object],
    *,
    file_path: Path,
    platform: str,
    tracker: Optional[LinearHeadTracker] = None,
) -> Optional[str]:
    """给线性来源事件补 ``client_node_id`` / ``parent_node_id``。

    返回本次附着到的 parent（空串表示这是该文件的第一个节点）。
    """
    node_id = str(payload.get("client_node_id") or "").strip()
    if node_id:
        return str(payload.get("parent_node_id") or "")
    if not is_linear_source(platform, node_id):
        return ""
    event_id = str(payload.get("event_id") or "").strip()
    if not event_id:
        return ""
    active = tracker or get_linear_head_tracker()
    parent = active.head(file_path)
    payload["client_node_id"] = server_node_id(event_id)
    payload["parent_node_id"] = parent
    payload["topology_status"] = "complete" if parent else "partial"
    return parent
