"""event_ref 回填：唯一命中才写、只改元数据、失败整批回滚（v3 D8）。"""

from __future__ import annotations

import json

from memory.audit.legacy import build_event_index
from memory.maintenance import event_ref_apply
from memory.maintenance.event_ref_apply import apply_backfill_plan
from memory.maintenance.event_ref_backfill import (
    STATUS_ALREADY_LINKED,
    STATUS_AMBIGUOUS,
    STATUS_CONFLICT,
    STATUS_DUPLICATE_ID,
    STATUS_LEGACY_ONLY,
    STATUS_RESOLVED,
    RecordSource,
    build_backfill_plan,
)
from memory.topology.events import normalize_event


class _Scanned:
    def __init__(self, payload):
        self.normalized = normalize_event(payload, storage_scope="aveline")
        self.relative_path = f"2026/10/25/{payload['conversation_id']}.jsonl"


def _payload(event_id, role, message_id, conversation_id="cid"):
    return {
        "event_id": event_id,
        "conversation_id": conversation_id,
        "role": role,
        "message_id": message_id,
        "content": f"事件-{event_id}",
        "timestamp": 1.0,
        "event_type": "chat_message",
    }


def _source(memory_id, path="a.json", position=0, role="user", message_id="", event_id=""):
    existing = ""
    metadata = {"message_id": message_id}
    if event_id:
        metadata["event_ref"] = {"event_id": event_id, "conversation_id": "cid"}
        existing = event_id
    return RecordSource(
        file_path=path,
        position=position,
        memory_id=memory_id,
        role=role,
        conversation_id="cid",
        message_id=message_id,
        existing_event_id=existing,
    )


def _index():
    events = [
        _Scanned(_payload("e1", "user", "t1")),
        _Scanned(_payload("e2", "user", "t2")),
        _Scanned(_payload("e3a", "assistant", "t3")),
        _Scanned(_payload("e3b", "assistant", "t3")),
        _Scanned(_payload("e6", "user", "t6")),
        _Scanned(_payload("e7a", "user", "t7")),
        _Scanned(_payload("e7b", "user", "t7")),
        _Scanned(_payload("e9", "assistant", "t9")),
    ]
    return build_event_index(events)


def test_plan_classifies_without_guessing():
    sources = [
        _source("m1", message_id="t1", event_id="e1"),
        _source("m2", position=1, message_id="t2"),
        _source("m3", position=2, role="assistant", message_id="t3"),
        _source("m4", position=3, message_id=""),
        _source("m5", position=4, message_id="t6"),
        _source("m9", path="b.json", message_id="t2"),  # 多条记忆共享同一事件：合法
        _source("m2", position=1, message_id="t2"),  # 同一物理记录被重复读入
        _source("m7", position=5, message_id="t7"),
        _source("m8", position=6, message_id="t9", event_id="e9"),
    ]

    plan = build_backfill_plan(sources, _index())

    counts = plan.counts()
    assert counts[STATUS_ALREADY_LINKED] == 1
    assert counts[STATUS_RESOLVED] == 3
    assert counts[STATUS_AMBIGUOUS] == 2
    assert counts[STATUS_LEGACY_ONLY] == 1
    assert counts[STATUS_DUPLICATE_ID] == 1
    assert counts[STATUS_CONFLICT] == 1
    assert {item.source.memory_id for item in plan.writable} == {"m2", "m5", "m9"}


def _write_file(path, records):
    path.write_text(
        json.dumps({"weighted_memories": records}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_apply_only_touches_event_ref(tmp_path):
    file_a = tmp_path / "a.json"
    file_b = tmp_path / "b.json"
    _write_file(
        file_a,
        [
            {"id": "m1", "role": "user", "summary": "旧梗概", "content": "正文1",
             "timestamp": 11.0, "metadata": {"message_id": "t1",
             "event_ref": {"event_id": "e1", "conversation_id": "cid"}}},
            {"id": "m2", "role": "user", "summary": "旧梗概2", "content": "正文2",
             "timestamp": 12.0, "metadata": {"message_id": "t2"}},
        ],
    )
    _write_file(
        file_b,
        [
            {"id": "m5", "role": "user", "summary": "旧梗概5", "content": "正文5",
             "timestamp": 15.0, "metadata": {"message_id": "t6"}},
        ],
    )
    sources = [
        RecordSource.from_record(str(file_a), 0, json.loads(file_a.read_text())["weighted_memories"][0]),
        RecordSource.from_record(str(file_a), 1, json.loads(file_a.read_text())["weighted_memories"][1]),
        RecordSource.from_record(str(file_b), 0, json.loads(file_b.read_text())["weighted_memories"][0]),
    ]
    plan = build_backfill_plan(sources, _index())

    result = apply_backfill_plan(plan, backup_dir=tmp_path / "backup")

    assert result["committed"] is True
    assert result["updated"] == 2
    record = json.loads(file_a.read_text())["weighted_memories"][1]
    assert record["metadata"]["event_ref"]["event_id"] == "e2"
    for key, value in (("id", "m2"), ("summary", "旧梗概2"), ("content", "正文2"), ("timestamp", 12.0)):
        assert record[key] == value
    assert json.loads(file_b.read_text())["weighted_memories"][0]["metadata"]["event_ref"]["event_id"] == "e6"
    assert len(list((tmp_path / "backup").glob("*.json"))) == 3  # 两个备份 + manifest


def test_apply_rolls_back_all_files_on_failure(tmp_path, monkeypatch):
    file_a = tmp_path / "a.json"
    file_b = tmp_path / "b.json"
    _write_file(file_a, [{"id": "m2", "role": "user", "metadata": {"message_id": "t2"}}])
    _write_file(file_b, [{"id": "m5", "role": "user", "metadata": {"message_id": "t6"}}])
    sources = [
        RecordSource.from_record(str(file_a), 0, json.loads(file_a.read_text())["weighted_memories"][0]),
        RecordSource.from_record(str(file_b), 0, json.loads(file_b.read_text())["weighted_memories"][0]),
    ]
    plan = build_backfill_plan(sources, _index())
    originals = {file_a: file_a.read_text(), file_b: file_b.read_text()}

    calls = {"count": 0}
    original = event_ref_apply._safe_json_dump

    def _boom(data, path):
        calls["count"] += 1
        if calls["count"] >= 2:
            raise OSError("disk full")
        original(data, path)

    monkeypatch.setattr(event_ref_apply, "_safe_json_dump", _boom)

    result = apply_backfill_plan(plan)

    assert result["committed"] is False
    assert file_a.read_text() == originals[file_a]
    assert file_b.read_text() == originals[file_b]


def test_blocked_plan_never_writes(tmp_path):
    file_a = tmp_path / "a.json"
    _write_file(file_a, [{"id": "m2", "role": "user", "metadata": {"message_id": "t2"}}])
    before = file_a.read_text()
    plan = build_backfill_plan(
        [RecordSource.from_record(str(file_a), 0, json.loads(before)["weighted_memories"][0])],
        _index(),
    )
    plan.blocked = True

    result = apply_backfill_plan(plan)

    assert result["committed"] is False
    assert file_a.read_text() == before
