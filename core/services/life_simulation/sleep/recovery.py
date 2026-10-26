"""夜间被叫醒后的恢复决策（Mixin）。

静默窗口结束后判断「睡回去 / 再撑一会儿 / 熬夜」，
含 LLM 决策与确定性兜底。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from core.services.character_daily.role_names import ROLE_NAMES as _ROLE_NAMES
from core.utils.logger import get_logger
from core.utils.time_utils import get_current_time

from ..sleep_decision import build_fallback_decision, call_llm_sleep_decision
from ..sleep_models import SleepDecision, SleepPhase, SleepRuntimeState

logger = get_logger(__name__)


class SleepRecoveryMixin:
    """被叫醒后的恢复决策。"""

    async def finalize_sleep_recovery_check(
        self,
        role_id: str,
        now: Optional[datetime] = None,
    ) -> SleepRuntimeState:
        """在静默窗口结束后，判断角色是否睡回去或继续醒着。"""
        dt = now or get_current_time()
        state = self.get_state(role_id, now=dt)
        profile = self._get_profile(role_id)
        silence_seconds = max(0.0, dt.timestamp() - float(state.last_chat_ts or 0.0))
        if silence_seconds < float(profile.silence_window_seconds):
            return state
        if state.phase not in (
            SleepPhase.NIGHT_AWAKE,
            SleepPhase.STAY_UP_LATE,
            SleepPhase.SLEEP_LATER,
        ):
            return state

        # 被叫醒（NIGHT_AWAKE）：静默窗口已到即确定性睡回。
        if state.phase == SleepPhase.NIGHT_AWAKE:
            prev_phase = state.phase
            state.phase = SleepPhase.SLEEPING
            if state.actual_sleep_start_ts <= 0:
                state.actual_sleep_start_ts = dt.timestamp()
            state.stay_up_activity = "idle"
            state.sleep_later_until_ts = 0.0
            self._mark_sleep_started(role_id, state, dt)
            self._on_enter_sleeping(
                role_id, prev_phase, dt, is_sleep_again=True,
            )
            state.push_event(
                "sleep_recovery_decision",
                dt.timestamp(),
                detail="夜间被叫醒后静默结束，确定性睡回",
                decision=SleepDecision.RETURN_TO_SLEEP.value,
                stay_up_activity="idle",
                sleep_after_minutes=0,
            )
            self._persist()
            return state

        decision = await self._decide_after_silence(role_id, state, dt)
        if decision["decision"] == SleepDecision.RETURN_TO_SLEEP.value:
            prev_phase = state.phase
            state.phase = SleepPhase.SLEEPING
            if state.actual_sleep_start_ts <= 0:
                state.actual_sleep_start_ts = dt.timestamp()
            state.stay_up_activity = "idle"
            state.sleep_later_until_ts = 0.0
            self._mark_sleep_started(role_id, state, dt)
            self._on_enter_sleeping(
                role_id, prev_phase, dt, is_sleep_again=True,
            )
        elif decision["decision"] == SleepDecision.SLEEP_LATER.value:
            state.phase = SleepPhase.SLEEP_LATER
            state.is_sleeping = False
            state.stay_up_activity = decision["stay_up_activity"]
            minutes = max(5, min(180, int(decision["sleep_after_minutes"] or 15)))
            state.sleep_later_until_ts = dt.timestamp() + minutes * 60
        else:
            state.phase = SleepPhase.STAY_UP_LATE
            state.is_sleeping = False
            state.stay_up_activity = decision["stay_up_activity"]
            state.sleep_later_until_ts = 0.0
            if state.nightly_done_for_date == state.date:
                state.patch_pending = True

        state.push_event(
            "sleep_recovery_decision",
            dt.timestamp(),
            detail=str(decision.get("reason") or ""),
            decision=decision["decision"],
            stay_up_activity=decision["stay_up_activity"],
            sleep_after_minutes=decision["sleep_after_minutes"],
        )
        self._persist()
        return state

    async def _decide_after_silence(
        self,
        role_id: str,
        state: SleepRuntimeState,
        now: datetime,
    ) -> Dict[str, Any]:
        result = await self._call_llm_decision(role_id, state, now)
        if result:
            return result
        return self._fallback_decision(role_id, state, now)

    async def _call_llm_decision(
        self,
        role_id: str,
        state: SleepRuntimeState,
        now: datetime,
    ) -> Optional[Dict[str, Any]]:
        try:
            from core.services.scheduler import get_global_scheduler

            scheduler = get_global_scheduler()
            if scheduler is None:
                return None
            profile = self._get_profile(role_id)
            _, wake_dt = self._resolve_sleep_window(role_id, now)
            return await call_llm_sleep_decision(
                scheduler=scheduler,
                model_path=self._runtime_config.sleep_runtime_decision_model,
                role_id=role_id,
                role_name=_ROLE_NAMES.get(role_id, role_id),
                state=state,
                profile=profile,
                now=now,
                wake_dt=wake_dt,
            )
        except Exception as exc:
            logger.debug("睡眠 LLM 判定失败，将回退启发式: %s", exc)
            return None

    def _fallback_decision(
        self,
        role_id: str,
        state: SleepRuntimeState,
        now: datetime,
    ) -> Dict[str, Any]:
        profile = self._get_profile(role_id)
        _, wake_dt = self._resolve_sleep_window(role_id, now)
        return build_fallback_decision(
            state=state,
            profile=profile,
            now=now,
            wake_dt=wake_dt,
        )
