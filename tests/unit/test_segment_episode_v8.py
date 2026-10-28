"""提取器 v8：梗概重要度、短事实 / 偏好 / 计划、关思考；下游：信号按段合并、检索标签与时间段。"""

from __future__ import annotations

import asyncio
import json

from core.llm.openai_compat.deepseek_client import DeepSeekClient
from core.tools import memory_notes_search
from memory.nightly.segment_jobs.contracts import NoteDraft
from memory.nightly.segment_jobs.episode import EpisodeExtractor
from memory.nightly.segment_jobs.episode_parse import (
    IMPORTANCE_LEVELS,
    MAX_FACTS,
    parse_facts,
    parse_topic_items,
)
from memory.nightly.segment_jobs.inputs import SegmentParams, build_conversation_inputs
from memory.notes import NoteStore, paths
from memory.notes.signals import collect_note_signals

CONV = "web_role_aveline"
PERSPECTIVE = {"role_id": "aveline", "role_name": "Aveline", "user_name": "Master", "role_profile": ""}


class _Scheduler:
    def __init__(self, reply):
        self.reply, self.kwargs = reply, []

    async def submit_llm_task(self, prompt, **kwargs):
        self.kwargs.append(kwargs)
        yield self.reply


def _item():
    spec = [("user", "下周三我去成都出差"), ("assistant", "记得早睡"), ("user", "我戒奶茶了")]
    events = [
        {
            "event_id": f"e{i}",
            "conversation_id": CONV,
            "role": role,
            "content": text,
            "timestamp": 1000.0 + 60 * i,
            "message_id": f"m{i}",
        }
        for i, (role, text) in enumerate(spec)
    ]
    return build_conversation_inputs(
        "aveline",
        CONV,
        events,
        params=SegmentParams(segmenter="v1"),
        now=10**8,
        tree_reader=lambda _cid: events,
    )[0]


def test_parse_topic_items_maps_importance_levels():
    text = json.dumps(
        {
            "topics": [
                {"ids": [0], "summary": "甲", "importance": 3},
                {"ids": [1], "summary": "乙", "importance": "9"},
                {"ids": [1], "summary": "丙"},
            ]
        }
    )
    items, skip = parse_topic_items(text, 2)
    assert skip == "" and [i[2] for i in items] == [0.8, 0.8, IMPORTANCE_LEVELS[2]]


def test_parse_facts_keeps_only_grounded_known_kinds():
    facts = [
        {"ids": [0], "kind": "plan", "text": "他下周三去成都"},
        {"ids": [0], "kind": "plan", "text": "他下周三去成都"},
        {"ids": [], "kind": "fact", "text": "没有编号"},
        {"ids": [1], "kind": "opinion", "text": "未知类型"},
        {"ids": [1], "kind": "fact", "text": "长" * 200},
    ] + [{"ids": [1], "kind": "preference", "text": f"喜欢{i}"} for i in range(9)]
    picked = parse_facts(json.dumps({"facts": facts}, ensure_ascii=False), 2)
    assert picked[0] == ("plan", [0], "他下周三去成都") and len(picked) == MAX_FACTS
    assert parse_facts("不是 JSON", 2) == []


def test_extractor_writes_importance_and_fact_notes_without_thinking():
    reply = json.dumps(
        {
            "topics": [{"ids": [0], "summary": "他说下周三去成都出差。", "importance": 3}],
            "facts": [
                {"ids": [0], "kind": "plan", "text": "Master下周三去成都出差"},
                {"ids": [1], "kind": "fact", "text": "Master在戒奶茶"},
            ],
            "skip": "",
            "people": [],
            "role_updates": [],
        },
        ensure_ascii=False,
    )
    scheduler = _Scheduler(reply)
    extractor = EpisodeExtractor(
        scheduler_provider=lambda: scheduler,
        model_hint="cloud:deepseek:deepseek-chat",
        perspective_for_scope=lambda _s: PERSPECTIVE,
        persona_prefix_for_scope=lambda _s: "你是Aveline。",
    )
    result = asyncio.run(extractor.extract(_item()))
    kinds = [(n.kind, n.source_event_ids, n.importance) for n in result.notes]
    assert kinds == [
        ("episode", ("e0", "e1"), 0.8),
        ("plan", ("e0", "e1"), 0.5),
        ("fact", ("e2",), 0.5),
    ]
    assert result.notes[2].metadata == {"occurred_from": 1120.0, "occurred_to": 1120.0}
    assert "profile_signal_analyzed" not in result.notes[1].metadata
    assert scheduler.kwargs[0]["thinking_enabled"] is False


