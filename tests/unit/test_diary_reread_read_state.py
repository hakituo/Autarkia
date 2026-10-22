"""翻旧日记 · 查看日记触发点（on_diary_read）与状态存储单测。

她真的翻了旧日记时按实际读到的深度更新 streak；状态文件读写与
「同日合并 / 断档重置」逻辑在这里覆盖。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List

from core.services.journal.diary_reread.service import DiaryRereadService
from core.services.journal.diary_reread.state_store import (
    DiaryRereadState,
    DiaryRereadStateStore,
)
from core.services.journal.models import JournalEntry


class _NullStorage:
    """读触发点不查 storage，返回空即可。"""

    async def get_entries(self, date, scopes=None) -> List[JournalEntry]:
        return []


class _NullRng:
    def random(self) -> float:
        return 1.0

    def randint(self, low: int, high: int) -> int:
        return low


def _make_service(tmp_path: Path) -> DiaryRereadService:
    def factory(scope: str) -> DiaryRereadStateStore:
        return DiaryRereadStateStore(scope, state_path=tmp_path / f"{scope}.json")

    async def _publish(entry: JournalEntry, dt: datetime) -> None:  # 不应被调用
        raise AssertionError("读触发点不应发布日记条目")

    return DiaryRereadService(
        storage=_NullStorage(), publish_fn=_publish, rng=_NullRng(), state_store_factory=factory
    )


async def _load_state(tmp_path: Path, scope: str) -> DiaryRereadState:
    return await DiaryRereadStateStore(scope, state_path=tmp_path / f"{scope}.json").load()


# ── on_diary_read ──────────────────────────────────────────


async def test_read_event_records_depth_and_streak(tmp_path):
    service = _make_service(tmp_path)

    await service.on_diary_read("aveline", 3, now=datetime(2026, 10, 12, 23, 50))
    state = await _load_state(tmp_path, "aveline")
    assert state.last_reread_date == "2026-10-12"
    assert state.streak == 1
    assert state.last_depth_days == 3

    # 第二天再读：streak +1，深度取最大
    await service.on_diary_read("aveline", 2, now=datetime(2026, 10, 13, 14, 0))
    state = await _load_state(tmp_path, "aveline")
    assert state.streak == 2
    assert state.last_depth_days == 3


async def test_read_same_day_merges_without_double_count(tmp_path):
    service = _make_service(tmp_path)

    await service.on_diary_read("aveline", 2, now=datetime(2026, 10, 12, 20, 0))
    await service.on_diary_read("aveline", 7, now=datetime(2026, 10, 12, 22, 0))

    state = await _load_state(tmp_path, "aveline")
    assert state.streak == 1
    assert state.total_count == 1
    assert state.last_depth_days == 7


async def test_read_today_only_is_not_a_reread(tmp_path):
    service = _make_service(tmp_path)

    await service.on_diary_read("aveline", 0, now=datetime(2026, 10, 12, 20, 0))

    assert not (tmp_path / "aveline.json").exists()


async def test_read_non_persona_scope_is_ignored(tmp_path):
    service = _make_service(tmp_path)

    await service.on_diary_read("user", 5, now=datetime(2026, 10, 12, 20, 0))

    assert not (tmp_path / "user.json").exists()


# ── 状态存储 ───────────────────────────────────────────────


async def test_state_roundtrip_and_corrupt_file_fallback(tmp_path):
    path = tmp_path / "aveline.json"
    store = DiaryRereadStateStore("aveline", state_path=path)

    await store.save(
        DiaryRereadState(
            last_roll_date="2026-10-12",
            last_reread_date="2026-10-11",
            streak=2,
            max_streak=3,
            last_depth_days=12,
            total_count=4,
        )
    )
    loaded = await store.load()
    assert loaded.streak == 2 and loaded.max_streak == 3
    assert loaded.last_depth_days == 12 and loaded.total_count == 4
    assert loaded.last_reread_date == "2026-10-11"

    path.write_text("{ broken json", encoding="utf-8")
    assert (await store.load()).streak == 0  # 损坏时回到空状态，不抛


def test_apply_reread_gap_detection():
    state = DiaryRereadState()
    state.apply_reread("2026-10-10", 1, 5)
    state.apply_reread("2026-10-11", 2, 5)  # 连续
    assert state.streak == 2
    state.apply_reread("2026-10-13", 1, 5)  # 断了一天
    assert state.streak == 1
    assert state.max_streak == 2
    assert state.total_count == 3


def test_from_dict_tolerates_garbage():
    state = DiaryRereadState.from_dict({"streak": "x", "total_count": None})
    assert state.streak == 0 and state.total_count == 0
