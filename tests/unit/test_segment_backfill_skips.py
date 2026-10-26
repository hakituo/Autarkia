"""回填断点续跑：模型明确无内容的段记入账本，重跑不再调用模型。"""

from __future__ import annotations

from types import SimpleNamespace

from scripts.maintenance import backfill_segment_notes as backfill


def _item(segment_id: str) -> SimpleNamespace:
    segment = SimpleNamespace(
        started_at=1_700_000_000.0,
        ended_at=1_700_000_060.0,
        source_event_ids=(),
    )
    return SimpleNamespace(
        segment_id=segment_id,
        conversation_id="conv",
        segment=segment,
        events=[],
        char_count=10,
    )


def _patch_plan(monkeypatch, tmp_path, items):
    monkeypatch.setattr(backfill, "get_role_memories_dir", lambda scope: tmp_path)
    monkeypatch.setattr(
        backfill, "collect_segment_inputs", lambda scope, conversations=None: items
    )
    monkeypatch.setattr(
        backfill, "NoteStore", lambda scope: SimpleNamespace(list_notes=lambda cid: [])
    )
    monkeypatch.setattr(backfill.policy, "excluded", lambda scope, events: False)
    monkeypatch.setattr(
        backfill.policy, "provider_for", lambda scope, started: "deepseek"
    )
    monkeypatch.setattr(backfill.policy, "key_alias_for", lambda scope, name: "")


def _args() -> SimpleNamespace:
    return SimpleNamespace(conversation="", since_days=0, limit=0)


def test_pending_skips_segments_recorded_as_no_content(tmp_path, monkeypatch):
    _patch_plan(monkeypatch, tmp_path, [_item("s1"), _item("s2")])
    ledger = backfill._open_ledger("testscope")
    ledger.mark_skipped("s1", "no_reusable_info")
    ledger.save()

    plan = backfill._pending(
        "testscope", _args(), {backfill.EpisodeExtractor.version}
    )

    assert [item.segment_id for item in plan["items"]] == ["s2"]
    assert plan["skipped_before"] == 1
    assert plan["done"] == 0


def test_pending_reexamines_skips_from_an_old_extractor_version(tmp_path, monkeypatch):
    _patch_plan(monkeypatch, tmp_path, [_item("s1")])
    monkeypatch.setattr(backfill.EpisodeExtractor, "version", "segment-episode-6")
    old = backfill._open_ledger("testscope")
    old.mark_skipped("s1", "no_reusable_info")
    old.save()

    monkeypatch.setattr(backfill.EpisodeExtractor, "version", "segment-episode-5")
    plan = backfill._pending(
        "testscope", _args(), {backfill.EpisodeExtractor.version}
    )

    assert [item.segment_id for item in plan["items"]] == ["s1"]
    assert plan["skipped_before"] == 0
