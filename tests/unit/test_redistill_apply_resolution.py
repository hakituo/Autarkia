"""redistill 回写解析：同轮多事件不得互相覆盖（B1）。"""

from __future__ import annotations

import threading

import pytest

from memory.maintenance.redistill_apply import (
    MemoryTargetIndex,
    SourceEvent,
    apply_plan,
    build_apply_plan,
)


class _FakeManager:
    """只实现回写路径需要的最小接口。"""

    def __init__(self, records, fail_on=()):
        self.weighted_memories = records
        self.lock = threading.RLock()
        self._use_rw_lock = False
        self.fail_on = set(fail_on)
        self.save_calls = 0
        self.dirty_marks = []

    def update_memory_distillation(self, memory_id, summary, keywords, **kwargs):
        if memory_id in self.fail_on:
            return False
        record = self.weighted_memories.get(memory_id)
        if record is None:
            return False
        record["summary"] = summary
        record["keywords"] = list(keywords)
        record["search_keywords"] = list(keywords)
        record["is_distilled"] = True
        return True

    def _mark_keyword_index_dirty_locked(self, memory_id):
        self.dirty_marks.append(memory_id)

    def _schedule_save(self):
        self.save_calls += 1


def _record(role, message_id, event_id="", conversation_id="cid-1", summary="老梗概"):
    metadata = {"message_id": message_id}
    if event_id:
        metadata["event_ref"] = {
            "event_id": event_id,
            "conversation_id": conversation_id,
            "relative_path": f"2026/10/25/{conversation_id}.jsonl",
        }
    return {
        "role": role,
        "source": role,
        "summary": summary,
        "keywords": ["old"],
        "search_keywords": ["old"],
        "display_tags": ["对话"],
        "is_distilled": True,
        "metadata": metadata,
    }


def _event(role, message_id, event_id="", conversation_id="cid-1"):
    return SourceEvent(
        event_id=event_id,
        conversation_id=conversation_id,
        role=role,
        message_id=message_id,
        content="正文",
        timestamp=1.0,
    )


def _turn_events():
    return [_event("user", "turn-1", "evt-u1"), _event("assistant", "turn-1", "evt-a1")]


def test_same_turn_user_and_assistant_resolve_to_their_own_records():
    records = {
        "mem-u": _record("user", "turn-1", "evt-u1"),
        "mem-a": _record("assistant", "turn-1", "evt-a1"),
    }
    index = MemoryTargetIndex(records)

    user_target = index.resolve(_event("user", "turn-1", "evt-u1"))
    assistant_target = index.resolve(_event("assistant", "turn-1", "evt-a1"))

    assert user_target.memory_id == "mem-u"
    assert assistant_target.memory_id == "mem-a"
    assert user_target.resolved_by == "event_ref"
    assert assistant_target.resolved_by == "event_ref"


def test_turn_fallback_requires_unique_role_match():
    records = {
        "mem-u": _record("user", "turn-9"),
        "mem-a": _record("assistant", "turn-9"),
    }
    index = MemoryTargetIndex(records)

    target = index.resolve(_event("assistant", "turn-9"))

    assert target.memory_id == "mem-a"
    assert target.resolved_by == "turn_unique"


def test_duplicate_turn_candidates_are_ambiguous_not_guessed():
    records = {
        "mem-a1": _record("assistant", "turn-2"),
        "mem-a2": _record("assistant", "turn-2"),
    }
    index = MemoryTargetIndex(records)

    target = index.resolve(_event("assistant", "turn-2"))

    assert target.ok is False
    assert target.status == "ambiguous"
    assert target.candidate_count == 2


def test_event_ref_role_mismatch_is_rejected():
    records = {"mem-a": _record("assistant", "turn-3", "evt-shared")}
    index = MemoryTargetIndex(records)

    target = index.resolve(_event("user", "turn-3", "evt-shared"))

    assert target.ok is False
    assert target.status == "role_mismatch"


