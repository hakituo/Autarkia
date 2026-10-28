"""提取器 v9：短事实带重要度、plan 带 status（open / done / cancelled），并随笔记落盘。"""

from __future__ import annotations

import asyncio
import json

from memory.nightly.segment_jobs import episode, prompts
from memory.nightly.segment_jobs.episode import EpisodeExtractor
from memory.nightly.segment_jobs.episode_parse import (
    IMPORTANCE_LEVELS,
    parse_fact_items,
    parse_facts,
)
from memory.nightly.segment_jobs.inputs import SegmentParams, build_conversation_inputs
from memory.notes import NoteStore

CONV = "web_role_aveline"
PERSPECTIVE = {"role_id": "aveline", "role_name": "Aveline", "user_name": "Master", "role_profile": ""}


class _Scheduler:
    def __init__(self, reply):
        self.reply = reply

    async def submit_llm_task(self, prompt, **kwargs):
        yield self.reply


def _item():
    spec = [("user", "出差回来了"), ("assistant", "辛苦啦"), ("user", "健身卡不办了")]
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
        "aveline", CONV, events, params=SegmentParams(segmenter="v1"), now=10**8,
        tree_reader=lambda _cid: events,
    )[0]


def test_parse_fact_items_reads_importance_and_plan_status():
    facts = [
        {"ids": [0], "kind": "plan", "text": "他去成都出差三天", "importance": 3, "status": "done"},
        {"ids": [1], "kind": "plan", "text": "他办健身卡", "status": "CANCELLED"},
        {"ids": [1], "kind": "plan", "text": "他月底考四级", "status": "maybe"},
        {"ids": [1], "kind": "plan", "text": "他周末去爬山"},
        {"ids": [1], "kind": "preference", "text": "他不吃香菜", "status": "done"},
    ]
    items = parse_fact_items(json.dumps({"facts": facts}, ensure_ascii=False), 2)
    assert [(i[0], i[3], i[4]) for i in items] == [
        ("plan", 0.8, "done"),
        ("plan", IMPORTANCE_LEVELS[2], "cancelled"),
        ("plan", IMPORTANCE_LEVELS[2], "open"),  # 不认识的状态按 open
        ("plan", IMPORTANCE_LEVELS[2], "open"),  # v8 没有 status，按 open
        ("preference", IMPORTANCE_LEVELS[2], ""),  # 只有 plan 有状态
    ]
    # v8 口径的 parse_facts 仍是三元组
    assert parse_facts(json.dumps({"facts": facts[:1]}, ensure_ascii=False), 2) == [
        ("plan", [0], "他去成都出差三天")
    ]


def test_extractor_v9_writes_fact_importance_and_status_to_store():
    reply = json.dumps(
        {
            "topics": [{"ids": [0], "summary": "他出差回来了。", "importance": 2}],
            "facts": [
                {"ids": [0], "kind": "plan", "text": "Master去成都出差三天", "importance": 3,
                 "status": "done"},
                {"ids": [1], "kind": "preference", "text": "Master不想办健身卡", "importance": 1},
            ],
            "skip": "",
            "people": [],
            "role_updates": [],
        },
        ensure_ascii=False,
    )
    extractor = EpisodeExtractor(
        scheduler_provider=lambda: _Scheduler(reply),
        perspective_for_scope=lambda _s: PERSPECTIVE,
        persona_prefix_for_scope=lambda _s: "你是Aveline。",
    )
    item = _item()
    result = asyncio.run(extractor.extract(item))
    assert result.extractor_version == episode.EPISODE_EXTRACTOR_VERSION
    plan, pref = result.notes[1], result.notes[2]
    assert (plan.importance, plan.metadata.get("status")) == (0.8, "done")
    assert (pref.importance, "status" in pref.metadata) == (0.3, False)

    store = NoteStore("aveline")
    store.replace_segment(
        CONV, "seg", result.extractor_version, result.notes,
        segment_source_event_ids=("e0", "e1", "e2"),
    )
    by_kind = {n["kind"]: n for n in store.list_notes(CONV)}
    assert by_kind["plan"]["status"] == "done"
    assert "status" not in by_kind["preference"] and "status" not in by_kind["episode"]


def test_v8_segments_still_count_as_done_and_prompt_mentions_status():
    assert "segment-episode-8" in episode.ACCEPTED_EPISODE_VERSIONS
    assert '"status": "open"' in prompts.TASK_INSTRUCTION
    assert "cancelled" in prompts.TASK_INSTRUCTION


def test_note_label_marks_done_and_cancelled_plans():
    from core.tools.memory_notes_search import note_label

    assert note_label({"category": "plan", "status": "done"}) == "[计划·已完成]"
    assert note_label({"category": "plan", "status": "cancelled"}) == "[计划·已取消]"
    assert note_label({"category": "plan", "status": "open"}) == "[计划]"


def test_thinking_flag_sent_on_deepseek_and_minimax_routes():
    calls = []

    class _Recording(_Scheduler):
        async def submit_llm_task(self, prompt, **kwargs):
            calls.append(kwargs)
            yield self.reply

    reply = json.dumps({"topics": [{"ids": [0], "summary": "他出差回来了。"}], "facts": []})
    for hint in ("cloud:deepseek:ye:deepseek-chat", "cloud:minimax:plan:MiniMax-M2", ""):
        extractor = EpisodeExtractor(
            scheduler_provider=lambda: _Recording(reply),
            model_hint=hint,
            perspective_for_scope=lambda _s: PERSPECTIVE,
            persona_prefix_for_scope=lambda _s: "你是Aveline。",
        )
        asyncio.run(extractor.extract(_item()))
    assert calls[0].get("thinking_enabled") is False
    assert calls[1].get("thinking_enabled") is False  # MiniMax-M3 也认顶层 thinking:disabled
    assert "thinking_enabled" not in calls[2]  # 空路由（走默认模型）不传
