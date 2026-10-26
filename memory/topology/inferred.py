"""第二档回填：没有消息树的历史，按「连续相同用户输入」推断重新生成（v3 D8）。

Android 重新生成一轮回复时会把同一句用户输入再提交一次，服务端线性追加，于是
同一位置出现多轮「用户输入相同、回复不同」。规则：

- 按 ``message_id`` 把事件分成轮，按时间排序；
- 相邻几轮的用户正文（去空白后）完全相同、间隔不超过 ``max_gap_seconds`` → 同一位置；
- 只保留最后一轮，前面各轮的回复 / 思考标为被取代（``superseded_by`` 指向保留轮）；
  用户那句话复用同一节点，仍算主线。

推断结果**不是拓扑**：不写节点 ID、不进 strict 判定，只给提炼 / 去重这类
「宁可少用一份」的场景用。准确率由手机窗口内的真实树校验（见 tests 与审计脚本）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence

DEFAULT_MAX_GAP_SECONDS = 30 * 60
_SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class InferredTurn:
    turn_id: str
    started_at: float
    user_text: str
    event_ids: tuple


@dataclass(frozen=True)
class Superseded:
    turn_id: str
    superseded_by: str
    run_size: int


def _normalize(text: str) -> str:
    return _SPACE_RE.sub("", str(text or ""))


def group_turns(events: Iterable[Mapping[str, Any]]) -> List[InferredTurn]:
    buckets: Dict[str, List[Mapping[str, Any]]] = {}
    for event in events:
        turn_id = str(event.get("message_id") or event.get("turn_id") or event.get("event_id") or "")
        if turn_id:
            buckets.setdefault(turn_id, []).append(event)
    turns: List[InferredTurn] = []
    for turn_id, items in buckets.items():
        users = [item for item in items if str(item.get("role") or "").lower() == "user"]
        turns.append(
            InferredTurn(
                turn_id=turn_id,
                started_at=min(float(item.get("timestamp") or 0.0) for item in items),
                user_text=_normalize(users[0].get("content")) if users else "",
                event_ids=tuple(str(item.get("event_id") or "") for item in items),
            )
        )
    turns.sort(key=lambda turn: (turn.started_at, turn.turn_id))
    return turns


def infer_regenerations(
    events: Sequence[Mapping[str, Any]],
    *,
    max_gap_seconds: float = DEFAULT_MAX_GAP_SECONDS,
) -> Dict[str, Superseded]:
    """返回 ``被取代轮 turn_id -> Superseded``；没有用户输入的轮（主动消息）打断连续段。"""
    turns = group_turns(events)
    marks: Dict[str, Superseded] = {}
    run: List[InferredTurn] = []

    def close() -> None:
        if len(run) > 1:
            keeper = run[-1].turn_id
            for turn in run[:-1]:
                marks[turn.turn_id] = Superseded(turn.turn_id, keeper, len(run))

    for turn in turns:
        same = (
            run
            and turn.user_text
            and turn.user_text == run[-1].user_text
            and turn.started_at - run[-1].started_at <= max_gap_seconds
        )
        if same:
            run.append(turn)
            continue
        close()
        run = [turn] if turn.user_text else []
    close()
    return marks


def superseded_event_ids(
    events: Sequence[Mapping[str, Any]], **kwargs: Any
) -> set:
    """被取代轮里的回复 / 思考事件。

    用户那句话在树上是同一个节点（重新生成复用它），本身仍在主线上，不标；
    被取代的只是那一轮的回复。
    """
    marks = infer_regenerations(events, **kwargs)
    return {
        str(event.get("event_id") or "")
        for event in events
        if str(event.get("message_id") or event.get("turn_id") or "") in marks
        and str(event.get("role") or "").lower() != "user"
    }


def drop_superseded(events: Sequence[Mapping[str, Any]], **kwargs: Any) -> List[Dict[str, Any]]:
    """提炼输入去重：去掉推断为被重新生成取代的轮。"""
    dropped = superseded_event_ids(events, **kwargs)
    return [dict(event) for event in events if str(event.get("event_id") or "") not in dropped]


__all__ = [
    "DEFAULT_MAX_GAP_SECONDS",
    "InferredTurn",
    "Superseded",
    "drop_superseded",
    "group_turns",
    "infer_regenerations",
    "superseded_event_ids",
]
