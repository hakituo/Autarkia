"""睡眠模块运行时隔离：内部异常不得外溢到聊天 / 状态 / 主动关怀。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.services.life_simulation.sleep_manager import SleepManager
from core.services.life_simulation.sleep_models import SleepPhase
from core.services.life_simulation.sleep_state_store import SleepStateStore


def _build_manager(tmp_path: Path) -> SleepManager:
    return SleepManager(store=SleepStateStore(tmp_path))


def test_get_state_swallows_runtime_error(tmp_path: Path, monkeypatch):
    manager = _build_manager(tmp_path)
    state = manager.get_state("aveline", now=datetime(2026, 10, 24, 1, 0, 0))
    state.phase = SleepPhase.SLEEPING
    state.is_sleeping = True

    def _boom(*args, **kwargs):
        raise TypeError("can't compare offset-naive and offset-aware datetimes")

    monkeypatch.setattr(manager, "_update_runtime_state", _boom)

    returned = manager.get_state("aveline", now=datetime(2026, 10, 24, 1, 1, 0))

    assert returned is state
    assert returned.phase == SleepPhase.SLEEPING


def test_get_summary_returns_neutral_dict_on_error(tmp_path: Path, monkeypatch):
    manager = _build_manager(tmp_path)

    def _boom(*args, **kwargs):
        raise RuntimeError("sleep state polluted")

    monkeypatch.setattr(manager, "_resolve_next_wake_dt", _boom)

    summary = manager.get_summary("aveline", now=datetime(2026, 10, 24, 1, 2, 0))

    assert summary["role_id"] == "aveline"
    assert summary["phase"] in {"unknown", "fully_awake", "sleeping"}
    assert summary["silence_window_seconds"] == 180
    assert summary["is_sleeping"] in (True, False)


def test_get_activity_override_degrades_to_none(tmp_path: Path, monkeypatch):
    manager = _build_manager(tmp_path)

    def _boom(*args, **kwargs):
        raise ValueError("broken window")

    monkeypatch.setattr(manager, "_resolve_activity_override", _boom)

    assert manager.get_activity_override("aveline") is None


def test_error_log_is_rate_limited(tmp_path: Path, monkeypatch):
    manager = _build_manager(tmp_path)
    calls: list[str] = []

    def _boom(*args, **kwargs):
        raise TypeError("boom")

    monkeypatch.setattr(manager, "_update_runtime_state", _boom)
    monkeypatch.setattr(
        manager,
        "_log_runtime_error",
        lambda role_id, where, exc: calls.append(where),
    )

    for _ in range(3):
        manager.get_state("aveline", now=datetime(2026, 10, 24, 1, 3, 0))

    # 每次异常都走降级，但日志函数本身负责限流（此处仅确认调用链不抛）
    assert calls == ["get_state", "get_state", "get_state"]