def test_build_plan_blocks_whole_batch_when_one_event_is_missing():
    records = {"mem-u": _record("user", "turn-4", "evt-u4")}
    index = MemoryTargetIndex(records)
    events = [_event("user", "turn-4", "evt-u4"), _event("assistant", "turn-4", "evt-a4")]

    plan = build_apply_plan(index, events, {1: ("新梗概1", ["k1"]), 2: ("新梗概2", [])})

    assert plan.blocked is True
    assert any("条目2" in reason for reason in plan.reasons)


def test_build_plan_blocks_two_events_mapping_to_one_memory():
    records = {"mem-u": _record("user", "turn-5", "evt-u5")}
    index = MemoryTargetIndex(records)
    # 两条事件的 event_id 都指向同一条记忆（历史脏数据）
    events = [_event("user", "turn-5", "evt-u5"), _event("user", "turn-5", "evt-u5b")]
    index._by_event_id.setdefault("evt-u5b", []).append("mem-u")

    plan = build_apply_plan(index, events, {1: ("一", []), 2: ("二", [])})

    assert plan.blocked is True
    assert any("同一条记忆" in reason for reason in plan.reasons)


def test_blocked_plan_never_writes():
    records = {"mem-u": _record("user", "turn-6", "evt-u6")}
    manager = _FakeManager(records)
    index = MemoryTargetIndex.from_manager(manager)
    events = [_event("user", "turn-6", "evt-u6"), _event("assistant", "turn-6", "evt-missing")]
    plan = build_apply_plan(index, events, {1: ("新梗概", []), 2: ("另一条", [])})

    result = apply_plan(manager, plan)

    assert result["committed"] is False
    assert records["mem-u"]["summary"] == "老梗概"


def test_successful_apply_writes_every_item():
    records = {
        "mem-u": _record("user", "turn-7", "evt-u7"),
        "mem-a": _record("assistant", "turn-7", "evt-a7"),
    }
    manager = _FakeManager(records)
    index = MemoryTargetIndex.from_manager(manager)
    plan = build_apply_plan(
        index,
        [_event("user", "turn-7", "evt-u7"), _event("assistant", "turn-7", "evt-a7")],
        {1: ("用户梗概", ["a"]), 2: ("角色梗概", ["b"])},
    )

    result = apply_plan(manager, plan)

    assert result["committed"] is True
    assert result["updated"] == 2
    assert records["mem-u"]["summary"] == "用户梗概"
    assert records["mem-a"]["summary"] == "角色梗概"


def test_partial_failure_rolls_back_previous_writes():
    records = {
        "mem-u": _record("user", "turn-8", "evt-u8"),
        "mem-a": _record("assistant", "turn-8", "evt-a8"),
    }
    manager = _FakeManager(records, fail_on={"mem-a"})
    index = MemoryTargetIndex.from_manager(manager)
    plan = build_apply_plan(
        index,
        [_event("user", "turn-8", "evt-u8"), _event("assistant", "turn-8", "evt-a8")],
        {1: ("用户梗概", ["a"]), 2: ("角色梗概", ["b"])},
    )

    result = apply_plan(manager, plan)

    assert result["committed"] is False
    assert records["mem-u"]["summary"] == "老梗概"
    assert records["mem-u"]["keywords"] == ["old"]
    assert manager.save_calls >= 1


def test_cross_conversation_same_turn_id_is_not_cross_matched():
    records = {
        "mem-a": _record("assistant", "turn-x", "evt-x", conversation_id="cid-a"),
        "mem-b": _record("assistant", "turn-x", "evt-y", conversation_id="cid-b"),
    }
    index = MemoryTargetIndex(records)

    left = index.resolve(_event("assistant", "turn-x", conversation_id="cid-a"))
    right = index.resolve(_event("assistant", "turn-x", conversation_id="cid-b"))

    assert left.memory_id == "mem-a"
    assert right.memory_id == "mem-b"


@pytest.mark.parametrize("summary", ["", "   "])
def test_entry_without_summary_is_treated_as_failure(summary):
    records = {"mem-u": _record("user", "turn-10", "evt-u10")}
    index = MemoryTargetIndex(records)

    plan = build_apply_plan(
        index,
        [_event("user", "turn-10", "evt-u10")],
        {1: (summary, ["k"])},
    )

    assert plan.blocked is True
