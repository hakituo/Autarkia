"""nightly 蒸馏作业状态机与公平积压（v3 F4）。

覆盖：去掉 24h 资格窗口、最旧优先 + 条数/字符预算、空正文显式 skipped、
失败退避与次数耗尽、租约过期回收、预算外退回 pending、账本落盘往返、
服务端按产物结算（缺条目 = failed，不整批当成功）。
"""

from __future__ import annotations

import asyncio
import threading

from memory.nightly import distillation_service as service_module
from memory.nightly.candidates import SKIP_EMPTY_CONTENT, collect_candidates
from memory.nightly.distillation_service import MemoryDistillationService
from memory.nightly.job_ledger import DistillJobLedger

NOW = 10_000_000.0
DAY = 86400.0


class _Manager:
    def __init__(self, memories):
        self.weighted_memories = {item["id"]: item for item in memories}
        self.lock = threading.RLock()
        self.user_id = "shared__scope__aveline"

    def update_memory_distillation(self, memory_id, summary, keywords, distillation_metadata=None):
        memory = self.weighted_memories.get(memory_id)
        if memory is None:
            return False
        memory["summary"] = summary
        memory["is_distilled"] = True
        return True


def _memory(memory_id, *, age_days, content="这是一段足够长、需要走 LLM 蒸馏的对话正文内容"):
    return {
        "id": memory_id,
        "content": content,
        "timestamp": NOW - age_days * DAY,
        "role": "user",
        "is_distilled": False,
    }


def _collect(manager, ledger, *, cap=50, max_chars=0, now=NOW):
    return collect_candidates(manager, now - 3600, cap, ledger=ledger, max_chars=max_chars, now=now)


def test_backlog_older_than_24h_is_still_eligible():
    manager = _Manager([_memory("old", age_days=30), _memory("new", age_days=0.5)])
    batch = _collect(manager, DistillJobLedger())
    assert [item["id"] for item in batch] == ["old", "new"]


def test_oldest_first_with_item_and_char_budget():
    memories = [_memory(f"m{i}", age_days=10 - i, content="x" * 40) for i in range(6)]
    manager = _Manager(list(reversed(memories)))
    batch = _collect(manager, DistillJobLedger(), cap=4, max_chars=100)
    assert [item["id"] for item in batch] == ["m0", "m1"]
    assert batch.backlog_total == 6 and batch.deferred == 4


def test_empty_content_is_skipped_explicitly_and_not_retried():
    ledger = DistillJobLedger()
    manager = _Manager([_memory("empty", age_days=3, content="  "), _memory("ok", age_days=2)])
    first = _collect(manager, ledger)
    assert [item["id"] for item in first] == ["ok"]
    assert first.newly_skipped == {SKIP_EMPTY_CONTENT: 1}
    assert ledger.state_of("empty") == "skipped"
    assert manager.weighted_memories["empty"]["is_distilled"] is False
    assert [item["id"] for item in _collect(manager, ledger)] == ["ok"]


def test_failure_backs_off_then_exhausts():
    ledger = DistillJobLedger(max_attempts=2, backoff_seconds=100.0)
    manager = _Manager([_memory("m", age_days=5)])
    ledger.mark_failed("m", "boom", now=NOW)
    assert len(_collect(manager, ledger, now=NOW + 50)) == 0
    assert len(_collect(manager, ledger, now=NOW + 101)) == 1
    ledger.mark_failed("m", "boom again", now=NOW + 101)
    assert len(_collect(manager, ledger, now=NOW + 10 * DAY)) == 0
    assert ledger.summary()["exhausted"] == 1


def test_expired_lease_returns_to_pool_and_release_resets():
    ledger = DistillJobLedger(lease_seconds=60.0)
    manager = _Manager([_memory("a", age_days=2), _memory("b", age_days=1)])
    ledger.lease(["a", "b"], now=NOW)
    assert len(_collect(manager, ledger, now=NOW + 30)) == 0
    assert len(_collect(manager, ledger, now=NOW + 61)) == 2
    ledger.release(["a"])
    assert ledger.state_of("a") == "pending"


def test_ledger_round_trip(tmp_path):
    path = tmp_path / "nightly" / "u_distill_jobs.json"
    ledger = DistillJobLedger(path)
    ledger.mark_failed("x", "err", now=NOW)
    ledger.mark_skipped("y", SKIP_EMPTY_CONTENT, now=NOW)
    ledger.save()
    reloaded = DistillJobLedger(path)
    assert reloaded.state_of("x") == "failed"
    assert reloaded.summary()["skip_reasons"] == {SKIP_EMPTY_CONTENT: 1}
    reloaded.mark_done("x")
    assert reloaded.state_of("x") == "pending"


def _service(monkeypatch, config, *, distill_only):
    monkeypatch.setattr(
        service_module,
        "resolve_distillation_perspective",
        lambda _manager: {"role_id": "aveline", "role_name": "Aveline"},
    )
    monkeypatch.setattr(service_module, "get_memory_distillation_model", lambda: None)

    async def fake_batch(self, scheduler, manager, messages, model, perspective):
        done = 0
        for message in messages:
            if message["id"] in distill_only:
                done += int(manager.update_memory_distillation(message["id"], "梗概", []))
        return done

    monkeypatch.setattr(MemoryDistillationService, "_distill_batch", fake_batch)
    return MemoryDistillationService({"distillation_role_whitelist": ["aveline"], **config}, lambda: None)


def test_service_settles_by_artifact_not_by_batch(monkeypatch):
    manager = _Manager([_memory("a", age_days=40), _memory("b", age_days=40.0001)])
    ledger = DistillJobLedger()
    manager._distill_job_ledger = ledger
    service = _service(monkeypatch, {}, distill_only={"a"})
    count = asyncio.run(service.distill_memories_async("u", manager))
    assert count == 1
    assert ledger.state_of("a") == "pending"  # done 不留账本条目，真源是 is_distilled
    assert manager.weighted_memories["a"]["is_distilled"] is True
    assert ledger.state_of("b") == "failed"


def test_service_releases_unprocessed_when_time_budget_runs_out(monkeypatch):
    manager = _Manager([_memory("a", age_days=3), _memory("b", age_days=2)])
    ledger = DistillJobLedger()
    manager._distill_job_ledger = ledger
    service = _service(monkeypatch, {"max_distill_seconds_per_night": 1e-9}, distill_only={"a", "b"})
    assert asyncio.run(service.distill_memories_async("u", manager)) == 0
    assert ledger.state_of("a") == "pending" and ledger.state_of("b") == "pending"
    assert manager.weighted_memories["a"]["is_distilled"] is False
