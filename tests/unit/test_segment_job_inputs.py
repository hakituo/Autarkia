"""按段提取输入管线（v3 F3 · WP1）：主线过滤、去重、合并重复提交、封口、确定性 ID。

conftest 已把游标目录指到临时目录、关掉覆盖层兜底，常驻树每例重置。
"""

from __future__ import annotations

from datetime import datetime, timezone

from core.services.chat_history_store import ChatHistoryStore
from memory.nightly.segment_jobs import inputs as seg_inputs
from memory.nightly.segment_jobs.inputs import (
    SegmentParams,
    build_conversation_inputs,
    collect_segment_inputs,
)
from memory.topology import cursors

CONV = "web_role_aveline"
FAR_FUTURE = 10_000_000.0


def _msg(eid, role, content, ts, *, node="", parent="", turn="", event_type="chat_message"):
    payload = {
        "event_id": eid,
        "conversation_id": CONV,
        "role": role,
        "content": content,
        "timestamp": ts,
        "event_type": event_type,
    }
    if turn:
        payload["message_id"] = turn
    if node:
        payload["client_node_id"] = node
        payload["parent_node_id"] = parent
    return payload


def _build(events, *, now=FAR_FUTURE, params=None):
    return build_conversation_inputs(
        "aveline",
        CONV,
        events,
        params=params or SegmentParams(),
        now=now,
        tree_reader=lambda _cid: events,
    )


def _source_ids(items):
    return [eid for item in items for eid in item.segment.source_event_ids]


def test_sibling_branch_not_in_segments():
    # u1→a1→{u2→a2（旧线）, u3→a3（游标所在新线）}
    events = [
        _msg("e-u1", "user", "早", 100, node="u1", turn="t1"),
        _msg("e-a1", "assistant", "早呀", 101, node="a1", parent="u1", turn="t1"),
        _msg("e-u2", "user", "旧线问题", 200, node="u2", parent="a1", turn="t2"),
        _msg("e-a2", "assistant", "旧线回答", 201, node="a2", parent="u2", turn="t2"),
        _msg("e-u3", "user", "新线问题", 300, node="u3", parent="a1", turn="t3"),
        _msg("e-a3", "assistant", "新线回答", 301, node="a3", parent="u3", turn="t3"),
    ]
    cursors.advance_cursors([events[-1]])

    items = _build(events)

    ids = _source_ids(items)
    assert "e-u2" not in ids and "e-a2" not in ids
    assert ids == ["e-u1", "e-a1", "e-u3", "e-a3"]
    assert items[0].segment.topology_status == "complete"


def test_regenerated_reply_dropped_and_repeat_submission_merged():
    # 没有节点的历史：同一句用户输入提交两次，第一轮回复被重新生成取代
    events = [
        _msg("e-u1", "user", "今天吃什么", 100, turn="m1"),
        _msg("e-a1", "assistant", "旧回复", 101, turn="m1"),
        _msg("e-u2", "user", "今天 吃什么", 130, turn="m2"),
        _msg("e-a2", "assistant", "新回复", 131, turn="m2"),
    ]

    items = _build(events)

    assert len(items) == 1
    item = items[0]
    assert item.segment.source_event_ids == ["e-u1", "e-a2"]
    assert len(item.segment.turn_ids) == 1  # 合并后用户与保留回复仍是同一轮
    assert item.aliases == (("e-u2", "e-u1"),)
    assert item.segment.topology_status == "unknown"


def test_repeat_merge_needs_consecutive_user_messages():
    events = [
        _msg("e-u1", "user", "晚安", 100, turn="m1"),
        _msg("e-a1", "assistant", "晚安呀", 101, turn="m1"),
        _msg("e-u2", "user", "晚安", 3000, turn="m2"),
        _msg("e-a2", "assistant", "又说一次", 3001, turn="m2"),
    ]

    ids = _source_ids(_build(events))

    assert ids == ["e-u1", "e-a1", "e-u2", "e-a2"]


