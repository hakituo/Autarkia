"""单个会话的主线整理（WP1 第 2 步）：世界线闸门 → 推断去重 → 去不可提炼 → 合并重复提交。

全部是纯函数（闸门本身只读常驻树 / 游标），不写任何状态；闸门通过「模块.函数」取，
测试可以 monkeypatch。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from memory.topology import inferred, read_gate
from memory.topology.events import (
    TOPOLOGY_COMPLETE,
    TOPOLOGY_PARTIAL,
    TOPOLOGY_UNKNOWN,
    NormalizedEvent,
    normalize_event,
)
from memory.topology.gating import is_content_eligible

_SPACE_RE = re.compile(r"\s+")

TreeReader = Callable[[str], Sequence[Mapping[str, Any]]]


@dataclass
class Mainline:
    """一条会话整理后的主线。``events`` 与 ``normalized`` 一一对应、按时间序。"""

    conversation_id: str
    events: list[dict[str, Any]] = field(default_factory=list)
    normalized: list[NormalizedEvent] = field(default_factory=list)
    aliases: dict[str, str] = field(default_factory=dict)
    gate_reasons: dict[str, int] = field(default_factory=dict)
    last_event_at: float = 0.0
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def topology_status(self) -> str:
        return conversation_topology_status(self.normalized)


def _as_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _turn_of(payload: Mapping[str, Any]) -> str:
    metadata = payload.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    return str(
        payload.get("turn_id") or payload.get("message_id") or metadata.get("message_id") or ""
    ).strip()


def _role(payload: Mapping[str, Any]) -> str:
    return str(payload.get("role") or "").strip().lower()


def is_eligible_payload(payload: Mapping[str, Any]) -> bool:
    """能否进提炼：复用 ``gating`` 的判定（``chat_thought``、空白、媒体占位、debug 都不进）。"""
    return is_content_eligible(
        str(payload.get("content") or ""), event_type=str(payload.get("event_type") or "")
    )


def merge_repeated_submissions(
    events: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """合并**连续**重复提交的同一句用户输入，只保留第一条。

    返回 (保留的事件, 别名 ``被合并 event_id → 保留 event_id``)。被合并那条所在轮的
    后续事件（通常是重新生成后保留的回复）改挂到保留那条的轮上，避免一轮被拆成
    「只有用户」和「只有回复」两个 turn，把轮数虚高。中间夹着助手回复就不算连续。
    """
    kept: list[dict[str, Any]] = []
    aliases: dict[str, str] = {}
    turn_remap: dict[str, str] = {}
    last_user: tuple[dict[str, Any], str] | None = None
    for raw in events:
        payload = dict(raw)
        turn_id = _turn_of(payload)
        if turn_id in turn_remap:
            payload["turn_id"] = turn_remap[turn_id]
        if _role(payload) == "user":
            text = _SPACE_RE.sub("", str(payload.get("content") or ""))
            if last_user is not None and text and text == last_user[1]:
                keeper = last_user[0]
                aliases[str(payload.get("event_id") or "")] = str(keeper.get("event_id") or "")
                keeper_turn = _turn_of(keeper)
                if turn_id and keeper_turn and turn_id != keeper_turn:
                    turn_remap[turn_id] = keeper_turn
                continue
            last_user = (payload, text)
        else:
            last_user = None
        kept.append(payload)
    aliases.pop("", None)
    return kept, aliases


def conversation_topology_status(events: Sequence[NormalizedEvent]) -> str:
    """整条主线的拓扑状态：全 complete / 全 unknown，否则 partial。

    主线是一条 root→leaf 路径，开头那个有节点、没 parent 的事件就是根，按 complete 算；
    其余位置缺 parent 才是真的 partial。
    """
    statuses = {
        TOPOLOGY_COMPLETE
        if index == 0 and event.client_node_id and event.topology_status == TOPOLOGY_PARTIAL
        else event.topology_status
        for index, event in enumerate(events)
    }
    if not statuses or statuses == {TOPOLOGY_UNKNOWN}:
        return TOPOLOGY_UNKNOWN
    if statuses == {TOPOLOGY_COMPLETE}:
        return TOPOLOGY_COMPLETE
    return TOPOLOGY_PARTIAL


def prepare_mainline(
    raw_events: Sequence[Mapping[str, Any]],
    *,
    conversation_id: str,
    tree_reader: TreeReader | None = None,
) -> Mainline:
    """把一个会话的全量原始事件整理成可分段的主线。

    闸门传 ``branch_scope={}``：nightly 不是请求读，不能拿到任何请求上下文里的活跃路径，
    anchor 只走持久化游标（E10）；``tree_reader=None`` 时用常驻树（含覆盖层回填）。
    """
    raw = [dict(item) for item in raw_events if isinstance(item, Mapping)]
    raw.sort(key=lambda item: (_as_float(item.get("timestamp")), str(item.get("event_id") or "")))
    result = Mainline(conversation_id=conversation_id)
    result.last_event_at = max((_as_float(item.get("timestamp")) for item in raw), default=0.0)
    result.counts["raw"] = len(raw)
    if not raw:
        return result
    gated = read_gate.filter_raw_events(
        raw,
        conversation_id=conversation_id,
        branch_scope={},
        tree_reader=tree_reader,
    )
    result.gate_reasons = dict(gated.reasons)
    result.counts["after_gate"] = len(gated.events)
    deduped = inferred.drop_superseded(gated.events)
    result.counts["after_superseded"] = len(deduped)
    eligible = [item for item in deduped if is_eligible_payload(item)]
    result.counts["after_content_gate"] = len(eligible)
    merged, aliases = merge_repeated_submissions(eligible)
    result.counts["merged_repeats"] = len(aliases)
    result.events = merged
    result.aliases = aliases
    result.normalized = [
        normalize_event(
            payload,
            storage_scope=str(payload.get("storage_scope") or ""),
            recorded_at=_as_float(payload.get("timestamp")),
        )
        for payload in merged
    ]
    return result


__all__ = [
    "Mainline",
    "conversation_topology_status",
    "is_eligible_payload",
    "merge_repeated_submissions",
    "prepare_mainline",
]
