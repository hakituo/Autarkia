"""分段器 v2：以「交换」为单位、空闲硬切、长会话按话题深度递归二分（spec §7.1）。

- 交换 = 连续用户消息 + 紧随的连续助手消息，不看 ``turn_id``（多气泡回复各有 message_id，
  按 turn 计数会把问和答切开）；相邻消息间隔超过 idle 也断开交换。
- 会话 = 被空闲（> idle 秒）分隔的连续交换；空闲是唯一硬边界。
- 会话正文 ≤ ``session_max_chars`` 整段一段；超出时在交换边界递归二分：候选切点两侧各
  ≥ ``min_part_chars``，取话题深度分最高处（分数由调用方注入，见 ``segment_jobs.topic_cuts``）。
- 本模块是纯函数，不读文件、不加载模型；切点缓存（账本）与向量打分在调用方。
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from .events import NormalizedEvent
from .segments import IDLE, MAX_CHARS, PATH_END, Segment, compute_segment_id

SEGMENTER_V2 = "2"
TOPIC = "topic"
MAX_EXCHANGES = "max_exchanges"

Unit = list[NormalizedEvent]
#: (本次待切的连续单元, 切点下标 i：新部分从 units[i] 开始) -> 话题深度分，越大越像换话题
Scorer = Callable[[Sequence[Unit], int], float]
#: (会话摘要, 会话单元) -> 切点（新部分首事件的 event_id 列表）；None 表示没有缓存
CutLookup = Callable[[str, Sequence[Unit]], "list[str] | None"]


@dataclass(frozen=True)
class TopicParams:
    idle_seconds: float = 1800.0
    session_max_chars: int = 4000
    min_part_chars: int = 300
    max_exchanges: int = 80
    exchange_split_chars: int = 8000
    context_exchanges: int = 2
    context_max_chars: int = 600


@dataclass
class TopicSegmentation:
    segments: list[Segment] = field(default_factory=list)
    #: 每个会话一项：(会话摘要, 本会话的切点, 本会话是否为末尾会话)
    sessions: list[tuple[str, list[str], bool]] = field(default_factory=list)
    #: 末尾会话（可能还会长）占用的段数，即 ``segments`` 的最后 N 段
    tail_segments: int = 0


def chars_of(unit: Sequence[NormalizedEvent]) -> int:
    return sum(len(str(event.content or "").strip()) for event in unit)


def build_units(events: Sequence[NormalizedEvent], params: TopicParams) -> list[Unit]:
    """可提炼事件按 (时间, event_id) 排序后组成交换；超长交换在消息边界拆开。"""
    ordered = sorted(
        (event for event in events if event.content_eligible),
        key=lambda item: (item.occurred_at, item.event_id),
    )
    units: list[Unit] = []
    for event in ordered:
        current = units[-1] if units else None
        new_turn = (
            current is not None
            and event.speaker_role == "user"
            and current[-1].speaker_role != "user"
        )
        too_late = current is not None and event.occurred_at - current[-1].occurred_at > (
            params.idle_seconds
        )
        if current is None or new_turn or too_late:
            units.append([event])
        else:
            current.append(event)
    result: list[Unit] = []
    for unit in units:
        if chars_of(unit) <= params.exchange_split_chars or len(unit) < 2:
            result.append(unit)
            continue
        chunk: Unit = []
        for event in unit:  # 单个交换过长：按消息贪心装箱，每块不超过会话上限
            if chunk and chars_of(chunk) + chars_of([event]) > params.session_max_chars:
                result.append(chunk)
                chunk = []
            chunk.append(event)
        result.append(chunk)
    return result


def split_sessions(units: Sequence[Unit], idle_seconds: float) -> list[list[Unit]]:
    sessions: list[list[Unit]] = []
    for unit in units:
        if sessions and unit[0].occurred_at - sessions[-1][-1][-1].occurred_at <= idle_seconds:
            sessions[-1].append(unit)
        else:
            sessions.append([unit])
    return sessions


def session_digest(conversation_id: str, session: Sequence[Unit]) -> str:
    ids = [event.event_id for unit in session for event in unit]
    basis = "|".join([SEGMENTER_V2, str(conversation_id or ""), *ids])
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def choose_cuts(session: Sequence[Unit], params: TopicParams, scorer: Scorer | None) -> list[int]:
    """返回切点下标（升序）。分数取 3 位小数，平局取更近中点、再取更靠前，保证可重放。"""
    cuts: list[int] = []

    def split(lo: int, hi: int) -> None:
        part = session[lo:hi]
        total = sum(chars_of(unit) for unit in part)
        if hi - lo < 2 or (total <= params.session_max_chars and hi - lo <= params.max_exchanges):
            return
        prefix = [0]
        for unit in part:
            prefix.append(prefix[-1] + chars_of(unit))
        floor = params.min_part_chars
        candidates = [
            i for i in range(1, hi - lo) if prefix[i] >= floor and total - prefix[i] >= floor
        ]
        if not candidates:
            candidates = list(range(1, hi - lo))
        over_chars = total > params.session_max_chars

        def key(i: int) -> tuple[float, float, int]:
            depth = round(float(scorer(part, i)), 3) if (scorer and over_chars) else 0.0
            return (depth, -abs(prefix[i] - total / 2), -i)

        best = max(candidates, key=key)
        cuts.append(lo + best)
        split(lo, lo + best)
        split(lo + best, hi)

    split(0, len(session))
    return sorted(cuts)


def _context(previous: Sequence[Unit], params: TopicParams) -> list[str]:
    picked: list[NormalizedEvent] = []
    budget = params.context_max_chars
    for unit in reversed(list(previous)[-params.context_exchanges :]):
        for event in reversed(unit):
            size = len(str(event.content or "").strip())
            if size > budget:
                return [event.event_id for event in reversed(picked)]
            picked.append(event)
            budget -= size
    return [event.event_id for event in reversed(picked)]


def build_topic_segments(
    events: Sequence[NormalizedEvent],
    *,
    tree_id: str = "",
    continuity_id: str = "",
    params: TopicParams | None = None,
    scorer: Scorer | None = None,
    lookup: CutLookup | None = None,
    topology_status: str = "complete",
) -> TopicSegmentation:
    """沿一条路径按 v2 规则分段。``lookup`` 命中缓存切点时不调用 ``scorer``。"""
    params = params or TopicParams()
    sessions = split_sessions(build_units(events, params), params.idle_seconds)
    result = TopicSegmentation()
    for index, session in enumerate(sessions):
        is_tail = index == len(sessions) - 1
        digest = session_digest(tree_id, session)
        cached = lookup(digest, session) if lookup else None
        firsts = {unit[0].event_id: position for position, unit in enumerate(session)}
        if cached is not None and all(eid in firsts for eid in cached):
            cut_positions = sorted(firsts[eid] for eid in cached)
        else:
            prepare = getattr(scorer, "prepare", None)
            if prepare and sum(map(chars_of, session)) > params.session_max_chars:
                prepare(session)  # 打分器支持批量预编码时，整次会话一次编码
            cut_positions = choose_cuts(session, params, scorer)
        cut_ids = [session[position][0].event_id for position in cut_positions]
        result.sessions.append((digest, cut_ids, is_tail))
        bounds = [0, *cut_positions, len(session)]
        before = len(result.segments)
        for part_index in range(len(bounds) - 1):
            part = session[bounds[part_index] : bounds[part_index + 1]]
            last_part = part_index == len(bounds) - 2
            if not last_part:
                reason = TOPIC  # 会话内切点（话题深度 / 交换数安全上限都记为 topic）
            else:
                reason = PATH_END if is_tail else IDLE
            source = [event.event_id for unit in part for event in unit]
            context = _context(session[: bounds[part_index]], params) if part_index else []
            result.segments.append(
                Segment(
                    segment_id=compute_segment_id(tree_id, source, version=SEGMENTER_V2),
                    tree_id=tree_id,
                    continuity_id=continuity_id,
                    source_event_ids=source,
                    turn_ids=[unit[0].event_id for unit in part],
                    started_at=part[0][0].occurred_at,
                    ended_at=max(event.occurred_at for unit in part for event in unit),
                    boundary_reason=reason,
                    topology_status=topology_status,
                    char_count=sum(chars_of(unit) for unit in part),
                    context_event_ids=context,
                    segmenter_version=SEGMENTER_V2,
                )
            )
        if is_tail:
            result.tail_segments = len(result.segments) - before
    return result


__all__ = [
    "MAX_CHARS",
    "MAX_EXCHANGES",
    "SEGMENTER_V2",
    "TOPIC",
    "TopicParams",
    "TopicSegmentation",
    "build_topic_segments",
    "build_units",
    "choose_cuts",
    "session_digest",
    "split_sessions",
]
