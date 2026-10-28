"""提取器 v7：按话题分条映射来源、前文只供理解、画像信号随梗概落盘并接入人物档案门控。"""

from __future__ import annotations

import asyncio
import json

import pytest

from core.character.people.signal_gate import PeopleProfileSignalGate
from memory.nightly.segment_jobs.contracts import NoteDraft
from memory.nightly.segment_jobs.episode import EpisodeExtractor
from memory.nightly.segment_jobs.episode_parse import (
    MAX_TOPICS,
    EpisodeParseError,
    parse_signals,
    parse_topics,
)
from memory.nightly.segment_jobs.inputs import SegmentParams, build_conversation_inputs
from memory.nightly.segment_jobs.prompts import build_messages, summary_length_hint
from memory.notes import NoteStore, paths
from memory.notes.signals import collect_note_signals

CONV = "web_role_aveline"
PERSPECTIVE = {"role_id": "aveline", "role_name": "Aveline", "user_name": "Master", "role_profile": ""}


def _route_notes(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "notes_dir", lambda scope: tmp_path / scope / "notes")


def test_length_hint_only_for_very_short_segments():
    assert summary_length_hint(40) == "（这段原文只有 40 字，只写一两句，不超过 40 字）"
    assert summary_length_hint(500) == ""


def test_context_is_marked_as_reference_only_and_items_are_numbered_by_exchange():
    events = [
        {"role": "user", "content": "那个后来怎么样了"},
        {"role": "assistant", "content": "还在等"},
        {"role": "assistant", "content": "下周出结果"},
        {"role": "user", "content": "好"},
    ]
    context = [{"role": "user", "content": "我在看房子"}, {"role": "assistant", "content": "嗯"}]
    _system, user = (
        m["content"] for m in build_messages(events, PERSPECTIVE, context_events=context)
    )
    head, _sep, body = user.partition("这是你和Master的一段真实聊天记录")
    assert "前文（只供理解指代" in head and "我在看房子" in head
    assert "我在看房子" not in body and "共 2 次往来" in body
    assert body.index("［0］") < body.index("下周出结果") < body.index("［1］")


def test_parse_topics_maps_ids_and_falls_back_safely():
    text = json.dumps(
        {"topics": [{"ids": [1, 9], "summary": "乙"}, {"ids": [], "summary": "整段"}], "skip": ""},
        ensure_ascii=False,
    )
    assert parse_topics(text, 3) == ([([1], "乙"), ([0, 1, 2], "整段")], "")
    assert parse_topics('{"summary": "旧格式", "skip": ""}', 2) == ([([0, 1], "旧格式")], "")
    assert parse_topics('{"topics": [], "skip": "no_reusable_info"}', 2) == ([], "no_reusable_info")
    many = json.dumps({"topics": [{"ids": [0], "summary": str(i)} for i in range(30)]})
    assert len(parse_topics(many, 1)[0]) == MAX_TOPICS
    with pytest.raises(EpisodeParseError):
        parse_topics('{"topics": [], "skip": ""}', 2)


def test_parse_signals_accepts_lists_and_marks_missing_as_unanalyzed():
    text = json.dumps(
        {"summary": "x", "skip": "", "people": ["妈妈", "", "妈妈"], "role_updates": []}
    )
    assert parse_signals(text) == {
        "profile_signal_analyzed": True,
        "people_mentions": ["妈妈"],
        "role_update_candidates": [],
    }
    assert parse_signals('{"summary": "x", "skip": ""}')["profile_signal_analyzed"] is False


class _Scheduler:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    async def submit_llm_task(self, prompt, **kwargs):
        self.calls.append(prompt)
        yield self.reply


