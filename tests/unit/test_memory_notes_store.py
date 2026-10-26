"""v3 F3 WP2：派生笔记库。"""

import pytest

from memory.notes import NoteStore, paths


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "notes_dir", lambda scope: tmp_path / scope)
    return NoteStore("aveline")


def D(text, ev=("e1",), kind="fact"):
    return {"kind": kind, "text": text, "source_event_ids": ev}


SRC = ("e1", "e2", "e3")


def test_path_monkeypatched(store, tmp_path):
    store.replace_segment("c1", "s1", "v1", [D("a")], segment_source_event_ids=SRC)
    assert (tmp_path / "aveline" / "c1.json").exists()


def test_rerun_no_duplicates_and_has_segment(store):
    for _ in range(2):
        store.replace_segment("c1", "s1", "v1", [D("a b"), D("a  b")], segment_source_event_ids=SRC)
    notes = store.list_notes("c1")
    assert len(notes) == 1
    assert notes[0]["visibility"] == "tree_local" and notes[0]["valid_from"] is None
    assert store.has_segment("c1", "s1", "v1")


def test_version_change_not_done_and_history_kept(store):
    store.replace_segment("c1", "s1", "v1", [D("a")], segment_source_event_ids=SRC)
    assert not store.has_segment("c1", "s1", "v2")
    store.replace_segment("c1", "s1", "v2", [D("b")], segment_source_event_ids=SRC)
    assert [n["text"] for n in store.list_notes("c1")] == ["b"]
    assert store.segment_history("c1", "s1")[0]["extractor_version"] == "v1"


def test_out_of_range_evidence_rejected(store):
    r = store.replace_segment(
        "c1", "s1", "v1", [D("ok"), D("bad", ev=("zz",)), D("mix", ev=("e1", "zz"))],
        segment_source_event_ids=SRC,
    )
    assert (r.written, r.rejected) == (1, 2)


def test_all_rejected_is_not_done(store):
    store.replace_segment("c1", "s1", "v1", [D("bad", ev=("zz",))], segment_source_event_ids=SRC)
    assert not store.has_segment("c1", "s1", "v1")


def test_atomic_replace_failure_keeps_old(store, monkeypatch):
    store.replace_segment("c1", "s1", "v1", [D("old")], segment_source_event_ids=SRC)
    from memory.notes import store as mod

    def boom(*a, **k):
        raise OSError("disk")

    monkeypatch.setattr(mod, "safe_json_dump", boom)
    with pytest.raises(OSError):
        store.replace_segment("c1", "s1", "v1", [D("new"), D("new2")], segment_source_event_ids=SRC)
    assert [n["text"] for n in store.list_notes("c1")] == ["old"]


def test_drop_segment(store):
    store.replace_segment("c1", "s1", "v1", [D("a")], segment_source_event_ids=SRC)
    assert store.drop_segment("c1", "s1")
    assert not store.has_segment("c1", "s1", "v1") and store.list_notes("c1") == []
    assert store.segment_history("c1", "s1")[-1]["dropped"]
    assert not store.drop_segment("c1", "nope")


def test_importance_zero_kept_and_bad_value_tolerated(store):
    store.replace_segment(
        "c1", "s1", "v1",
        [{**D("a"), "importance": 0}, {**D("b"), "importance": "x"}],
        segment_source_event_ids=SRC,
    )
    imp = {n["text"]: n["importance"] for n in store.list_notes("c1")}
    assert imp == {"a": 0.0, "b": 0.5}


def test_sanitized_conversation_ids_do_not_collide(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "notes_dir", lambda scope: tmp_path)
    assert paths.notes_path("s", "a/b") != paths.notes_path("s", "a:b")
    assert paths.notes_path("s", "plain") == tmp_path / "plain.json"
