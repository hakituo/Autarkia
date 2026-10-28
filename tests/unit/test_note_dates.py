"""梗概相对时间补具体日期（不调模型）：推算规则、写入时补、已有梗概原地补。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.utils import time_utils
from memory.nightly.segment_jobs.contracts import NoteDraft
from memory.notes import NoteStore, paths
from memory.notes.dates import annotate
from scripts.maintenance import annotate_note_dates

SHANGHAI = timezone(timedelta(hours=8))
CONV = "web_role_aveline"


@pytest.fixture(autouse=True)
def fixed_timezone(monkeypatch):
    monkeypatch.setattr(
        time_utils, "format_timestamp",
        lambda ts, fmt="%Y-%m-%d %H:%M:%S": datetime.fromtimestamp(ts, SHANGHAI).strftime(fmt),
    )


def _ts(*args):
    return datetime(*args, tzinfo=SHANGHAI).timestamp()


def test_relative_days_and_weeks_resolve_from_reference_time():
    thursday_night = _ts(2025, 9, 25, 22, 0)
    assert annotate("他说明天要回老家，昨晚没睡好", thursday_night) == (
        "他说明天（9月26日）要回老家，昨晚（9月24日）没睡好"
    )
    assert annotate("大后天考试，下周三出差，上周日去爬山", thursday_night) == (
        "大后天（9月28日）考试，下周三（10月1日）出差，上周日（9月21日）去爬山"
    )


def test_late_night_counts_as_previous_day_and_ranges_are_left_alone():
    assert annotate("他说明天要早起", _ts(2025, 9, 26, 1, 30)) == "他说明天（9月26日）要早起"
    assert annotate("周末再说，月底发工资", _ts(2025, 9, 25, 22, 0)) == "周末再说，月底发工资"


def test_compound_words_and_non_time_usages_are_left_alone():
    ts = _ts(2025, 9, 25, 22, 0)
    for text in ("他在玩明日方舟", "刷今日头条", "先天后天都有", "习惯是后天养成的", "后天形成的"):
        assert annotate(text, ts) == text
    assert annotate("明日要早起", ts) == "明日（9月26日）要早起"
    # 排除词只管对应的词：「明天努力」「今天新闻」仍是时间用法
    assert annotate("明天努力学习", ts) == "明天（9月26日）努力学习"
    assert annotate("今天新闻说", ts) == "今天（9月25日）新闻说"
    assert annotate("先天与后天", ts) == "先天与后天"


def test_existing_dates_are_not_doubled_and_missing_time_is_noop():
    ts = _ts(2025, 9, 25, 22, 0)
    assert annotate("明天（9月26日）回老家", ts) == "明天（9月26日）回老家"
    assert annotate("明天回老家", None) == "明天回老家"


def test_script_rewrites_in_place_keeps_id_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "notes_dir", lambda scope: tmp_path / scope / "notes_v2")
    store = NoteStore("aveline")
    draft = NoteDraft(kind="plan", text="Master明天要回老家", source_event_ids=("e1",),
                      metadata={"occurred_from": _ts(2025, 9, 25, 22, 0)})
    store.replace_segment(CONV, "seg", "segment-episode-10", [draft], segment_source_event_ids=("e1",))
    before = store.list_notes(CONV)[0]
    root = tmp_path / "aveline" / "notes_v2"
    assert annotate_note_dates.run("aveline", apply=False, root=root)["would_change"] == 1
    monkeypatch.setattr(annotate_note_dates, "ROOT_DIR", tmp_path)  # 备份写到临时目录
    report = annotate_note_dates.run("aveline", apply=True, root=root)
    after = store.list_notes(CONV)[0]
    assert report["changed"] == 1 and after["note_id"] == before["note_id"]
    assert after["text"] == "Master明天（9月26日）要回老家" and after["text_revisions"] == ["dates-v1"]
    assert annotate_note_dates.run("aveline", apply=True, root=root)["changed"] == 0


def test_extractor_annotates_new_notes_from_exchange_time():
    import asyncio
    import json

    from memory.nightly.segment_jobs.episode import EpisodeExtractor
    from memory.nightly.segment_jobs.inputs import SegmentParams, build_conversation_inputs

    ts = _ts(2025, 9, 25, 22, 0)
    events = [
        {"event_id": "e0", "conversation_id": CONV, "role": "user", "content": "明天要回老家",
         "timestamp": ts, "message_id": "m0"},
        {"event_id": "e1", "conversation_id": CONV, "role": "assistant", "content": "早点睡",
         "timestamp": ts + 5, "message_id": "m0"},
    ]
    item = build_conversation_inputs("aveline", CONV, events, params=SegmentParams(segmenter="v1"),
                                     now=ts + 10**6, tree_reader=lambda _cid: events)[0]
    reply = json.dumps({"topics": [{"ids": [0], "summary": "他说明天要回老家。"}],
                        "facts": [{"ids": [0], "kind": "plan", "text": "Master明天回老家"}]}, ensure_ascii=False)

    class _Scheduler:
        async def submit_llm_task(self, prompt, **kwargs):
            yield reply

    extractor = EpisodeExtractor(
        scheduler_provider=_Scheduler, perspective_for_scope=lambda _s: {},
        persona_prefix_for_scope=lambda _s: "你是Aveline。",
    )
    result = asyncio.run(extractor.extract(item))
    assert [n.text for n in result.notes] == ["他说明天（9月26日）要回老家。", "Master明天（9月26日）回老家"]
