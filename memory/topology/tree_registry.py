"""按会话常驻的消息树：首次用到时全量建一次，之后随写入增量挂节点（v3 D6 运行时）。

此前读路径每次检索都把整个会话 JSONL 读出来现场建树（主会话 5 万条约 1.4s）。
树的结构本来就只由原始事件里的父子指针决定，所以完全可以「边写边建」：

- ``snapshot(cid)``：没加载过就从 ChatHistoryStore 全量读一次并建树，之后直接返回；
- ``on_append(payloads)``：ChatHistoryStore 落盘后调用，已加载的会话把新事件
  ``TreeBuilder.add`` 进去（child 先到会进 pending，父节点到了自动补挂）；
- ``forget(cid)``：会话被删除时丢弃。

增量与全量建树走同一个 ``TreeBuilder`` 与同一套规范化，规范哈希一致（单测覆盖）。
``refresh_seconds`` 只兜底其他进程直接写 JSONL 的情况，正常写入不依赖它。
不持久化：原始事件仍是唯一真源，进程重启后按需重建。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from .events import NormalizedEvent, normalize_event
from .tree import TreeBuilder, TreeBuildResult

Reader = Callable[[str], Sequence[Mapping[str, Any]]]
OverlayLoader = Callable[[str, str], Optional[Mapping[str, Any]]]
GraftLoader = Callable[[str], Mapping[str, str]]
EventIndex = Dict[str, str]

DEFAULT_REFRESH_SECONDS = 1800.0
_THOUGHT = "thought-turn:"


def normalize_payload(payload: Mapping[str, Any]) -> NormalizedEvent:
    """读路径与写路径共用的规范化口径（与历史 ``load_trees`` 完全一致）。"""
    try:
        recorded_at = float(payload.get("timestamp") or 0.0)
    except (TypeError, ValueError):
        recorded_at = 0.0
    return normalize_event(
        payload,
        storage_scope=str(payload.get("storage_scope") or ""),
        recorded_at=recorded_at,
    )


@dataclass
class _Entry:
    builder: TreeBuilder
    loaded_at: float
    snapshot: Optional[Tuple[TreeBuildResult, EventIndex]] = None
    event_count: int = 0
    # 事件 → 节点别名：重复提交的事件被 TreeBuilder 按幂等键去重、不进 node.event_ids，
    # 但它本身仍属于那个节点；没有别名时按事件 ID 查不到节点，会被误当成历史未知放行
    aliases: Optional[EventIndex] = None


def _default_reader(conversation_id: str) -> Sequence[Mapping[str, Any]]:
    # 调用时再取 read_gate 的读取器：测试只需 patch 那一个点
    from . import read_gate

    return read_gate._default_tree_reader(conversation_id)


class TreeRegistry:
    def __init__(
        self,
        reader: Optional[Reader] = None,
        *,
        refresh_seconds: float = DEFAULT_REFRESH_SECONDS,
        overlay_loader: Optional[OverlayLoader] = None,
        graft_loader: Optional[GraftLoader] = None,
    ) -> None:
        self._reader = reader
        self._overlay_loader = overlay_loader
        self._graft_loader = graft_loader
        self._refresh_seconds = float(refresh_seconds)
        self._entries: Dict[str, _Entry] = {}
        self._lock = threading.RLock()
        self.full_loads = 0  # 观测用：全量建树次数

    # ---- 读 ---------------------------------------------------------------
    def snapshot(self, conversation_id: str) -> Tuple[TreeBuildResult, EventIndex]:
        cid = str(conversation_id or "")
        with self._lock:
            entry = self._entries.get(cid)
            if entry is None or self._expired(entry):
                entry = self._load(cid)
            if entry.snapshot is None:
                tree = entry.builder.build(grafts=self._grafts(cid))
                index = {}
                for event_id, node_id in (entry.aliases or {}).items():
                    node_id = node_id[len(_THOUGHT):] if node_id.startswith(_THOUGHT) else node_id
                    if node_id in tree.nodes:
                        index[event_id] = node_id
                index.update(_event_index(tree))
                entry.snapshot = (tree, index)
            return entry.snapshot

    def tree(self, conversation_id: str) -> TreeBuildResult:
        return self.snapshot(conversation_id)[0]

    # ---- 写 ---------------------------------------------------------------
    def on_append(self, payloads: Iterable[Mapping[str, Any]]) -> None:
        """落盘后的增量更新；只更新已加载的会话，没加载的等首次读时全量建。"""
        with self._lock:
            for payload in payloads:
                if not isinstance(payload, Mapping):
                    continue
                entry = self._entries.get(str(payload.get("conversation_id") or ""))
                if entry is None:
                    continue
                event = normalize_payload(payload)
                entry.builder.add(event)
                _remember_alias(entry, event)
                entry.event_count += 1
                entry.snapshot = None

    def with_known_nodes(self, payloads: Sequence[Mapping[str, Any]]) -> list:
        """给缺节点字段的事件补上树里已知的节点（来自覆盖层回填）；返回副本。

        只在该会话已加载、或存在覆盖文件时才查树，避免为纯历史会话付全量建树的代价。
        """
        items = [dict(payload) for payload in payloads if isinstance(payload, Mapping)]
        wanted: Dict[str, list] = {}
        for item in items:
            if not item.get("client_node_id") and item.get("event_id"):
                wanted.setdefault(str(item.get("conversation_id") or ""), []).append(item)
        for conversation_id, group in wanted.items():
            if not conversation_id or not self._worth_loading(conversation_id, group):
                continue
            tree, index = self.snapshot(conversation_id)
            for item in group:
                node_id = index.get(str(item.get("event_id")))
                if node_id:
                    item["client_node_id"] = node_id
                    item["parent_node_id"] = tree.nodes[node_id].parent_id
        return items

    def _worth_loading(self, conversation_id: str, group: Sequence[Mapping[str, Any]]) -> bool:
        if self.loaded(conversation_id):
            return True
        if self._overlay_loader is None:
            return False
        from .overlay import scope_of

        return bool(self._overlay_loader(conversation_id, scope_of(group, conversation_id)))

    def invalidate(self, conversation_id: str) -> None:
        """嫁接记录变了：下次取快照时重新 build（不重读事件）。"""
        with self._lock:
            entry = self._entries.get(str(conversation_id or ""))
            if entry is not None:
                entry.snapshot = None

    def _grafts(self, conversation_id: str) -> Mapping[str, str]:
        if self._graft_loader is None:
            return {}
        try:
            return self._graft_loader(conversation_id) or {}
        except Exception:  # noqa: BLE001 - 嫁接只是兜底，读不到就按原树
            return {}

    def forget(self, conversation_id: str) -> None:
        with self._lock:
            self._entries.pop(str(conversation_id or ""), None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self.full_loads = 0

    def loaded(self, conversation_id: str) -> bool:
        with self._lock:
            return str(conversation_id or "") in self._entries

    # ---- 内部 -------------------------------------------------------------
    def _expired(self, entry: _Entry) -> bool:
        return self._refresh_seconds > 0 and time.monotonic() - entry.loaded_at > self._refresh_seconds

    def _load(self, conversation_id: str) -> _Entry:
        reader = self._reader or _default_reader
        payloads = [item for item in (reader(conversation_id) or []) if isinstance(item, Mapping)]
        if self._overlay_loader is not None:
            # 历史回填：旁挂覆盖层补节点与结构节点，原始事件不改写
            from .overlay import apply_overlay, scope_of

            scope = scope_of(payloads, conversation_id)
            overlay = self._overlay_loader(conversation_id, scope)
            if overlay:
                payloads = apply_overlay(
                    payloads, overlay, conversation_id=conversation_id, scope=scope
                )
        events = [normalize_payload(payload) for payload in payloads]
        builder = TreeBuilder(conversation_id=conversation_id)
        # 与 build_tree 相同的稳定顺序，减少 pending 重放；正确性不依赖排序
        for event in sorted(events, key=lambda item: (item.occurred_at, item.event_id)):
            builder.add(event)
        entry = _Entry(builder=builder, loaded_at=time.monotonic(), event_count=len(events))
        for event in events:
            _remember_alias(entry, event)
        self._entries[conversation_id] = entry
        self.full_loads += 1
        return entry


def _remember_alias(entry: _Entry, event: NormalizedEvent) -> None:
    if not event.event_id:
        return
    if entry.aliases is None:
        entry.aliases = {}
    if event.client_node_id:
        entry.aliases[event.event_id] = event.client_node_id
    elif event.event_type == "chat_thought" and event.turn_id:
        # 2026-10-26 修复前写入的思考记录没带节点；新事件的 turn_id 就是本轮回复节点，
        # 取快照时若该节点在树里就认回去（_THOUGHT 前缀标记，见 snapshot）
        entry.aliases[event.event_id] = _THOUGHT + event.turn_id


def _event_index(tree: TreeBuildResult) -> EventIndex:
    index: EventIndex = {}
    for node_id, node in tree.nodes.items():
        for event_id in node.event_ids:
            index[str(event_id)] = node_id
    return index


_registry: Optional[TreeRegistry] = None
_registry_lock = threading.Lock()


def get_tree_registry() -> TreeRegistry:
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = TreeRegistry(
                overlay_loader=lambda cid, scope: _default_overlay_loader(cid, scope),
                graft_loader=lambda cid: _default_graft_loader(cid),
            )
        return _registry


def _default_overlay_loader(conversation_id: str, scope: str) -> Optional[Mapping[str, Any]]:
    from .overlay import load_overlay

    return load_overlay(conversation_id, scope)


def _default_graft_loader(conversation_id: str) -> Mapping[str, str]:
    from .cursors import grafts_for

    return grafts_for(conversation_id)


def reset_tree_registry() -> None:
    """测试用：丢弃进程内单例。"""
    global _registry
    with _registry_lock:
        _registry = None


__all__ = ["TreeRegistry", "get_tree_registry", "normalize_payload", "reset_tree_registry"]
