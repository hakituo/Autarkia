"""确定性分段（v3 F1 / F2）。

- 只在完整 turn 边界切；idle / max_turns / max_chars 三种封口；
- 跨 04:00 不强断，parent 跨段不封口；
- 输入顺序打乱后 segment_id 不变；结构节点（媒体占位）不进提炼段；
- 只沿一条 root→leaf 路径分段，兄弟线不混入；
- 迟到事件只让受影响段失效（diff_segments）。
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from memory.topology.events import normalize_event
from memory.topology.segments import IDLE, MAX_TURNS, build_segments, diff_segments
from memory.topology.tree import build_tree

CONV = "web_role_aveline"
SHANGHAI = timezone(timedelta(hours=8))


def _event(node, parent, ts, *, role="user", turn="", content=None):
    return normalize_event(
        {
            "event_id": f"evt-{node}",
            "conversation_id": CONV,
            "role": role,
            "content": f"正文-{node}" if content is None else content,
            "timestamp": ts,
            "event_type": "chat_message",
            "client_node_id": node,
            "parent_node_id": parent,
            "turn_id": turn or f"t-{node}",
        }
    )


def _exchange(index, ts, parent="", prefix=""):
    """一轮完整 exchange：user + assistant 共享 turn_id。"""
    key = f"{prefix}{index}"
    user = _event(f"u{key}", parent, ts, turn=f"t{key}")
    bot = _event(f"a{key}", f"u{key}", ts + 1, role="assistant", turn=f"t{key}")
    return [user, bot]


def _chain(count, *, start=1000.0, step=60.0, prefix="", parent=""):
    events = []
    for index in range(count):
        pair = _exchange(index, start + index * step, parent, prefix)
        events.extend(pair)
        parent = pair[-1].client_node_id
    return events


def test_idle_gap_splits_on_turn_boundary():
    events = _chain(2) + _exchange(9, 1000.0 + 3 * 3600, parent="a1")
    segments = build_segments(events, tree_id="t", idle_seconds=1800)
    assert [len(item.turn_ids) for item in segments] == [2, 1]
    assert segments[0].boundary_reason == IDLE
    # 封口永远落在完整 turn 后：同 turn 的 user/assistant 不被拆开
    assert segments[0].source_event_ids[-1] == "evt-a1"


def test_max_turns_seals_without_sealing_every_following_turn():
    segments = build_segments(_chain(7), tree_id="t", max_turns=3)
    assert [len(item.turn_ids) for item in segments] == [3, 3, 1]
    assert [item.boundary_reason for item in segments[:2]] == [MAX_TURNS, MAX_TURNS]


def test_no_hard_break_at_four_am():
    night = datetime(2026, 10, 25, 3, 50, tzinfo=SHANGHAI).timestamp()
    events = []
    parent = ""
    for index in range(4):  # 03:50 → 04:05，相邻 5 分钟
        pair = _exchange(index, night + index * 300, parent)
        events.extend(pair)
        parent = pair[-1].client_node_id
    segments = build_segments(events, tree_id="t", idle_seconds=1800)
    assert len(segments) == 1


def test_input_order_does_not_change_segment_ids():
    events = _chain(6)
    shuffled = list(events)
    random.Random(7).shuffle(shuffled)
    first = [item.segment_id for item in build_segments(events, tree_id="t", max_turns=4)]
    second = [item.segment_id for item in build_segments(shuffled, tree_id="t", max_turns=4)]
    assert first == second


def test_media_placeholder_turn_is_kept_out_of_extraction():
    events = _chain(1) + [
        _event("img", "a0", 1100.0, turn="t-img", content="[图片]"),
    ]
    segments = build_segments(events, tree_id="t")
    assert all("evt-img" not in item.source_event_ids for item in segments)
    with_structure = build_segments(events, tree_id="t", include_ineligible=True)
    assert any("evt-img" in item.source_event_ids for item in with_structure)


def test_segments_follow_single_path_only():
    shared = _chain(2)
    left = _exchange(5, 2000.0, parent="a1")
    right = _exchange(6, 2100.0, parent="a1")
    tree = build_tree(shared + left + right, conversation_id=CONV)
    by_id = {event.event_id: event for event in shared + left + right}
    path_events = [by_id[item] for item in tree.path_event_ids("a5")]
    segments = build_segments(path_events, tree_id=tree.tree_id)
    sources = {item for segment in segments for item in segment.source_event_ids}
    assert "evt-u5" in sources and "evt-u6" not in sources


def test_late_event_only_invalidates_affected_segment():
    early = _chain(2, start=1000.0)
    late_block = _chain(2, start=1000.0 + 5 * 3600, prefix="L", parent="a1")
    before = build_segments(early + late_block, tree_id="t", idle_seconds=1800)
    straggler = _event("late", "a1", 1000.0 + 5 * 3600 + 200.0, turn="t-late")
    after = build_segments(early + late_block + [straggler], tree_id="t", idle_seconds=1800)
    diff = diff_segments(before, after)
    assert diff.kept == [before[0].segment_id]
    assert diff.invalidated == [before[1].segment_id]
    assert len(diff.added) == 1
    assert not diff_segments(after, after).changed


def test_shared_prefix_segments_are_reused_across_siblings():
    shared = _chain(4, start=1000.0)
    left = _chain(2, start=1000.0 + 4 * 3600, prefix="L", parent="a3")
    right = _chain(2, start=1000.0 + 5 * 3600, prefix="R", parent="a3")
    tree = build_tree(shared + left + right, conversation_id=CONV)
    by_id = {event.event_id: event for event in shared + left + right}

    def path_segments(leaf):
        events = [by_id[item] for item in tree.path_event_ids(leaf)]
        return build_segments(events, tree_id=tree.tree_id, idle_seconds=1800, max_turns=3)

    left_ids = [item.segment_id for item in path_segments("aL1")]
    right_ids = [item.segment_id for item in path_segments("aR1")]
    # 共享前缀 4 轮按 max_turns=3 切成 [3, 1]，两条兄弟线复用同样的两个段 ID
    assert left_ids[:2] == right_ids[:2]
    assert left_ids[2:] != right_ids[2:]
