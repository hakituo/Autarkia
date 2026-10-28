"""输入管线接分段器 v2（spec §7.1）：切点账本 + 惰性 bge 打分，``inputs`` 按参数选择 v1 / v2。

- 已封口会话（非末尾会话，或末尾会话也已空闲超时）的切点写账本，重放直接读，段号稳定；
- 末尾会话还可能变长：其切点不入账本，它的各段一律算未封口；
- 打分器只在遇到超长且账本未命中的会话时才加载 bge。
"""

from __future__ import annotations

from typing import Any

from memory.topology.segments import Segment
from memory.topology.topic_split import TopicParams, build_topic_segments

from .topic_cuts import CutLedger
from .topic_scorer import EmbeddingScorer


class TopicContext:
    """一次 collect 内共用的账本与打分器（每个 scope 一份）。"""

    def __init__(self, scope: str, *, ledger: CutLedger | None = None, scorer: Any = None):
        self.ledger = ledger if ledger is not None else CutLedger(scope)
        self.scorer = scorer if scorer is not None else EmbeddingScorer()

    def save(self) -> None:
        self.ledger.save()


def topic_params(params: Any) -> TopicParams:
    return TopicParams(
        idle_seconds=float(params.idle_seconds),
        session_max_chars=int(params.session_max_chars),
        min_part_chars=int(params.min_part_chars),
    )


def segment_v2(
    line: Any,
    conversation_id: str,
    continuity_id: str,
    params: Any,
    *,
    context: TopicContext,
    tail_closed: bool,
) -> tuple[list[Segment], int]:
    """返回 (段, 末尾仍开放的段数)。"""
    result = build_topic_segments(
        line.normalized,
        tree_id=conversation_id,
        continuity_id=continuity_id,
        params=topic_params(params),
        scorer=context.scorer,
        lookup=context.ledger.lookup,
        topology_status=line.topology_status,
    )
    for digest, cuts, is_tail in result.sessions:
        if not is_tail or tail_closed:
            context.ledger.record(digest, cuts)
    return result.segments, 0 if tail_closed else result.tail_segments


__all__ = ["TopicContext", "segment_v2", "topic_params"]
