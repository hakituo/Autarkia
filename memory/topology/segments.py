"""确定性分段：只沿一棵 tree 的一条 root→leaf 路径、只在完整 turn 边界切（v3 F1/F2）。

明确不做的事：
- 不按 04:00 / 自然日强断（日记归属是独立日期视图，不切断连续语义）；
- 不因"parent 不在本段"封口（达到上限后正常下一轮也会 parent 跨段）；
- 不把一个批次混上兄弟路径或跨 tree 拼接。

``segment_id`` 由分段器版本 + 有序来源事件 ID 决定，同一路径重复计算得到同一 ID。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from .events import NormalizedEvent

SEGMENTER_VERSION = "1"

MAX_TURNS = "max_turns"
MAX_CHARS = "max_chars"
IDLE = "idle"
PATH_END = "path_end"


@dataclass
class Turn:
    turn_id: str
    events: List[NormalizedEvent] = field(default_factory=list)

    @property
    def started_at(self) -> float:
        return min((event.occurred_at for event in self.events), default=0.0)

    @property
    def ended_at(self) -> float:
        return max((event.occurred_at for event in self.events), default=0.0)

    @property
    def content_length(self) -> int:
        return sum(
            len(str(event.content or "").strip())
            for event in self.events
            if event.content_eligible
        )

    @property
    def eligible(self) -> bool:
        return any(event.content_eligible for event in self.events)


@dataclass
class Segment:
    segment_id: str
    tree_id: str
    continuity_id: str
    source_event_ids: List[str]
    turn_ids: List[str]
    started_at: float
    ended_at: float
    boundary_reason: str
    topology_status: str = "complete"
    char_count: int = 0
    #: 分段器 v2：会话内话题切点之后的段，提取时附带的上一段末尾事件（只供理解，不算来源）
    context_event_ids: List[str] = field(default_factory=list)
    segmenter_version: str = SEGMENTER_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "tree_id": self.tree_id,
            "continuity_id": self.continuity_id,
            "source_event_ids": list(self.source_event_ids),
            "turn_ids": list(self.turn_ids),
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "boundary_reason": self.boundary_reason,
            "topology_status": self.topology_status,
            "char_count": self.char_count,
            "context_event_ids": list(self.context_event_ids),
            "segmenter_version": self.segmenter_version,
        }


def group_turns(events: Iterable[NormalizedEvent]) -> List[Turn]:
    """按 turn_id 分组；没有 turn_id 时按 user→assistant 相邻配对。"""
    ordered = sorted(events, key=lambda item: (item.occurred_at, item.event_id))
    turns: List[Turn] = []
    for event in ordered:
        turn_id = str(event.turn_id or "").strip()
        if turns and turn_id and turns[-1].turn_id == turn_id:
            turns[-1].events.append(event)
            continue
        if (
            turns
            and not turn_id
            and event.speaker_role == "assistant"
            and turns[-1].events
            and turns[-1].events[-1].speaker_role == "user"
            and not turns[-1].turn_id
        ):
            turns[-1].events.append(event)
            continue
        turns.append(Turn(turn_id=turn_id or f"anon:{event.event_id}", events=[event]))
    return turns


def compute_segment_id(
    tree_id: str, event_ids: Iterable[str], *, version: str = SEGMENTER_VERSION
) -> str:
    basis = "|".join([str(version), str(tree_id or ""), *[str(item) for item in event_ids]])
    return "seg_" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def build_segments(
    events: Iterable[NormalizedEvent],
    *,
    tree_id: str = "",
    continuity_id: str = "",
    idle_seconds: float = 1800.0,
    max_turns: int = 40,
    max_chars: int = 8000,
    topology_status: str = "complete",
    include_ineligible: bool = False,
) -> List[Segment]:
    """沿一条路径切段；参数只是候选值，默认值需由回放分布与 A/B 决定。"""
    turns = group_turns(events)
    if not include_ineligible:
        turns = [turn for turn in turns if turn.eligible]
    segments: List[Segment] = []
    current: List[Turn] = []
    current_chars = 0
    pending_reason = PATH_END

    def flush(reason: str) -> None:
        nonlocal current, current_chars
        if not current:
            return
        source_ids = [event.event_id for turn in current for event in turn.events]
        segments.append(
            Segment(
                segment_id=compute_segment_id(tree_id, source_ids),
                tree_id=tree_id,
                continuity_id=continuity_id,
                source_event_ids=source_ids,
                turn_ids=[turn.turn_id for turn in current],
                started_at=current[0].started_at,
                ended_at=current[-1].ended_at,
                boundary_reason=reason,
                topology_status=topology_status,
                char_count=current_chars,
            )
        )
        current = []
        current_chars = 0

    for turn in turns:
        if current:
            gap = turn.started_at - current[-1].ended_at
            if gap > idle_seconds:
                pending_reason = IDLE
            elif len(current) >= max_turns:
                pending_reason = MAX_TURNS
            elif current_chars >= max_chars:
                pending_reason = MAX_CHARS
            else:
                pending_reason = ""
            if pending_reason:
                # 在**新 turn 开始前**封口：上一段始终结束在完整 turn 边界
                flush(pending_reason)
        current.append(turn)
        current_chars += turn.content_length
    flush(PATH_END)
    return segments


def summarize_segments(segments: List[Segment]) -> Dict[str, Any]:
    turn_counts = [len(segment.turn_ids) for segment in segments]
    char_counts = [segment.char_count for segment in segments]
    boundaries: Dict[str, int] = {}
    for segment in segments:
        boundaries[segment.boundary_reason] = boundaries.get(segment.boundary_reason, 0) + 1
    return {
        "segment_count": len(segments),
        "turn_counts": _distribution(turn_counts),
        "char_counts": _distribution(char_counts),
        "boundary_reasons": boundaries,
        "empty_segments": sum(1 for segment in segments if not segment.source_event_ids),
    }


def _distribution(values: List[int]) -> Dict[str, Optional[float]]:
    if not values:
        return {"min": None, "p50": None, "p90": None, "max": None}
    ordered = sorted(values)

    def pick(ratio: float) -> int:
        return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * ratio))]

    return {"min": ordered[0], "p50": pick(0.5), "p90": pick(0.9), "max": ordered[-1]}


@dataclass
class SegmentDiff:
    """两次分段的差异：只有 ``invalidated`` 的派生物需要失效，``added`` 需要重算。"""

    kept: List[str] = field(default_factory=list)
    invalidated: List[str] = field(default_factory=list)
    added: List[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.invalidated or self.added)


def diff_segments(previous: Iterable[Segment], current: Iterable[Segment]) -> SegmentDiff:
    """迟到事件 / 重放后的增量重建（F1）。

    ``segment_id`` 由版本 + 有序来源事件决定，因此来源不变的段 ID 不变、产物可直接复用；
    迟到事件只会改变它落入的段（以及因上限顺延而移位的后续段）。原始事件不改写。
    """
    old_ids = [segment.segment_id for segment in previous]
    new_ids = [segment.segment_id for segment in current]
    old_set, new_set = set(old_ids), set(new_ids)
    return SegmentDiff(
        kept=[item for item in new_ids if item in old_set],
        invalidated=[item for item in old_ids if item not in new_set],
        added=[item for item in new_ids if item not in old_set],
    )