def test_extractor_writes_one_note_per_topic_with_its_own_sources(monkeypatch, tmp_path):
    _route_notes(monkeypatch, tmp_path)
    spec = [
        ("user", "我妈让我周末回家吃饭"),
        ("assistant", "好呀"),
        ("user", "显卡到了"),
        ("assistant", "恭喜"),
        ("assistant", "试试跑分"),
    ]
    events = [
        {
            "event_id": f"e{i}",
            "conversation_id": CONV,
            "role": role,
            "content": text,
            "timestamp": 1000.0 + i,
            "message_id": f"m{i}",
        }
        for i, (role, text) in enumerate(spec)
    ]
    item = build_conversation_inputs(
        "aveline",
        CONV,
        events,
        params=SegmentParams(segmenter="v1"),
        now=10**8,
        tree_reader=lambda _cid: events,
    )[0]
    reply = json.dumps(
        {
            "topics": [
                {"ids": [0], "summary": "他说妈妈让他周末回家吃饭。"},
                {"ids": [1], "summary": "他的显卡到了，我让他跑个分。"},
            ],
            "skip": "",
            "people": ["妈妈"],
            "role_updates": [],
        },
        ensure_ascii=False,
    )
    extractor = EpisodeExtractor(
        scheduler_provider=lambda: _Scheduler(reply),
        perspective_for_scope=lambda _s: PERSPECTIVE,
        persona_prefix_for_scope=lambda _s: "你是Aveline。",
    )
    result = asyncio.run(extractor.extract(item))
    assert [n.source_event_ids for n in result.notes] == [("e0", "e1"), ("e2", "e3", "e4")]
    store = NoteStore("aveline")
    store.replace_segment(
        CONV,
        item.segment_id,
        result.extractor_version,
        result.notes,
        segment_source_event_ids=item.segment.source_event_ids,
        occurred_to=2000.0,
    )
    notes = store.list_notes(CONV)
    assert len(notes) == 2 and all(n["people_mentions"] == ["妈妈"] for n in notes)
    assert store.has_segment(CONV, item.segment_id, result.extractor_version)


def test_note_signals_feed_people_gate_by_source_event(monkeypatch, tmp_path):
    _route_notes(monkeypatch, tmp_path)
    store = NoteStore("aveline")
    draft = NoteDraft(
        kind="episode",
        text="他说妈妈来了。",
        source_event_ids=("e7", "e8"),
        metadata={
            "profile_signal_analyzed": True,
            "people_mentions": ["妈妈"],
            "role_update_candidates": [],
        },
    )
    store.replace_segment(
        CONV,
        "seg_x",
        "segment-episode-6",
        [draft],
        segment_source_event_ids=("e7", "e8"),
        occurred_to=5000.0,
    )
    signals = collect_note_signals("aveline", last_processed_ts=100.0)
    assert signals["analyzed_count"] == 1 and signals["people"][0]["event_ids"] == ["e7", "e8"]
    assert collect_note_signals("aveline", last_processed_ts=6000.0)["people"] == []

    hit = [{"event_id": "e8", "conversation_id": CONV, "timestamp": 1.0, "content": "无关"}]
    miss = [{"event_id": "e9", "conversation_id": CONV, "timestamp": 1.0, "content": "无关"}]
    gate = PeopleProfileSignalGate
    assert gate._matches_distillation_signal(hit, signals["people"])
    assert not gate._matches_distillation_signal(miss, signals["people"])

    class _Manager:
        def __init__(self) -> None:
            self.storage_scope = "aveline"
            self.weighted_memories: dict = {}

    collected = gate.collect({"shared__persona__core_aveline": _Manager()}, 100.0)
    assert collected["analyzed_count"] == 1 and collected["people"]


def test_each_topic_note_carries_its_own_time_span(monkeypatch, tmp_path):
    _route_notes(monkeypatch, tmp_path)
    draft_a = NoteDraft(
        kind="episode",
        text="早上的事",
        source_event_ids=("e1",),
        metadata={"occurred_from": 1000.0, "occurred_to": 1100.0},
    )
    draft_b = NoteDraft(kind="episode", text="没有自带时间", source_event_ids=("e2",))
    store = NoteStore("aveline")
    store.replace_segment(
        CONV,
        "seg_t",
        "segment-episode-7",
        [draft_a, draft_b],
        segment_source_event_ids=("e1", "e2"),
        occurred_from=900.0,
        occurred_to=5000.0,
    )
    times = {n["text"]: (n["occurred_from"], n["occurred_to"]) for n in store.list_notes(CONV)}
    assert times == {"早上的事": (1000.0, 1100.0), "没有自带时间": (900.0, 5000.0)}
