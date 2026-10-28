"""按段提取输入管线接分段器 v2（spec §7.1）：切点账本、开放末尾会话、开关与目录。"""

from __future__ import annotations

from memory.nightly.segment_jobs.inputs import SegmentParams


def _v2_events(start: float, *, topics=("猫", "车"), rounds: int = 8):
    events, index = [], 0
    for topic in topics:
        for _ in range(rounds):
            for role, size in (("user", 100), ("assistant", 200)):
                events.append(
                    {
                        "event_id": f"v2-{index:03d}",
                        "conversation_id": "web_role_aveline",
                        "role": role,
                        "content": topic * size,
                        "timestamp": start + index * 20,
                        "event_type": "chat_message" if role == "user" else "chat_reply",
                        "message_id": f"m{index}",
                    }
                )
                index += 1
    return events


def _head_scorer(units, i):
    return 1.0 if units[i - 1][0].content[0] != units[i][0].content[0] else 0.0


def test_v2_segmenter_records_cuts_and_replays_same_ids(tmp_path):
    from memory.nightly.segment_jobs import inputs as segment_inputs
    from memory.nightly.segment_jobs.topic_cuts import CutLedger
    from memory.nightly.segment_jobs.topic_inputs import TopicContext

    raw = _v2_events(1000.0)
    params = segment_inputs.SegmentParams(segmenter="v2")
    ledger_file = tmp_path / "cuts.json"
    context = TopicContext("aveline", ledger=CutLedger("aveline", ledger_file), scorer=_head_scorer)
    first = segment_inputs.build_conversation_inputs(
        "aveline",
        "web_role_aveline",
        raw,
        params=params,
        now=10**9,
        topic_context=context,
        tree_reader=lambda _cid: raw,
    )
    context.save()
    assert [item.segment.char_count for item in first] == [2400, 2400]
    assert all(item.closed for item in first)
    assert first[1].context_events and not first[0].context_events

    def boom(units, i):
        raise AssertionError("账本命中时不应打分")

    replay_ctx = TopicContext("aveline", ledger=CutLedger("aveline", ledger_file), scorer=boom)
    replay = segment_inputs.build_conversation_inputs(
        "aveline",
        "web_role_aveline",
        raw,
        params=params,
        now=10**9,
        topic_context=replay_ctx,
        tree_reader=lambda _cid: raw,
    )
    assert [i.segment_id for i in replay] == [i.segment_id for i in first]
    assert replay_ctx.ledger.hits == 1


def test_v2_open_tail_session_is_not_closed_nor_recorded(tmp_path):
    from memory.nightly.segment_jobs import inputs as segment_inputs
    from memory.nightly.segment_jobs.topic_cuts import CutLedger
    from memory.nightly.segment_jobs.topic_inputs import TopicContext

    raw = _v2_events(1000.0)
    last = max(item["timestamp"] for item in raw)
    context = TopicContext(
        "aveline", ledger=CutLedger("aveline", tmp_path / "c.json"), scorer=_head_scorer
    )
    items = segment_inputs.build_conversation_inputs(
        "aveline",
        "web_role_aveline",
        raw,
        params=segment_inputs.SegmentParams(segmenter="v2"),
        now=last + 60,
        topic_context=context,
        tree_reader=lambda _cid: raw,
    )
    assert len(items) == 2 and not any(item.closed for item in items)
    assert context.ledger.recorded == 0


def test_segment_params_reads_v2_config(monkeypatch):
    from memory.nightly.segment_jobs.inputs import SegmentParams
    from memory.notes import paths as notes_paths

    # 缺省值跟随 settings（app.yaml 已切 v2）；这里固定开关，只测「配置优先、缺省读开关」
    monkeypatch.setattr(notes_paths, "active_segmenter", lambda: "v1")

    params = SegmentParams.from_config(
        {"segment_segmenter": "V2", "segment_session_max_chars": 3000}
    )
    assert params.segmenter == "v2" and params.session_max_chars == 3000
    assert SegmentParams.from_config({}).segmenter == "v1"


def test_notes_dir_follows_segmenter_switch(monkeypatch):
    from types import SimpleNamespace

    import config.integrated_config as integrated
    from memory.notes import paths as notes_paths

    for value, expected in (("v2", "notes_v2"), ("v1", "notes"), ("bogus", "notes")):
        fake = SimpleNamespace(memory=SimpleNamespace(notes_segmenter=value))
        monkeypatch.setattr(integrated, "get_settings", lambda fake=fake: fake)
        assert notes_paths.active_segmenter() in {"v1", "v2"}
        assert notes_paths.notes_dir_name() == expected
        assert SegmentParams.from_config({}).segmenter == ("v2" if value == "v2" else "v1")
