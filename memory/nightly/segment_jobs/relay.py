"""接力切分（提取器 v10）：长对话在话题中间被切开时，没聊完的话题交给下一段一起整理。

- 只有「本段之后同一次对话还在继续」（``SegmentInput.continues``）的段才允许交出：模型给最后
  一个话题标 ``"open": true``，且该话题覆盖到本段最后一次往来，本段就不写这个话题；
- 交出的往来不超过 ``CARRY_MAX_CHARS`` 字，超了就在本段照常写掉，防止越滚越长；
- 下一段提取时把交来的往来并进开头，一起作为本段来源（证据校验口径 ``allowed_sources``）；
- 调用次数不变，只是同一次对话的几段要按顺序处理：编排层先跑上一段再跑下一段，
  不同对话之间照常并行。交出的往来记在笔记库的段条目里（``carry_event_ids``），跨夜也接得上。
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .contracts import SegmentInput

CARRY_MAX_CHARS = 3000


def with_carry(item: SegmentInput, store: Any, items_by_id: Mapping[str, SegmentInput]) -> SegmentInput:
    """上一段交来了往来就并进本段开头；没有接力时原样返回。"""
    previous = items_by_id.get(item.previous_segment_id) if item.previous_segment_id else None
    if previous is None:
        return item
    carry = set(store.get_carry(item.conversation_id, previous.segment_id))
    if not carry:
        return item
    carried = tuple(event for event in previous.events if str(event.get("event_id")) in carry)
    if not carried:
        return item
    carried_ids = tuple(str(event.get("event_id")) for event in carried)
    return dataclasses.replace(
        item,
        events=(*carried, *item.events),
        carried_event_ids=carried_ids,
        context_events=tuple(
            e for e in item.context_events if str(e.get("event_id")) not in set(carried_ids)
        ),
    )


def carry_start(
    open_ids: Iterable[int], exchanges: Sequence[Sequence[Mapping[str, Any]]]
) -> int | None:
    """没聊完的话题从第几次往来开始交出；不满足条件（没覆盖到末尾 / 太长）返回 None。"""
    ids = sorted(set(open_ids))
    last = len(exchanges) - 1
    if not ids or ids[-1] != last or ids[0] < 0:
        return None  # 必须覆盖到最后一次往来；整段都没聊完就整段交出（本段记 carried_forward）
    chars = sum(len(str(e.get("content") or "")) for ex in exchanges[ids[0] :] for e in ex)
    return ids[0] if chars <= CARRY_MAX_CHARS else None


def ordered_chains(items: Sequence[SegmentInput]) -> list[list[SegmentInput]]:
    """按「上一段 → 下一段」串成链：链内必须顺序跑，链与链之间可以并行。"""
    present = {item.segment_id: item for item in items}
    chains: dict[str, list[SegmentInput]] = {}
    head_of: dict[str, str] = {}
    for item in sorted(items, key=lambda i: (i.segment.started_at, i.segment_id)):
        head = head_of.get(item.previous_segment_id) if item.previous_segment_id in present else None
        head = head or item.segment_id
        head_of[item.segment_id] = head
        chains.setdefault(head, []).append(item)
    return list(chains.values())


__all__ = ["CARRY_MAX_CHARS", "carry_start", "ordered_chains", "with_carry"]