def test_thought_and_media_placeholder_not_in_segments():
    events = [
        _msg("e-u1", "user", "看这个", 100, turn="m1"),
        _msg("e-th", "assistant", "内心独白", 100.5, turn="m1", event_type="chat_thought"),
        _msg("e-img", "user", "[图片]", 100.7, turn="m1"),
        _msg("e-a1", "assistant", "好看", 101, turn="m1"),
    ]

    item = _build(events)[0]

    assert item.segment.source_event_ids == ["e-u1", "e-a1"]
    assert [event["event_id"] for event in item.events] == ["e-u1", "e-a1"]


def _long_chat(turns=10, start=100.0, step=60.0):
    events = []
    for index in range(turns):
        ts = start + index * step
        events.append(_msg(f"e-u{index}", "user", f"问题{index}", ts, turn=f"m{index}"))
        events.append(_msg(f"e-a{index}", "assistant", f"回答{index}", ts + 1, turn=f"m{index}"))
    return events


def test_only_tail_segment_can_be_open():
    events = _long_chat(turns=10)
    params = SegmentParams(idle_seconds=1800, max_turns=4, max_chars=4000)
    last_ts = max(event["timestamp"] for event in events)

    open_items = _build(events, now=last_ts + 60, params=params)
    closed_items = _build(events, now=last_ts + 1801, params=params)

    assert [item.closed for item in open_items] == [True, True, False]
    assert all(item.closed for item in closed_items)
    assert [len(item.segment.turn_ids) for item in closed_items] == [4, 4, 2]


def test_same_input_gives_same_segment_ids():
    events = _long_chat(turns=6)
    params = SegmentParams(max_turns=4)

    first = [item.segment_id for item in _build(events, params=params)]
    second = [item.segment_id for item in _build(list(reversed(events)), params=params)]

    assert first == second and len(first) == 2


def test_partial_topology_is_carried():
    events = [
        _msg("e-u1", "user", "有节点", 100, node="u1", turn="t1"),
        _msg("e-a1", "assistant", "没节点", 101, turn="t1"),
    ]

    assert _build(events)[0].segment.topology_status == "partial"


def test_params_from_config_and_defaults():
    assert SegmentParams.from_config({}) == SegmentParams(1800.0, 8, 4000)
    assert SegmentParams.from_config({"segment_max_turns": 3}).max_turns == 3


def test_collect_from_store_skips_open_segments(tmp_path, monkeypatch):
    store = ChatHistoryStore(tmp_path)
    written = [
        store.append_event(
            conversation_id=CONV,
            role=event["role"],
            content=event["content"],
            message_id=event["message_id"],
            now_dt=datetime.fromtimestamp(event["timestamp"], tz=timezone.utc),
        )
        for event in _long_chat(turns=3)
    ]
    last_ts = max(float(event["timestamp"]) for event in written)
    monkeypatch.setattr(seg_inputs, "list_scope_conversations", lambda _scope: [CONV])

    still_open = collect_segment_inputs("aveline", store=store, now=last_ts + 10)
    closed = collect_segment_inputs("aveline", store=store, now=last_ts + 3600)
    with_open = collect_segment_inputs("aveline", store=store, now=last_ts + 10, include_open=True)

    assert still_open == []
    assert len(closed) == 1 and closed[0].closed
    assert closed[0].segment.source_event_ids == [event["event_id"] for event in written]
    assert len(with_open) == 1 and not with_open[0].closed


def test_list_scope_conversations_skips_other_roles(tmp_path, monkeypatch):
    from core.utils.data import data_paths

    root = tmp_path / "chat_history" / "2026" / "10" / "26"
    root.mkdir(parents=True)
    for stem in ("web_role_aveline", "shared__scope__ling", "u1"):
        (root / f"{stem}.jsonl").write_text("", encoding="utf-8")
    monkeypatch.setattr(
        data_paths, "get_role_chat_history_dir", lambda _s: tmp_path / "chat_history"
    )
    monkeypatch.setattr(
        "core.services.chat_history_store.ChatHistoryStore._synced_index",
        staticmethod(lambda _r: None),
    )

    stems = seg_inputs.list_scope_conversations("aveline")

    assert "shared__scope__ling" not in stems
    assert {"web_role_aveline", "u1"} <= set(stems)
