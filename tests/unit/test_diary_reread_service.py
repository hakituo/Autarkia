"""翻旧日记 · 写日记触发点（on_diary_written）单测。

storage / publish / rng / state_store 全部注入，不碰真实 companion_data。
查看日记触发点与状态存储的测试见 test_diary_reread_read_state.py。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from core.services.journal.diary_reread.service import DiaryRereadService
from core.services.journal.diary_reread.state_store import (
    DiaryRereadState,
    DiaryRereadStateStore,
)
from core.services.journal.models import JournalEntry

# 2026-10-12 是周一；23:47 属深夜档（aveline 23:00 睡），06:30 清早档，14:00 偶然档
MONDAY_2347 = datetime(2026, 10, 12, 23, 47)
MONDAY_0630 = datetime(2026, 10, 12, 6, 30)
MONDAY_1400 = datetime(2026, 10, 12, 14, 0)


class FixedRng:
    """random 值固定；randint 钳到样本区间内。"""

    def __init__(self, value: float, randint_value: int = 3):
        self._value = value
        self._randint_value = randint_value

    def random(self) -> float:
        return self._value

    def randint(self, low: int, high: int) -> int:
        return min(max(self._randint_value, low), high)


class FakeStorage:
    """按日期返回预制条目的假 storage（签名与 JournalStorage.get_entries 一致）。"""

    def __init__(self, entries_by_date: Optional[Dict[str, List[JournalEntry]]] = None):
        self._entries = entries_by_date or {}

    async def get_entries(self, date, scopes=None):
        return list(self._entries.get(date.strftime("%Y-%m-%d"), []))


class PublishRecorder:
    def __init__(self):
        self.published: List[tuple] = []

    async def __call__(self, entry: JournalEntry, dt: datetime) -> None:
        self.published.append((entry, dt))


def _entry(
    source: str = "aveline",
    entry_type: str = "proactive",
    content: str = "旧日记正文",
    dt: Optional[datetime] = None,
) -> JournalEntry:
    return JournalEntry(
        timestamp=dt.timestamp() if dt is not None else 0.0,
        time_str="23:47:00",
        type=entry_type,
        content=content,
        source=source,
    )


def _make_service(
    tmp_path: Path, storage: FakeStorage, rng, recorder: PublishRecorder
) -> DiaryRereadService:
    def factory(scope: str) -> DiaryRereadStateStore:
        return DiaryRereadStateStore(scope, state_path=tmp_path / f"{scope}.json")

    return DiaryRereadService(
        storage=storage, publish_fn=recorder, rng=rng, state_store_factory=factory
    )


async def _load_state(tmp_path: Path, scope: str) -> DiaryRereadState:
    return await DiaryRereadStateStore(scope, state_path=tmp_path / f"{scope}.json").load()


async def _seed_state(tmp_path: Path, scope: str, state: DiaryRereadState) -> None:
    await DiaryRereadStateStore(scope, state_path=tmp_path / f"{scope}.json").save(state)


# ── 过滤：非角色 / 系统条目不触发 ─────────────────────────


async def test_non_persona_entry_never_triggers(tmp_path):
    storage, recorder = FakeStorage(), PublishRecorder()
    service = _make_service(tmp_path, storage, FixedRng(0.01), recorder)
    assert await service.on_diary_written(_entry(source="user"), MONDAY_2347) is None
    assert recorder.published == []


async def test_system_entry_types_excluded(tmp_path):
    recorder = PublishRecorder()
    service = _make_service(tmp_path, FakeStorage(), FixedRng(0.01), recorder)
    result = await service.on_diary_written(
        _entry(source="auto_heal", entry_type="event"), MONDAY_2347
    )
    assert result is None
    assert recorder.published == []


async def test_diary_reread_entry_does_not_retrigger(tmp_path):
    recorder = PublishRecorder()
    service = _make_service(tmp_path, FakeStorage(), FixedRng(0.01), recorder)
    result = await service.on_diary_written(
        _entry(entry_type="diary_reread"), MONDAY_2347
    )
    assert result is None
    assert recorder.published == []


# ── 命中 / 未命中 ─────────────────────────────────────────


async def test_write_hit_publishes_reread_entry(tmp_path):
    storage = FakeStorage({"2026-10-09": [_entry(dt=datetime(2026, 10, 9, 21, 0))]})
    recorder = PublishRecorder()
    service = _make_service(tmp_path, storage, FixedRng(0.10), recorder)

    result = await service.on_diary_written(_entry(dt=MONDAY_2347), MONDAY_2347)

    assert result is not None
    assert len(recorder.published) == 1
    published, dt = recorder.published[0]
    assert dt == MONDAY_2347
    assert published.type == "diary_reread"
    assert published.source == "aveline"
    assert "睡不着" in published.content
    assert "3天前（10-09）" in published.content
    assert "旧日记正文" in published.content
    assert published.tags == ["翻旧日记", "深夜失眠", "3天前"]
    state = await _load_state(tmp_path, "aveline")
    assert state.last_roll_date == "2026-10-12"
    assert state.last_reread_date == "2026-10-12"
    assert state.streak == 1
    assert state.last_depth_days == 3


async def test_write_miss_only_marks_roll_date(tmp_path):
    recorder = PublishRecorder()
    service = _make_service(tmp_path, FakeStorage({"2026-10-09": [_entry()]}), FixedRng(0.99), recorder)

    assert await service.on_diary_written(_entry(dt=MONDAY_2347), MONDAY_2347) is None
    assert recorder.published == []
    state = await _load_state(tmp_path, "aveline")
    assert state.last_roll_date == "2026-10-12"
    assert state.last_reread_date == ""
    assert state.streak == 0


async def test_roll_once_per_attribution_day(tmp_path):
    recorder = PublishRecorder()
    service = _make_service(tmp_path, FakeStorage({"2026-10-09": [_entry()]}), FixedRng(0.10), recorder)

    first = await service.on_diary_written(_entry(dt=MONDAY_2347), MONDAY_2347)
    # 同一天再写一条（哪怕 rng 仍然会命中），也不允许再翻
    second = await service.on_diary_written(_entry(dt=MONDAY_2347), MONDAY_2347)

    assert first is not None
    assert second is None
    assert len(recorder.published) == 1


async def test_no_old_diary_consumes_roll_without_event(tmp_path):
    recorder = PublishRecorder()
    service = _make_service(tmp_path, FakeStorage({}), FixedRng(0.10), recorder)

    assert await service.on_diary_written(_entry(dt=MONDAY_2347), MONDAY_2347) is None
    assert recorder.published == []
    state = await _load_state(tmp_path, "aveline")
    assert state.last_roll_date == "2026-10-12"
    assert state.last_reread_date == ""


async def test_find_nearest_walks_back_to_existing_day(tmp_path):
    # 抽样锚点是 10-09，但只有 10-06 有日记 → 回退 3 天命中
    storage = FakeStorage({"2026-10-06": [_entry(content="上周的记录")]})
    recorder = PublishRecorder()
    service = _make_service(tmp_path, storage, FixedRng(0.10), recorder)

    result = await service.on_diary_written(_entry(dt=MONDAY_2347), MONDAY_2347)

    assert result is not None
    assert "6天前（10-06）" in result.content
    assert "上周的记录" in result.content


# ── 时段风味 ───────────────────────────────────────────────


async def test_early_morning_uses_casual_flavor(tmp_path):
    # 06:30 写日记 → 归属日 10-11；抽 1 天前锚点 10-10，回退到 10-08 命中
    storage = FakeStorage({"2026-10-08": [_entry(content="周日的记录")]})
    recorder = PublishRecorder()
    service = _make_service(tmp_path, storage, FixedRng(0.10, randint_value=1), recorder)

    result = await service.on_diary_written(_entry(dt=MONDAY_0630), MONDAY_0630)

    assert result is not None
    assert "醒得早" in result.content
    assert "3天前（10-08）" in result.content
    assert result.mood == "neutral"
    assert "清早闲翻" in result.tags


async def test_daytime_uses_stumble_flavor(tmp_path):
    storage = FakeStorage({"2026-10-11": [_entry()]})
    recorder = PublishRecorder()
    service = _make_service(tmp_path, storage, FixedRng(0.10, randint_value=1), recorder)

    result = await service.on_diary_written(_entry(dt=MONDAY_1400), MONDAY_1400)

    assert result is not None
    assert result.content.startswith("偶然翻到")
    assert "1天前（10-11）" in result.content
    assert "偶然翻到" in result.tags


# ── streak 加深影响概率 ────────────────────────────────────


async def test_second_night_bonus_makes_0_50_a_hit(tmp_path):
    # 前一夜（归属日 10-11）已翻过 → 今晚 0.45+0.10=0.55，0.50 命中
    await _seed_state(
        tmp_path, "aveline", DiaryRereadState(last_reread_date="2026-10-11", streak=1)
    )
    # 0.50 的抽样落在第二桶（4-7 天），故预置 10-07 的旧日记
    storage = FakeStorage({"2026-10-07": [_entry()]})
    recorder = PublishRecorder()
    service = _make_service(tmp_path, storage, FixedRng(0.50, randint_value=5), recorder)

    result = await service.on_diary_written(_entry(dt=MONDAY_2347), MONDAY_2347)

    assert result is not None
    assert (await _load_state(tmp_path, "aveline")).streak == 2


async def test_first_night_0_50_is_a_miss(tmp_path):
    recorder = PublishRecorder()
    service = _make_service(tmp_path, FakeStorage({"2026-10-09": [_entry()]}), FixedRng(0.50), recorder)

    assert await service.on_diary_written(_entry(dt=MONDAY_2347), MONDAY_2347) is None


async def test_streak_caps_at_five(tmp_path):
    await _seed_state(
        tmp_path, "aveline", DiaryRereadState(last_reread_date="2026-10-11", streak=5)
    )
    recorder = PublishRecorder()
    service = _make_service(tmp_path, FakeStorage({"2026-10-09": [_entry()]}), FixedRng(0.10), recorder)

    await service.on_diary_written(_entry(dt=MONDAY_2347), MONDAY_2347)

    assert (await _load_state(tmp_path, "aveline")).streak == 5


async def test_skip_a_night_resets_streak(tmp_path):
    await _seed_state(
        tmp_path, "aveline", DiaryRereadState(last_reread_date="2026-10-09", streak=4)
    )
    recorder = PublishRecorder()
    service = _make_service(tmp_path, FakeStorage({"2026-10-09": [_entry()]}), FixedRng(0.10), recorder)

    await service.on_diary_written(_entry(dt=MONDAY_2347), MONDAY_2347)

    assert (await _load_state(tmp_path, "aveline")).streak == 1
