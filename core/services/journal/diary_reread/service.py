"""翻旧日记编排服务。

两个触发点，共用同一份跨天状态：

1. **写完日记时**（``on_diary_written``，由 JournalStorage.save_entry 调用）：
   按写日记的时刻分桶、掷概率，命中就找到一篇旧日记并写入一条
   ``type=diary_reread`` 的日记条目（flavor 短句），同时更新 streak。
   每个角色每个归属日最多 roll 一次。
2. **查看日记时**（``on_diary_read``，由 ReadDiaryTool 调用）：
   她真的翻了旧日记——既成事实，直接按实际读到的深度更新状态。

所有失败都只记日志，不阻断日记保存 / 读取主流程。
"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional, Tuple

from core.services.journal.diary_personas import is_diary_persona
from core.services.journal.models import JournalEntry
from core.services.journal.diary_reread.policy import (
    MAX_STREAK,
    build_reread_content,
    build_reread_tags,
    classify_time_bucket,
    effective_probability,
    normalize_excerpt,
    reread_mood,
    resolve_sleep_schedule,
    sample_days_back,
)
from core.services.journal.diary_reread.state_store import (
    DiaryRereadStateStore,
)
from core.services.journal.storage import JournalStorage
from core.utils.data_paths import resolve_data_scope_from_source
from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time, get_diary_target_date, ts_to_str

logger = get_logger("DiaryRereadService")

#: 命中后从抽样锚点向前找旧日记的最大回退天数
DEPTH_SEARCH_WINDOW = 14

#: 不参与翻旧触发的条目类型（系统内部条目）
_EXCLUDED_TYPES = {"event", "memory_distillation", "diary_reread"}

#: 日期下界保护（早于该日期的日记不存在，避免无意义回退）
_MIN_DIARY_DATE = datetime(2020, 1, 1)

PublishFn = Callable[[JournalEntry, datetime], Any]


async def _default_publish(entry: JournalEntry, dt: datetime) -> None:
    """默认落盘：存条目 + persona 导出 + 加权记忆（与 write_entry 尾部一致）。"""
    from core.services.journal.service import get_journal_service

    service = get_journal_service()
    await service.storage.save_entry(entry, dt)
    try:
        from core.services.journal.persona_exports import (
            get_persona_journal_export_service,
        )

        await get_persona_journal_export_service().export_after_entry(entry, dt)
    except Exception as exc:  # noqa: BLE001 - 导出失败不阻断状态更新
        logger.warning("翻旧日记条目导出失败: %s", exc)
    try:
        from core.services.journal.journal_helpers import (
            append_weighted_memory,
            should_skip_memory_append,
        )

        if not should_skip_memory_append(entry, service.settings):
            await asyncio.to_thread(append_weighted_memory, entry, service.settings)
    except Exception as exc:  # noqa: BLE001 - 记忆失败不阻断状态更新
        logger.warning("翻旧日记写入记忆失败: %s", exc)


class DiaryRereadService:
    """翻旧日记编排（依赖全部可注入，便于单测）。"""

    def __init__(
        self,
        storage: Optional[JournalStorage] = None,
        publish_fn: Optional[PublishFn] = None,
        rng: Optional[random.Random] = None,
        state_store_factory: Optional[Callable[[str], DiaryRereadStateStore]] = None,
    ):
        self._storage = storage if storage is not None else JournalStorage()
        self._publish_fn: PublishFn = publish_fn if publish_fn is not None else _default_publish
        self._rng = rng if rng is not None else random
        self._state_store_factory = state_store_factory or (
            lambda scope: DiaryRereadStateStore(scope)
        )
        self._stores: Dict[str, DiaryRereadStateStore] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    # ── 触发点 1：写完日记 ──────────────────────────────────

    async def on_diary_written(
        self, entry: JournalEntry, write_dt: Optional[datetime] = None
    ) -> Optional[JournalEntry]:
        """写完一条角色日记后的概率性翻旧。返回生成的翻旧条目（未命中为 None）。"""
        scope = self._persona_scope(entry)
        if scope is None:
            return None
        try:
            write_dt = self._resolve_write_dt(entry, write_dt)
            anchor = get_diary_target_date(write_dt)
            attr_key = anchor.strftime("%Y-%m-%d")
            lock = self._lock_for(scope)
            async with lock:
                state = await self._store_for(scope).load()
                if state.last_roll_date == attr_key:
                    return None  # 当天已 roll 过，不重复
                state.last_roll_date = attr_key
                bucket = classify_time_bucket(write_dt, resolve_sleep_schedule(scope, write_dt))
                probability = effective_probability(bucket, state.streak)
                if self._rng.random() >= probability:
                    await self._store_for(scope).save(state)
                    return None
                effective_streak = min(state.streak + 1, MAX_STREAK)
                days_back = sample_days_back(self._rng, effective_streak)
                found = await self._find_nearest_entry(scope, anchor - timedelta(days=days_back))
                if found is None:
                    # 没有可翻的旧日记：消费掉今天的 roll，但不记事件
                    await self._store_for(scope).save(state)
                    return None
                found_date, excerpt = found
                actual_days = max(0, (anchor.date() - found_date.date()).days)
                reread_entry = self._build_entry(
                    scope, write_dt, bucket, actual_days, found_date, anchor, excerpt,
                    source_timestamp=float(getattr(entry, "timestamp", 0.0) or 0.0),
                )
                await self._publish_fn(reread_entry, write_dt)
                state.apply_reread(attr_key, actual_days, MAX_STREAK)
                await self._store_for(scope).save(state)
                logger.info(
                    "翻旧日记触发 scope=%s bucket=%s days_back=%s streak=%s",
                    scope,
                    bucket,
                    actual_days,
                    state.streak,
                )
                return reread_entry
        except Exception as exc:  # noqa: BLE001 - 翻旧失败绝不阻断日记写入
            logger.warning("翻旧日记触发失败 scope=%s: %s", scope, exc)
            return None

    # ── 触发点 2：查看日记 ──────────────────────────────────

    async def on_diary_read(
        self, scope: str, depth_days: int, now: Optional[datetime] = None
    ) -> None:
        """她真的翻了旧日记：按实际读到的深度更新跨天状态。"""
        normalized = str(scope or "").strip()
        if not is_diary_persona(normalized) or int(depth_days or 0) < 1:
            return
        try:
            now = now if now is not None else get_current_time()
            attr_key = get_diary_target_date(now).strftime("%Y-%m-%d")
            lock = self._lock_for(normalized)
            async with lock:
                state = await self._store_for(normalized).load()
                state.apply_reread(attr_key, int(depth_days), MAX_STREAK)
                await self._store_for(normalized).save(state)
        except Exception as exc:  # noqa: BLE001 - 记录失败不阻断日记读取
            logger.warning("记录翻旧日记状态失败 scope=%s: %s", normalized, exc)

    # ── 内部工具 ───────────────────────────────────────────

    @staticmethod
    def _persona_scope(entry: JournalEntry) -> Optional[str]:
        """只有注册角色自己写的条目才触发翻旧。"""
        if str(getattr(entry, "type", "") or "").strip().lower() in _EXCLUDED_TYPES:
            return None
        scope = resolve_data_scope_from_source(
            getattr(entry, "source", None), default="user"
        )
        if not is_diary_persona(scope):
            return None
        return scope

    @staticmethod
    def _resolve_write_dt(entry: JournalEntry, write_dt: Optional[datetime]) -> datetime:
        if write_dt is not None:
            return write_dt
        ts = float(getattr(entry, "timestamp", 0.0) or 0.0)
        if ts > 0:
            # ts_to_str 走项目统一时区，避免裸 datetime.fromtimestamp
            return datetime.strptime(ts_to_str(ts, "%Y-%m-%d %H:%M:%S"), "%Y-%m-%d %H:%M:%S")
        return get_current_time().replace(tzinfo=None)

    async def _find_nearest_entry(
        self, scope: str, anchor: datetime
    ) -> Optional[Tuple[datetime, str]]:
        """从锚点向前找最近一个有日记的日期，返回 (日期, 摘录)。"""
        for offset in range(DEPTH_SEARCH_WINDOW + 1):
            candidate = anchor - timedelta(days=offset)
            if candidate < _MIN_DIARY_DATE:
                break
            entries = await self._storage.get_entries(candidate, scopes=[scope])
            if entries:
                excerpt = next(
                    (e.content for e in entries if str(e.content or "").strip()), ""
                )
                return candidate, str(excerpt or "")
        return None

    @staticmethod
    def _build_entry(
        scope: str,
        write_dt: datetime,
        bucket: str,
        days_back: int,
        found_date: datetime,
        anchor: datetime,
        excerpt: str,
        source_timestamp: float = 0.0,
    ) -> JournalEntry:
        # 时间戳优先用源条目的原始值（经 ts_to_str 往返会有秒级损失），
        # 缺失时才退回归一化后的本地时刻。
        return JournalEntry(
            timestamp=source_timestamp or write_dt.timestamp(),
            time_str=write_dt.strftime("%H:%M:%S"),
            type="diary_reread",
            content=build_reread_content(
                bucket, days_back, found_date, anchor, normalize_excerpt(excerpt)
            ),
            mood=reread_mood(bucket),
            tags=build_reread_tags(bucket, days_back),
            source=scope,
        )

    def _store_for(self, scope: str) -> DiaryRereadStateStore:
        store = self._stores.get(scope)
        if store is None:
            store = self._state_store_factory(scope)
            self._stores[scope] = store
        return store

    def _lock_for(self, scope: str) -> asyncio.Lock:
        lock = self._locks.get(scope)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[scope] = lock
        return lock


_INSTANCE: Optional[DiaryRereadService] = None


def get_diary_reread_service() -> DiaryRereadService:
    """进程内单例（写日记 / 读日记两个挂点共用）。"""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = DiaryRereadService()
    return _INSTANCE
