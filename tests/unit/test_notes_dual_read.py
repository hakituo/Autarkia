"""分段器 v2 双读：检索 / 展开默认新旧都读；人物线索按覆盖去重；旧向量直接复用。"""

from __future__ import annotations

import numpy as np
import pytest

from core.tools import expand_memory_tool
from memory.nightly.segment_jobs.contracts import NoteDraft
from memory.notes import NoteStore, embeddings, legacy, paths
from memory.notes.retrieval import NoteRetriever, reset_note_retrieval_cache

CONV = "web_role_aveline"


@pytest.fixture
def stores(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "notes_dir", lambda scope: tmp_path / scope / "notes_v2")
    reset_note_retrieval_cache()
    new = NoteStore("aveline")
    old = NoteStore("aveline", root=tmp_path / "aveline" / "notes")
    old.replace_segment(CONV, "old_1", "segment-episode-5",
                        [NoteDraft(kind="episode", text="旧：他买了乌龙茶", source_event_ids=("e1",))],
                        segment_source_event_ids=("e1",))
    old.replace_segment(CONV, "old_2", "segment-episode-5",
                        [NoteDraft(kind="episode", text="旧：他去爬了山", source_event_ids=("e9",))],
                        segment_source_event_ids=("e9",))
    new.replace_segment(CONV, "new_1", "segment-episode-10",
                        [NoteDraft(kind="episode", text="新：他买了乌龙茶和红茶", source_event_ids=("e2",))],
                        segment_source_event_ids=("e1", "e2"))
    yield new, old
    reset_note_retrieval_cache()


def test_reads_old_and_new_but_signals_view_hides_covered(stores):
    new, _old = stores
    texts = sorted(n["text"] for n in legacy.readable_notes(new, CONV))
    assert texts == ["新：他买了乌龙茶和红茶", "旧：他买了乌龙茶", "旧：他去爬了山"]
    deduped = sorted(n["text"] for n in legacy.readable_notes(new, CONV, include_covered=False))
    assert deduped == ["新：他买了乌龙茶和红茶", "旧：他去爬了山"]
    assert legacy.covered_events(new, CONV) == {"e1", "e2"}
    assert new.list_notes(CONV)[0]["text"].startswith("新")  # 写入口径只看新库


def test_no_legacy_outside_v2(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "notes_dir", lambda scope: tmp_path / scope / "notes")
    assert paths.legacy_notes_dir("aveline") is None
    assert legacy.legacy_store(NoteStore("aveline")) is None


def test_retrieval_and_expand_see_uncovered_old_notes(stores):
    new, _old = stores
    retriever = NoteRetriever("aveline", store=new, gate=lambda *_a: set())
    hits = retriever.search("他去爬了山", conversation_id=CONV, use_vectors=False)
    assert hits and hits[0]["text"] == "旧：他去爬了山"
    texts = [h["text"] for h in retriever.search("乌龙茶", conversation_id=CONV, use_vectors=False)]
    assert "旧：他买了乌龙茶" in texts and "新：他买了乌龙茶和红茶" in texts  # 同段新旧都可检到
    old_id = next(n["note_id"] for n in legacy.readable_notes(new, CONV) if n["text"].startswith("旧"))
    found, error = expand_memory_tool.find_note("aveline", old_id, store=new)
    assert found and not error


def test_old_vectors_are_reused_not_recomputed(stores, tmp_path):
    _new, old = stores
    note = next(n for n in old.list_notes(CONV) if n["text"] == "旧：他去爬了山")
    stem = paths.notes_path("aveline", CONV).stem
    embeddings._write(tmp_path / "aveline" / "notes" / "_vectors" / f"{stem}.npz",
                      {note["note_id"]: np.ones(4, dtype=np.float32)})

    def boom(_texts):
        raise AssertionError("不应重算旧梗概的向量")

    vectors, computed = embeddings.load_vectors_counted("aveline", CONV, [note], boom)
    assert computed == 0 and note["note_id"] in vectors
