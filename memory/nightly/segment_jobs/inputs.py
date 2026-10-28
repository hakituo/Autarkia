"""按段提取的输入管线（v3 F3 · WP1）：给定 scope，产出「已封口、未处理」的段。

流程：列出 scope 的会话 → 每个会话读全量事件 → 主线整理（``mainline``）→ 分段 →
封口判定。是否「未处理」由 WP3 用笔记库 ``has_segment`` 判定，这里只负责封口。

封口：除最后一段外都封口；最后一段只有「会话最后一条事件距 now 超过 idle_seconds」
才封口（之后不会再长）。拓扑 unknown / partial 的会话照常产段，状态如实带在
``Segment.topology_status`` 上。
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.utils.logger import get_module_logger
from memory.topology.segments import build_segments

from . import mainline
from .contracts import SegmentInput
from .skip import default_skip_patterns, is_skipped_conversation

logger = get_module_logger(__name__, "nightly_processor.log")


@dataclass(frozen=True)
class SegmentParams:
    """分段参数。``segmenter`` = "v1"（按轮数，现行默认）或 "v2"（交换 + 话题，spec §7.1）。

    v1 的轮数实际约等于消息数（多气泡回复各算一轮），详见 spec §7.1「v1 现状」。
    """

    idle_seconds: float = 1800.0
    max_turns: int = 8
    max_chars: int = 4000
    segmenter: str = "v1"
    session_max_chars: int = 4000
    min_part_chars: int = 300

    @classmethod
    def from_config(cls, config: Mapping[str, Any] | None) -> SegmentParams:
        config = config or {}
        return cls(
            idle_seconds=float(config.get("segment_idle_seconds") or cls.idle_seconds),
            max_turns=int(config.get("segment_max_turns") or cls.max_turns),
            max_chars=int(config.get("segment_max_chars") or cls.max_chars),
            segmenter=str(config.get("segment_segmenter") or _active_segmenter()).strip().lower(),
            session_max_chars=int(config.get("segment_session_max_chars") or cls.session_max_chars),
            min_part_chars=int(config.get("segment_min_part_chars") or cls.min_part_chars),
        )


def _active_segmenter() -> str:
    """与梗概库目录同一个开关（settings ``memory.notes_segmenter``），保证写读一致。"""
    from memory.notes import paths as notes_paths

    return notes_paths.active_segmenter()


#: 没传参数时用的默认分段参数（v1）；运行时按开关取请用 ``SegmentParams.from_config({})``
DEFAULT_PARAMS = SegmentParams()


def build_conversation_inputs(
    scope: str,
    conversation_id: str,
    raw_events: Sequence[Mapping[str, Any]],
    *,
    params: SegmentParams | None = None,
    now: float | None = None,
    tree_reader: mainline.TreeReader | None = None,
    topic_context: Any = None,
) -> list[SegmentInput]:
    """一个会话的全部段（含未封口的最后一段，``closed`` 如实标注）。

    v2 需要 ``topic_context``（切点账本 + 打分器），缺省时按 scope 现建一个。
    """
    params = params or DEFAULT_PARAMS
    stamp = time.time() if now is None else float(now)
    line = mainline.prepare_mainline(
        raw_events, conversation_id=conversation_id, tree_reader=tree_reader
    )
    if not line.normalized:
        return []
    continuity_id = line.normalized[0].continuity_id
    tail_closed = stamp - line.last_event_at > params.idle_seconds
    open_count = 0 if tail_closed else 1
    # tree_id 取会话 ID：根节点集合会随回填 / 嫁接变化，用它算 segment_id 会让整条会话的段全部失效
    if params.segmenter == "v2":
        from .topic_inputs import TopicContext, segment_v2

        own = topic_context is None
        context = topic_context if not own else TopicContext(scope)
        segments, open_count = segment_v2(
            line,
            conversation_id,
            continuity_id,
            params,
            context=context,
            tail_closed=tail_closed,
        )
        if own:
            context.save()
    else:
        segments = build_segments(
            line.normalized,
            tree_id=conversation_id,
            continuity_id=continuity_id,
            idle_seconds=params.idle_seconds,
            max_turns=params.max_turns,
            max_chars=params.max_chars,
            topology_status=line.topology_status,
        )
    by_id = {str(item.get("event_id") or ""): item for item in line.events}
    inputs: list[SegmentInput] = []
    for index, segment in enumerate(segments):
        source = set(segment.source_event_ids)
        aliases = tuple(
            sorted((dropped, kept) for dropped, kept in line.aliases.items() if kept in source)
        )
        inputs.append(
            SegmentInput(
                scope=scope,
                conversation_id=conversation_id,
                segment=segment,
                events=tuple(by_id[eid] for eid in segment.source_event_ids if eid in by_id),
                closed=index < len(segments) - open_count,
                aliases=aliases,
                context_events=tuple(
                    by_id[eid] for eid in segment.context_event_ids if eid in by_id
                ),
                previous_segment_id=(
                    segments[index - 1].segment_id
                    if index and segments[index - 1].boundary_reason == "topic"
                    else ""
                ),
            )
        )
    return inputs


def list_scope_conversations(scope: str, *, skip: Iterable[str] = ()) -> list[str]:
    """该 scope 聊天目录下的会话（文件 stem）；优先用派生索引，不可用时遍历目录。

    目录里可能混着旧版本误放的其他角色会话：能确定属于别的角色的跳过；
    命中 ``skip`` 名单（探针 / 系统问候）的也跳过。
    """
    from core.utils.data import data_paths
    from core.utils.data.scope_registry import matched_persona_scope

    root = Path(data_paths.get_role_chat_history_dir(scope))
    if not root.exists():
        return []
    stems: Iterable[str] = ()
    try:
        from core.services.chat_history_store import ChatHistoryStore

        index = ChatHistoryStore._synced_index(root)
        if index is not None:
            stems = index.distinct_file_stems()
    except Exception as exc:  # noqa: BLE001 - 索引只是派生层，失败退回目录遍历
        logger.debug("读取会话索引失败，改为遍历目录: %s", exc)
    stems = set(stems) or {path.stem for path in root.rglob("*.jsonl")}
    allowed = []
    for stem in sorted(stems):
        if is_skipped_conversation(stem, skip):
            continue
        owner = matched_persona_scope(stem)
        if owner and owner != scope:
            continue
        allowed.append(stem)
    return allowed


def collect_segment_inputs(
    scope: str,
    *,
    params: SegmentParams | None = None,
    now: float | None = None,
    conversations: Sequence[str] | None = None,
    store: Any = None,
    tree_reader: mainline.TreeReader | None = None,
    include_open: bool = False,
    skip_conversations: Sequence[str] | None = None,
) -> list[SegmentInput]:
    """全 scope 的段；默认只返回已封口的段。单个会话失败只跳过该会话。

    不传 ``params`` 时按开关取分段器版本，回填脚本与 nightly 与梗概库目录保持一致。
    ``skip_conversations`` 为空时取 nightly 默认名单（探针 / 系统问候等零信息量会话）。
    """
    params = params or SegmentParams.from_config({})
    skip = tuple(skip_conversations) if skip_conversations is not None else default_skip_patterns()
    from core.utils.data import data_paths

    if store is None:
        from core.services.chat_history_store import ChatHistoryStore

        root = Path(data_paths.get_role_chat_history_dir(scope))
        if not root.exists():
            return []  # 不为一个没有聊天记录的 scope 建空目录
        store = ChatHistoryStore(root)
    cids = list(conversations) if conversations is not None else list_scope_conversations(scope)
    cids = [cid for cid in cids if not is_skipped_conversation(cid, skip)]
    stamp = time.time() if now is None else float(now)
    topic_context = None
    if params.segmenter == "v2":
        from .topic_inputs import TopicContext

        topic_context = TopicContext(scope)
    collected: list[SegmentInput] = []
    for cid in cids:
        try:
            raw = store.list_conversation_events(cid, limit=0)
            conversation_id = _payload_conversation_id(raw) or cid
            items = build_conversation_inputs(
                scope,
                conversation_id,
                raw,
                params=params,
                now=stamp,
                tree_reader=tree_reader,
                topic_context=topic_context,
            )
        except Exception as exc:  # noqa: BLE001 - 一个会话坏数据不拖垮整轮
            logger.warning("会话分段失败，已跳过: %s (%s)", cid, type(exc).__name__)
            continue
        collected.extend(item for item in items if include_open or item.closed)
    if topic_context is not None:
        topic_context.save()
    return collected


def _payload_conversation_id(raw: Sequence[Mapping[str, Any]]) -> str:
    for item in raw:
        cid = str(item.get("conversation_id") or "").strip() if isinstance(item, Mapping) else ""
        if cid:
            return cid
    return ""


def summarize_inputs(inputs: Sequence[SegmentInput]) -> dict[str, Any]:
    """只含计数的摘要（验证脚本 ``--live`` 用，不含任何正文）。"""
    turns = sorted(len(item.segment.turn_ids) for item in inputs)
    statuses: dict[str, int] = {}
    for item in inputs:
        key = item.segment.topology_status
        statuses[key] = statuses.get(key, 0) + 1

    def pick(ratio: float) -> int | None:
        return turns[min(len(turns) - 1, int((len(turns) - 1) * ratio))] if turns else None

    return {
        "conversations": len({item.conversation_id for item in inputs}),
        "segments": len(inputs),
        "closed": sum(1 for item in inputs if item.closed),
        "turns": {"min": pick(0.0), "p50": pick(0.5), "p90": pick(0.9), "max": pick(1.0)},
        "topology_status": dict(sorted(statuses.items())),
        "merged_repeats": sum(len(item.aliases) for item in inputs),
    }


__all__ = [
    "DEFAULT_PARAMS",
    "SegmentParams",
    "build_conversation_inputs",
    "collect_segment_inputs",
    "is_skipped_conversation",
    "list_scope_conversations",
    "summarize_inputs",
]
