"""按段作业编排与开关（v3 F3 · WP3）：开关、重跑、版本、退避、预算、零产出、开放段。"""

from __future__ import annotations

import asyncio
import threading

import pytest

from memory.nightly.segment_jobs import extractors
from memory.nightly.segment_jobs import run as seg_run
from memory.nightly.segment_jobs.inputs import SegmentParams, build_conversation_inputs
from memory.nightly.segment_jobs.testing import FakeExtractor
from memory.nightly.task_runner import NightlyTaskRunner
from memory.notes import NoteStore, paths

CONV = "web_role_aveline"
NIGHT = 10_000_000.0
DAY = 24 * 3600


class _Manager:
    def __init__(self, history_dir):
        self.user_id = "shared__scope__aveline"
        self.storage_scope = "aveline"
        self._memory_layout = {"history_dir": str(history_dir)}
        self.lock = threading.RLock()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "notes_dir", lambda scope: tmp_path / "notes" / scope)
    monkeypatch.setattr(
        seg_run, "resolve_distillation_perspective", lambda _m: {"role_id": "aveline"}
    )
    return _Manager(tmp_path / "memories"), NoteStore("aveline")


def _segments(turns=6, *, max_turns=2, now=NIGHT):
    events = []
    for index in range(turns):
        ts = 1000.0 + index * 60
        events.append(_msg(f"e-u{index}", "user", f"问{index}", ts, f"m{index}"))
        events.append(_msg(f"e-a{index}", "assistant", f"答{index}", ts + 1, f"m{index}"))
    return build_conversation_inputs(
        "aveline",
        CONV,
        events,
        params=SegmentParams(max_turns=max_turns),
        now=now,
        tree_reader=lambda _cid: events,
    )


def _msg(eid, role, content, ts, turn):
    return {
        "event_id": eid,
        "conversation_id": CONV,
        "role": role,
        "content": content,
        "timestamp": ts,
        "event_type": "chat_message",
        "message_id": turn,
    }


def _config(**extra):
    base = {
        "segment_extraction_enabled": True,
        "distillation_role_whitelist": ["aveline"],
        "segment_max_per_night": 0,
        "segment_max_chars_per_night": 0,
        "segment_max_seconds_per_night": 0,
    }
    base.update(extra)
    return base


def _run(env, extractor, *, now=NIGHT, segments=None, **config):
    manager, store = env
    return asyncio.run(
        seg_run.run_segment_jobs(
            manager.user_id,
            manager,
            _config(**config),
            extractor=extractor,
            note_store=store,
            segments=_segments() if segments is None else segments,
            now=now,
        )
    )


def test_disabled_makes_zero_calls(env):
    fake = FakeExtractor()
    report = _run(env, fake, segment_extraction_enabled=False)
    assert report == {"segment_extraction": "disabled"} and fake.calls == []


def test_not_whitelisted_and_no_extractor(env):
    fake = FakeExtractor()
    assert (
        _run(env, fake, distillation_role_whitelist=["ye"])["segment_extraction"]
        == "not_whitelisted"
    )
    assert fake.calls == []
    manager, store = env
    report = asyncio.run(
        seg_run.run_segment_jobs(manager.user_id, manager, _config(), note_store=store, segments=[])
    )
    assert report["segment_extraction"] == "no_extractor"
    extractors.register_extractor_factory(lambda _config: fake)
    report = asyncio.run(
        seg_run.run_segment_jobs(
            manager.user_id, manager, _config(), note_store=store, segments=_segments(), now=NIGHT
        )
    )
    assert report["done"] == 3 and len(fake.calls) == 3


def test_second_night_does_not_rerun_and_ledger_file_is_separate(env):
    manager, store = env
    fake = FakeExtractor()
    first = _run(env, fake)
    second = _run(env, fake, now=NIGHT + DAY)
    assert first["done"] == 3 and second["picked"] == 0
    assert len(fake.calls) == 3
    assert len(store.list_notes(CONV)) == 3
    nightly_dir = seg_run.segment_ledger_path(manager).parent
    assert [p.name for p in nightly_dir.iterdir()] == ["shared__scope__aveline_segment_jobs.json"]


