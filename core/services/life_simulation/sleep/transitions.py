"""睡眠运行时状态推进（Mixin）。

只负责「当前时刻 + 作息 + 已锁定窗口 → 状态迁移」，不含对外 API，
也不做异常兜底；异常边界统一放在门面 `SleepManager.get_state`。
窗口与时间的换算全部委托给 `windows` 纯函数模块。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time

from ..sleep_models import (
    NightWakeContext,
    SleepPhase,
    SleepQualityImpact,
    SleepRuntimeState,
)

logger = get_logger(__name__)


class SleepTransitionsMixin:
    """状态推进相关的内部方法集合。"""

    def _update_runtime_state(
        self,
        role_id: str,
        state: SleepRuntimeState,
        now: Optional[datetime] = None,
    ) -> None:
        dt = now or get_current_time()
        today = dt.strftime("%Y-%m-%d")
        if state.date and state.date != today:
            self._reset_daily_fields(state, dt)
        state.date = today
        sleep_dt, wake_dt = self._resolve_sleep_window(role_id, dt)
        # 入睡后以锁定的窗口为准，不跟着跨天后的作息档重算（见 _apply_locked_sleep_window）
        sleep_dt, wake_dt = self._apply_locked_sleep_window(
            state, sleep_dt, wake_dt, now=dt
        )
        state.planned_sleep_time = sleep_dt.strftime("%H:%M")
        state.planned_wake_time = wake_dt.strftime("%H:%M")
        state.current_sleep_duration_hours = 0.0

        if state.phase == SleepPhase.SLEEP_LATER and state.sleep_later_until_ts > 0:
            if dt.timestamp() >= state.sleep_later_until_ts:
                prev_phase = state.phase
                state.phase = SleepPhase.SLEEPING
                state.stay_up_activity = "idle"
                self._mark_sleep_started(role_id, state, dt, wake_dt=wake_dt)
                self._on_enter_sleeping(
                    role_id, prev_phase, dt, is_sleep_again=True,
                )

        in_sleep_window = sleep_dt <= dt < wake_dt
        actual_wake_ts = max(
            float(state.actual_wakeup_ts or 0.0),
            float(state.last_wake_ts or 0.0),
        )
        woke_during_current_sleep_window = bool(
            state.phase in (SleepPhase.WAKING_UP, SleepPhase.FULLY_AWAKE)
            and sleep_dt.timestamp() <= actual_wake_ts <= dt.timestamp()
        )
        if (
            in_sleep_window
            and not woke_during_current_sleep_window
            and state.phase not in (
                SleepPhase.NIGHT_AWAKE,
                SleepPhase.STAY_UP_LATE,
                SleepPhase.SLEEP_LATER,
            )
        ):
            prev_phase = state.phase
            state.phase = SleepPhase.SLEEPING
            if state.actual_sleep_start_ts <= 0:
                state.actual_sleep_start_ts = max(sleep_dt.timestamp(), 0.0)
            self._mark_sleep_started(role_id, state, dt, wake_dt=wake_dt)
            # 同一夜内再次入睡（被叫醒后睡回、熬夜补睡）说「睡回去」，
            # 只有首次入睡才发「我去睡了」的告别。
            self._on_enter_sleeping(
                role_id,
                prev_phase,
                dt,
                is_sleep_again=prev_phase
                in (
                    SleepPhase.WAKING_UP,
                    SleepPhase.NIGHT_AWAKE,
                    SleepPhase.SLEEP_LATER,
                    SleepPhase.STAY_UP_LATE,
                ),
            )

        if state.is_sleeping and state.actual_sleep_start_ts > 0:
            state.current_sleep_duration_hours = max(
                0.0,
                (dt.timestamp() - state.actual_sleep_start_ts) / 3600.0,
            )

        if dt >= wake_dt and state.phase == SleepPhase.SLEEPING:
            effective_sleep_start_ts = self._resolve_effective_sleep_start_ts(
                state,
                sleep_dt=sleep_dt,
                wake_dt=wake_dt,
            )
            effective_wakeup_ts = min(dt.timestamp(), wake_dt.timestamp())
            prev_phase = state.phase
            state.phase = SleepPhase.WAKING_UP
            state.is_sleeping = False
            state.actual_wakeup_ts = effective_wakeup_ts
            state.last_wake_ts = effective_wakeup_ts
            state.last_sleep_duration_hours = max(
                0.0,
                (effective_wakeup_ts - effective_sleep_start_ts) / 3600.0,
            )
            state.sleep_debt_hours = self._estimate_sleep_debt(role_id, state)
            state.sleep_inertia_score = self._estimate_sleep_inertia(role_id, state)
            state.overslept = dt > (wake_dt + timedelta(minutes=25))
            state.impact_level = self._estimate_impact_level(state)
            state.actual_sleep_start_ts = 0.0
            state.sleep_window_wake_ts = 0.0
            state.current_sleep_duration_hours = 0.0
            state.push_event("wakeup", dt.timestamp(), detail="按作息起床")
            self._on_enter_waking_up(
                role_id, prev_phase, dt, wake_dt, is_stay_up_recovery=False,
            )

        if dt >= wake_dt and state.phase in (
            SleepPhase.STAY_UP_LATE,
            SleepPhase.NIGHT_AWAKE,
            SleepPhase.SLEEP_LATER,
        ):
            prev_phase = state.phase
            state.phase = SleepPhase.WAKING_UP
            state.is_sleeping = False
            state.actual_wakeup_ts = wake_dt.timestamp()
            state.last_wake_ts = max(
                float(state.last_wake_ts or 0.0), wake_dt.timestamp()
            )
            state.stay_up_activity = "idle"
            state.sleep_later_until_ts = 0.0
            state.sleep_window_wake_ts = 0.0
            if state.actual_sleep_start_ts > 0:
                state.last_sleep_duration_hours = max(
                    0.0,
                    (wake_dt.timestamp() - state.actual_sleep_start_ts) / 3600.0,
                )
                state.actual_sleep_start_ts = 0.0
            state.sleep_debt_hours = self._estimate_sleep_debt(role_id, state)
            state.sleep_inertia_score = self._estimate_sleep_inertia(role_id, state)
            state.impact_level = self._estimate_impact_level(state)
            state.current_sleep_duration_hours = 0.0
            state.push_event(
                "wakeup", dt.timestamp(), detail="熬夜后白天恢复清醒"
            )
            self._on_enter_waking_up(
                role_id, prev_phase, dt, wake_dt, is_stay_up_recovery=True,
            )

        if state.phase == SleepPhase.WAKING_UP:
            elapsed = dt.timestamp() - float(state.actual_wakeup_ts or 0.0)
            if elapsed > 3600:
                state.phase = SleepPhase.FULLY_AWAKE
                state.sleep_inertia_score = max(0.0, state.sleep_inertia_score * 0.5)

        if not in_sleep_window and state.phase == SleepPhase.FULLY_AWAKE:
            state.is_sleeping = False

        self._maybe_roll_nightmare(role_id, state, dt)
        self._apply_impact_expiry(state, dt)
        self._persist()

    def _mark_sleep_started(
        self,
        role_id: str,
        state: SleepRuntimeState,
        now: datetime,
        wake_dt: Optional[datetime] = None,
    ) -> None:
        """登记一次入睡：补齐睡眠起点，并锁定这一觉的起床时刻。

        同一夜内再次入睡（被叫醒后睡回）沿用仍未到期的锁定值，避免起床时刻
        被后一次入睡往后推。
        """
        state.is_sleeping = True
        if state.actual_sleep_start_ts <= 0:
            state.actual_sleep_start_ts = now.timestamp()
        locked_wake_ts = float(state.sleep_window_wake_ts or 0.0)
        if locked_wake_ts > now.timestamp():
            return
        if wake_dt is not None and wake_dt.timestamp() > now.timestamp():
            state.sleep_window_wake_ts = wake_dt.timestamp()
            return
        state.sleep_window_wake_ts = self._resolve_next_wake_dt(role_id, now).timestamp()

    def _reset_daily_fields(self, state: SleepRuntimeState, dt: datetime) -> None:
        """跨天时重置日级睡眠字段，避免昨日夜间统计值残留污染今天的状态。"""
        state.nightmare_level = "none"
        state.impact_level = "none"
        state.impact_expires_at_ts = 0.0
        state.sleep_quality_score = 82.0
        state.sleep_inertia_score = 0.0
        state.sleep_debt_hours = 0.0
        state.night_wake_count = 0
        state.last_sleep_duration_hours = 0.0
        state.overslept = False
        state.night_wake = NightWakeContext()
        state.quality_impact = SleepQualityImpact()
        state.push_event(
            "daily_reset",
            dt.timestamp(),
            detail=f"跨天重置日级睡眠字段（{state.date} → {dt.strftime('%Y-%m-%d')}）",
        )
        logger.info(
            "角色 %s 跨天重置睡眠字段：%s → %s",
            state.role_id,
            state.date,
            dt.strftime("%Y-%m-%d"),
        )
