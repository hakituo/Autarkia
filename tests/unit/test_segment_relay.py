"""提取器 v10：接力切分（没聊完的话题交给下一段）与 DeepSeek 不思考 → 思考的重试顺序。"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import threading

import pytest

from memory.nightly.segment_jobs import relay
from memory.nightly.segment_jobs import run as seg_run
from memory.nightly.segment_jobs.contracts import ExtractionResult, NoteDraft
from memory.nightly.segment_jobs.episode import EpisodeExtractor, EpisodeParseError
from memory.nightly.segment_jobs.inputs import SegmentParams, build_conversation_inputs
from memory.nightly.segment_jobs.prompts import CARRIED_HINT, CONTINUES_HINT
from memory.notes import NoteStore, paths

CONV = "web_role_aveline"
PERSPECTIVE = {"role_id": "aveline", "role_name": "Aveline", "user_name": "Master", "role_profile": ""}
DEEPSEEK = "cloud:deepseek:aveline:deepseek-v4-flash"


def _pair():
    """同一次对话被话题切点切成两段：第一段 e0–e3（两次往来），第二段 e4–e5。"""
    spec = [("user", "我想换工作"), ("assistant", "怎么了"), ("user", "老板天天加班"),
            ("assistant", "确实累"), ("user", "所以我投了三家"), ("assistant", "加油")]
    events = [
        {"event_id": f"e{i}", "conversation_id": CONV, "role": role, "content": text,
         "timestamp": 1000.0 + 60 * i, "message_id": f"m{i}"}
        for i, (role, text) in enumerate(spec)
    ]
    whole = build_conversation_inputs(
        "aveline", CONV, events, params=SegmentParams(segmenter="v1"), now=10**8,
        tree_reader=lambda _cid: events,
    )[0]
    first_seg = dataclasses.replace(
        whole.segment, segment_id="seg_a", source_event_ids=[f"e{i}" for i in range(4)],
        boundary_reason="topic", char_count=20,
    )
    second_seg = dataclasses.replace(
        whole.segment, segment_id="seg_b", source_event_ids=["e4", "e5"], boundary_reason="idle",
        started_at=1240.0, char_count=10,
    )
    first = dataclasses.replace(whole, segment=first_seg, events=tuple(events[:4]))
    second = dataclasses.replace(
        whole, segment=second_seg, events=tuple(events[4:]), previous_segment_id="seg_a",
        context_events=tuple(events[2:4]),
    )
    return first, second


class _Scheduler:
    def __init__(self, replies):
        self.replies, self.kwargs, self.prompts = list(replies), [], []

    async def submit_llm_task(self, prompt, **kwargs):
        self.kwargs.append(kwargs)
        self.prompts.append(prompt)
        yield self.replies.pop(0)


def _extractor(scheduler, model_hint=DEEPSEEK):
    return EpisodeExtractor(
        scheduler_provider=lambda: scheduler, model_hint=model_hint,
        perspective_for_scope=lambda _s: PERSPECTIVE, persona_prefix_for_scope=lambda _s: "你是Aveline。",
    )


def _reply(topics):
    return json.dumps({"topics": topics, "facts": [], "skip": "", "people": [], "role_updates": []},
                      ensure_ascii=False)


def test_carry_start_requires_tail_and_size_limit():
    short = [[{"content": "短"}]] * 3
    assert relay.carry_start({1, 2}, short) == 1
    assert relay.carry_start({0, 1}, short) is None  # 没覆盖到最后一次往来
    assert relay.carry_start(set(), short) is None
    long = [[{"content": "长" * (relay.CARRY_MAX_CHARS + 1)}]] * 2
    assert relay.carry_start({1}, long) is None


def test_open_topic_is_carried_and_continuation_prompted():
    first, _second = _pair()
    sched = _Scheduler([_reply([
        {"ids": [0], "summary": "他说想换工作。", "importance": 2},
        {"ids": [1], "summary": "他说老板天天加班。", "importance": 2, "open": True},
    ])])
    result = asyncio.run(_extractor(sched).extract(first))
    assert [n.text for n in result.notes] == ["他说想换工作。"]
    assert result.carry_event_ids == ("e2", "e3")
    assert CONTINUES_HINT in sched.prompts[0][1]["content"]


def test_open_flag_ignored_when_segment_does_not_continue():
    _first, second = _pair()
    sched = _Scheduler([_reply([{"ids": [0], "summary": "投了三家。", "open": True}])])
    result = asyncio.run(_extractor(sched).extract(second))
    assert len(result.notes) == 1 and result.carry_event_ids == ()
    assert CONTINUES_HINT not in sched.prompts[0][1]["content"]


def test_whole_segment_carried_is_skipped_with_reason():
    first, _second = _pair()
    sched = _Scheduler([_reply([{"ids": [0, 1], "summary": "换工作的事。", "open": True}])])
    result = asyncio.run(_extractor(sched).extract(first))
    assert result.notes == () and result.skip_reason == "carried_forward"
    assert result.carry_event_ids == ("e0", "e1", "e2", "e3")


def test_retry_ladder_turns_thinking_on_last():
    first, _second = _pair()
    good = _reply([{"ids": [0, 1], "summary": "他想换工作。"}])
    sched = _Scheduler(["不是 JSON", "还不是", good])
    result = asyncio.run(_extractor(sched).extract(first))
    assert len(result.notes) == 1
    assert [k["thinking_enabled"] for k in sched.kwargs] == [False, False, True]

    empty = _Scheduler(["", good])  # 空响应也要重试，不能直接失败
    assert len(asyncio.run(_extractor(empty).extract(first)).notes) == 1

    minimax = _Scheduler(["不是 JSON", good])
    asyncio.run(_extractor(minimax, model_hint="cloud:minimax:plan:MiniMax-M3").extract(first))
    assert [k["thinking_enabled"] for k in minimax.kwargs] == [False, False]

    other = _Scheduler(["不是 JSON"])  # 空路由（走默认模型）不认思考开关：只跑一次
    with pytest.raises(EpisodeParseError):
        asyncio.run(_extractor(other, model_hint="").extract(first))
    assert len(other.kwargs) == 1 and "thinking_enabled" not in other.kwargs[0]


def test_ordered_chains_keep_parts_of_one_conversation_together():
    first, second = _pair()
    lone = dataclasses.replace(second, segment=dataclasses.replace(second.segment, segment_id="x"),
                               previous_segment_id="")
    chains = relay.ordered_chains([second, lone, first])
    assert sorted([s.segment_id for s in c] for c in chains) == [["seg_a", "seg_b"], ["x"]]


class _Manager:
    user_id = "shared__scope__aveline"
    storage_scope = "aveline"

    def __init__(self, history_dir):
        self._memory_layout = {"history_dir": str(history_dir)}
        self.lock = threading.RLock()


class _Relaying:
    """第一段交出后一次往来；第二段原样把收到的全部事件写成一条。"""

    version = "segment-episode-10"
    accepted_versions = ()

    def __init__(self, fail_first=False):
        self.fail_first, self.seen = fail_first, {}

    async def extract(self, item):
        self.seen[item.segment_id] = [e["event_id"] for e in item.events]
        if item.segment_id == "seg_a":
            if self.fail_first:
                raise EpisodeParseError("bad_json")
            note = NoteDraft(kind="episode", text="想换工作", source_event_ids=("e0", "e1"))
            return ExtractionResult(notes=(note,), extractor_version=self.version,
                                    carry_event_ids=("e2", "e3"))
        ids = tuple(e["event_id"] for e in item.events)
        note = NoteDraft(kind="episode", text="加班和投简历", source_event_ids=ids)
        return ExtractionResult(notes=(note,), extractor_version=self.version)


def _run_jobs(tmp_path, monkeypatch, extractor):
    monkeypatch.setattr(paths, "notes_dir", lambda scope: tmp_path / "notes" / scope)
    monkeypatch.setattr(seg_run, "resolve_distillation_perspective", lambda _m: {"role_id": "aveline"})
    config = {"segment_extraction_enabled": True, "distillation_role_whitelist": ["aveline"],
              "segment_max_per_night": 0, "segment_max_chars_per_night": 0,
              "segment_max_seconds_per_night": 0}
    manager = _Manager(tmp_path / "memories")
    report = asyncio.run(seg_run.run_segment_jobs(
        manager.user_id, manager, config, extractor=extractor, note_store=NoteStore("aveline"),
        segments=list(_pair()), now=10**8,
    ))
    return report, NoteStore("aveline")


def test_nightly_hands_carry_to_next_part(tmp_path, monkeypatch):
    extractor = _Relaying()
    report, store = _run_jobs(tmp_path, monkeypatch, extractor)
    assert report["done"] == 2
    assert extractor.seen["seg_b"] == ["e2", "e3", "e4", "e5"]
    second = [n for n in store.list_notes(CONV) if n["source_segment_id"] == "seg_b"]
    assert second[0]["source_event_ids"] == ["e2", "e3", "e4", "e5"]
    assert store.get_carry(CONV, "seg_a") == ["e2", "e3"]


def test_nightly_defers_next_part_when_previous_failed(tmp_path, monkeypatch):
    extractor = _Relaying(fail_first=True)
    report, _store = _run_jobs(tmp_path, monkeypatch, extractor)
    assert report["failed"] == 1 and report["done"] == 0 and "seg_b" not in extractor.seen


def test_next_part_prompt_marks_carried_exchanges(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "notes_dir", lambda scope: tmp_path / "notes" / scope)
    first, second = _pair()
    store = NoteStore("aveline")
    store.replace_segment(CONV, "seg_a", "segment-episode-10", (),
                          segment_source_event_ids=first.segment.source_event_ids,
                          carry_event_ids=("e2", "e3"))
    merged = relay.with_carry(second, store, {"seg_a": first})
    assert merged.carried_event_ids == ("e2", "e3") and merged.context_events == ()
    assert set(merged.allowed_sources) == {"e2", "e3", "e4", "e5"}
    sched = _Scheduler([_reply([{"ids": [0, 1], "summary": "加班后投了三家。"}])])
    result = asyncio.run(_extractor(sched).extract(merged))
    assert CARRIED_HINT.format(last=0) in sched.prompts[0][1]["content"]
    assert result.notes[0].source_event_ids == ("e2", "e3", "e4", "e5")


def test_minimax_client_thinking_can_be_disabled_per_call():
    from core.llm.openai_compat.minimax_client import MiniMaxClient

    client = MiniMaxClient(api_key="test")
    messages = [{"role": "user", "content": "hi"}]
    off = client._build_payload(messages, stream=False, thinking_enabled=False)
    assert off["thinking"] == {"type": "disabled"} and off["reasoning_split"] is True
    assert "thinking" not in client._build_payload(messages, stream=False)