def test_extractor_version_change_recomputes(env):
    _run(env, FakeExtractor("fake-1"))
    _run(env, FakeExtractor("fake-1", empty_on=lambda _i: True), now=NIGHT + DAY)  # 无事可做
    upgraded = FakeExtractor("fake-2")
    report = _run(env, upgraded, now=NIGHT + 2 * DAY)
    assert report["done"] == 3 and len(upgraded.calls) == 3


def test_skipped_under_old_version_is_requeued_after_upgrade(env):
    empty = FakeExtractor("fake-1", empty_on=lambda _i: True)
    report = _run(env, empty)
    assert report["skipped"] == 3
    assert report["ledger"]["skip_reasons"] == {"no_reusable_info": 3}
    assert _run(env, empty, now=NIGHT + DAY)["picked"] == 0  # 零产出不再重跑
    assert _run(env, FakeExtractor("fake-2"), now=NIGHT + 2 * DAY)["done"] == 3


def test_failure_backs_off_then_retries(env):
    failing = FakeExtractor(fail_on=lambda _i: True)
    report = _run(env, failing)
    assert report["failed"] == 3 and report["done"] == 0
    assert _run(env, failing, now=NIGHT + 3600)["picked"] == 0  # 退避中
    healed = FakeExtractor()
    assert _run(env, healed, now=NIGHT + DAY)["done"] == 3


def test_evidence_out_of_range_is_failed_not_written(env):
    _manager, store = env
    report = _run(env, FakeExtractor(out_of_range_on=lambda _i: True))
    assert report["failed"] == 3 and report["notes_rejected"] == 3
    assert store.list_notes(CONV) == []


def test_budget_picks_oldest_and_returns_rest(env):
    fake = FakeExtractor()
    segments = _segments()
    report = _run(env, fake, segment_max_per_night=1, segments=segments)
    assert report["picked"] == 1 and report["deferred"] == 2
    assert fake.calls == [segments[0].segment_id]
    assert report["ledger"]["states"] == {}  # 预算外不留账本条目 = pending
    _run(env, fake, segment_max_per_night=1, segments=segments, now=NIGHT + DAY)
    assert fake.calls == [segments[0].segment_id, segments[1].segment_id]


def test_wall_clock_budget_releases_leased_segments(env):
    fake = FakeExtractor()
    report = _run(env, fake, segment_max_seconds_per_night=1e-9)
    assert fake.calls == [] and report["released"] == 3
    assert report["ledger"]["states"] == {}


def test_open_segment_is_not_leased(env):
    fake = FakeExtractor()
    segments = _segments(now=1000.0 + 5 * 60 + 10)  # 尾段刚结束不久
    assert [item.closed for item in segments] == [True, True, False]
    report = _run(env, fake, segments=segments)
    assert report["done"] == 2 and segments[-1].segment_id not in fake.calls


def _scope_runner(config, calls):
    runner = NightlyTaskRunner(config)

    async def distill(_user, _manager):
        calls.append("distill")
        return 0

    return runner, distill


def test_task_runner_skips_segment_jobs_when_disabled(monkeypatch):
    calls = []
    runner, distill = _scope_runner({"segment_extraction_enabled": False}, calls)

    async def boom(*_args, **_kwargs):
        raise AssertionError("开关关闭时不应调用")

    monkeypatch.setattr(seg_run, "run_segment_jobs", boom)
    results = asyncio.run(runner.execute_scope_tasks("u", object(), distill))
    assert calls == ["distill"] and "segment_jobs" not in results


def test_task_runner_runs_segment_jobs_after_distillation(monkeypatch):
    calls = []
    runner, distill = _scope_runner({"segment_extraction_enabled": True}, calls)

    async def fake_run(user_id, _manager, _config):
        calls.append("segments")
        return {"segment_extraction": "ok", "user": user_id}

    monkeypatch.setattr(seg_run, "run_segment_jobs", fake_run)
    results = asyncio.run(runner.execute_scope_tasks("u", object(), distill))
    assert calls == ["distill", "segments"]
    assert results["segment_jobs"] == {"segment_extraction": "ok", "user": "u"}