def test_note_signals_merge_once_per_segment(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "notes_dir", lambda scope: tmp_path / scope / "notes")
    signal = {"profile_signal_analyzed": True, "people_mentions": ["妈妈"]}
    drafts = [
        NoteDraft(kind="episode", text="甲", source_event_ids=("e1",), metadata=signal),
        NoteDraft(kind="episode", text="乙", source_event_ids=("e2",), metadata=signal),
        NoteDraft(kind="fact", text="丙", source_event_ids=("e3",)),
    ]
    NoteStore("aveline").replace_segment(
        CONV, "seg", "segment-episode-8", drafts, segment_source_event_ids=("e1", "e2", "e3"),
        occurred_to=5000.0,
    )
    signals = collect_note_signals("aveline", last_processed_ts=100.0)
    assert signals["analyzed_count"] == 1 and len(signals["people"]) == 1
    assert signals["people"][0]["event_ids"] == ["e1", "e2", "e3"]
    assert signals["people"][0]["hints"] == ["妈妈"]


def test_note_label_shows_kind_and_time_range():
    from core.utils.time_utils import format_timestamp

    start = 1_760_000_000.0
    day = format_timestamp(start, "%m-%d %H:%M")
    end_clock = format_timestamp(start + 1200, "%H:%M")
    label = memory_notes_search.note_label
    assert label({"category": "plan", "timestamp": start, "occurred_to": start + 1200}) == (
        f"[计划] [{day}–{end_clock}]"
    )
    assert label({"category": "episode", "timestamp": start, "occurred_to": start}) == (
        f"[梗概] [{day}]"
    )
    assert label({"category": "fact"}) == "[事实]"


def test_deepseek_thinking_can_be_disabled_per_call():
    client = DeepSeekClient(api_key="test", thinking_enabled=True)
    messages = [{"role": "user", "content": "hi"}]
    off = client._build_payload(messages, stream=False, thinking_enabled=False)
    assert off["thinking"] == {"type": "disabled"} and "reasoning_effort" not in off
    on = client._build_payload(messages, stream=False)
    # 顶层字段（裸 HTTP 不展开 extra_body）：开启时同样显式写出，配置关思考时真正关掉
    assert on["thinking"] == {"type": "enabled"} and "extra_body" not in on
    configured_off = DeepSeekClient(api_key="test", thinking_enabled=False)
    assert configured_off._build_payload(messages, stream=False)["thinking"] == {"type": "disabled"}


def test_exchange_headers_carry_date_for_relative_time(monkeypatch):
    from datetime import datetime, timedelta, timezone

    from core.utils import time_utils
    from memory.nightly.segment_jobs.prompts import TASK_INSTRUCTION, build_messages, exchange_time

    shanghai = timezone(timedelta(hours=8))  # 固定时区，不随机器 / 配置变化
    monkeypatch.setattr(
        time_utils, "format_timestamp",
        lambda ts, fmt="%Y-%m-%d %H:%M:%S": datetime.fromtimestamp(ts, shanghai).strftime(fmt),
    )

    assert exchange_time([{"timestamp": 1761552000}]) == "（10月27日 周一 16:00）"
    assert exchange_time([{"timestamp": 0}]) == ""
    events = [{"role": "user", "content": "明天要回老家", "timestamp": 1761552000}]
    _system, user = (m["content"] for m in build_messages(events, PERSPECTIVE))
    assert "［0］（10月27日 周一 16:00）" in user
    assert "昨天（9月26日）" in TASK_INSTRUCTION  # 相对时间括号注明具体日期
