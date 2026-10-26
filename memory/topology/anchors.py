"""逐 tree 的 anchor 控制面（v3 D7）。

``anchors_by_tree`` 是硬约束：每棵允许读取的 tree 都必须有明确 anchor，
缺 anchor 时该 tree 不返回内容（fail-closed），禁止默认放行全树。
切换分支只改对应 tree 的游标，历史事件与派生笔记都不改状态：
open/closed 是会话游标，不是事件属性，因此没有全局 ``inactive``。
"""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Mapping, Optional

ANCHOR_STORE_VERSION = 1

_request_anchors: ContextVar[Optional[Dict[str, str]]] = ContextVar(
    "xiaoyou_request_anchors_by_tree", default=None
)


def set_request_anchors(anchors: Optional[Mapping[str, str]]) -> Token:
    """绑定本轮请求的显式 anchor（请求路径优先于持久化游标）。"""
    cleaned = {
        str(tree_id).strip(): str(node_id).strip()
        for tree_id, node_id in (anchors or {}).items()
        if str(tree_id).strip() and str(node_id).strip()
    }
    return _request_anchors.set(cleaned or None)


def reset_request_anchors(token: Token) -> None:
    _request_anchors.reset(token)


def get_request_anchors() -> Optional[Dict[str, str]]:
    value = _request_anchors.get()
    return dict(value) if value else None


def _anchors_dir(scope: str) -> Path:
    from core.utils.data.data_paths import get_role_memories_dir

    return Path(get_role_memories_dir(scope)) / "topology"


class AnchorStore:
    """按 scope 持久化逐 tree 游标；快照只是缓存，事件日志才是审计来源。"""

    def __init__(self, scope: str, *, base_dir: Optional[Path] = None) -> None:
        self.scope = str(scope or "user")
        self._base_dir = Path(base_dir) if base_dir else None
        self._lock = threading.RLock()

    @property
    def base_dir(self) -> Path:
        return self._base_dir or _anchors_dir(self.scope)

    @property
    def snapshot_path(self) -> Path:
        return self.base_dir / "anchors.json"

    @property
    def events_path(self) -> Path:
        return self.base_dir / "anchor_events.jsonl"

    def load(self) -> Dict[str, str]:
        with self._lock:
            return dict(self._load_snapshot())

    def get(self, tree_id: str) -> str:
        return self._load_snapshot().get(str(tree_id or ""), "")

    def set(
        self,
        tree_id: str,
        node_id: str,
        *,
        reason: str = "user_request",
        source: str = "runtime",
        changed_at: Optional[float] = None,
    ) -> Dict[str, Any]:
        tree_key = str(tree_id or "").strip()
        node_key = str(node_id or "").strip()
        if not tree_key or not node_key:
            raise ValueError("anchor 需要明确的 tree_id 与 node_id")
        stamp = float(changed_at if changed_at is not None else time.time())
        with self._lock:
            anchors = self._load_snapshot()
            previous = anchors.get(tree_key, "")
            anchors[tree_key] = node_key
            self.base_dir.mkdir(parents=True, exist_ok=True)
            record = {
                "type": "anchor_changed",
                "tree_id": tree_key,
                "node_id": node_key,
                "previous": previous,
                "reason": str(reason or ""),
                "source": str(source or ""),
                "changed_at": stamp,
            }
            with open(self.events_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._write_snapshot(anchors, stamp)
            return record

    # ---- 内部 -----------------------------------------------------------
    def _load_snapshot(self) -> Dict[str, str]:
        try:
            raw = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        anchors = raw.get("anchors") if isinstance(raw, dict) else None
        if not isinstance(anchors, dict):
            return {}
        result: Dict[str, str] = {}
        for tree_id, value in anchors.items():
            if isinstance(value, dict):
                node_id = str(value.get("node_id") or "").strip()
            else:
                node_id = str(value or "").strip()
            if str(tree_id).strip() and node_id:
                result[str(tree_id).strip()] = node_id
        return result

    def _write_snapshot(self, anchors: Mapping[str, str], stamp: float) -> None:
        from core.utils.atomic_io import safe_json_dump

        payload = {
            "version": ANCHOR_STORE_VERSION,
            "scope": self.scope,
            "updated_at": stamp,
            "anchors": {
                tree_id: {"node_id": node_id}
                for tree_id, node_id in sorted(anchors.items())
            },
        }
        safe_json_dump(payload, self.snapshot_path, encoding="utf-8")


def resolve_anchors_by_tree(
    tree_ids: Iterable[str],
    *,
    explicit: Optional[Mapping[str, str]] = None,
    store: Optional[AnchorStore] = None,
) -> Dict[str, Optional[str]]:
    """请求显式路径优先，其次逐 tree 持久化游标；都没有时为 ``None``。

    返回 ``None`` 的 tree 必须在读路径上被跳过并记录原因，不能默认放行。
    """
    request = dict(explicit) if explicit is not None else (get_request_anchors() or {})
    stored = store.load() if store is not None else {}
    resolved: Dict[str, Optional[str]] = {}
    for tree_id in tree_ids:
        key = str(tree_id or "").strip()
        if not key:
            continue
        anchor = str(request.get(key) or "").strip() or str(stored.get(key) or "").strip()
        resolved[key] = anchor or None
    return resolved


@contextmanager
def bound_anchors(anchors: Optional[Mapping[str, str]]) -> Iterator[None]:
    """在调用链内临时绑定 anchor，退出时还原。"""
    token = set_request_anchors(anchors)
    try:
        yield
    finally:
        reset_request_anchors(token)
