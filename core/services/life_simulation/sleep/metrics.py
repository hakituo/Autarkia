"""睡眠指标与噩梦（Mixin）。

起床时重算睡眠债 / 惯性 / 影响等级，睡眠中滚动噩梦与影响失效。
纯状态计算，不读外部服务。
"""

from __future__ import annotations

import random
from datetime import datetime

from ..sleep_models import SleepPhase, SleepRuntimeState

# 睡眠影响等级的有效时长（小时）：起床时刻起算，到点自动清零 impact_level。
_IMPACT_DURATION_HOURS = {"mild": 2.0, "medium": 4.0, "severe": 10.0}


class SleepMetricsMixin:
    """睡眠指标计算。"""

    def _estimate_sleep_debt(self, role_id: str, state: SleepRuntimeState) -> float:
        profile = self._get_profile(role_id)
        target = 8.0 - (profile.night_owl_tendency * 0.5)
        return max(0.0, round(target - float(state.last_sleep_duration_hours or 0.0), 2))

    def _estimate_sleep_inertia(self, role_id: str, state: SleepRuntimeState) -> float:
        profile = self._get_profile(role_id)
        base = profile.sleep_inertia_tendency * 65.0
        debt_penalty = min(25.0, state.sleep_debt_hours * 12.0)
        nightmare_penalty = {"none": 0.0, "mild": 8.0, "medium": 16.0, "severe": 28.0}.get(
            state.nightmare_level,
            0.0,
        )
        return min(100.0, base + debt_penalty + nightmare_penalty)

    def _estimate_impact_level(self, state: SleepRuntimeState) -> str:
        if state.nightmare_level == "severe" or state.sleep_debt_hours >= 2.5:
            return "severe"
        if state.nightmare_level == "medium" or state.sleep_debt_hours >= 1.2:
            return "medium"
        if state.nightmare_level == "mild" or state.sleep_debt_hours >= 0.4:
            return "mild"
        return "none"

    def _apply_impact_expiry(self, state: SleepRuntimeState, now: datetime) -> None:
        """让 impact_level 在 ``_IMPACT_DURATION_HOURS`` 后自动失效。

        历史问题：`quality_impact.duration_hours` 只被写入、全仓无人读取，
        `impact_level` 只在跨天 `_reset_daily_fields` 才清零。结果一次 severe 噩梦
        会惩罚**一整天**（每分钟多扣 0.1 energy），角色醒后约 7~8 小时就被钉在 0。

        锚点取 ``last_wake_ts``（impact_level 只在起床分支被赋值，锚点即起床时刻）；
        旧状态文件没有锚点（=0）时用同一规则补锚，而不是以「现在」起算——
        否则线上已惩罚半天的角色会被再续一整个时长。
        """
        level = str(state.impact_level or "none").strip().lower()
        if level not in _IMPACT_DURATION_HOURS:
            state.impact_level = "none"
            state.impact_expires_at_ts = 0.0
            return
        now_ts = now.timestamp()
        if state.impact_expires_at_ts <= 0:
            anchor_ts = float(state.last_wake_ts or 0.0) or now_ts
            state.impact_expires_at_ts = anchor_ts + _IMPACT_DURATION_HOURS[level] * 3600.0
        if now_ts >= state.impact_expires_at_ts:
            state.impact_level = "none"
            state.impact_expires_at_ts = 0.0

    def _maybe_roll_nightmare(self, role_id: str, state: SleepRuntimeState, now: datetime) -> None:
        if state.date != now.strftime("%Y-%m-%d"):
            return
        if state.phase != SleepPhase.SLEEPING:
            return
        if state.nightmare_level != "none":
            return
        profile = self._get_profile(role_id)
        threshold = max(0.02, min(0.25, profile.nightmare_tendency / 20.0))
        if random.random() >= threshold:
            return
        roll = random.random()
        if roll < 0.55:
            level = "mild"
        elif roll < 0.85:
            level = "medium"
        else:
            level = "severe"
        state.nightmare_level = level
        state.sleep_quality_score = max(
            25.0,
            state.sleep_quality_score - {"mild": 8.0, "medium": 18.0, "severe": 30.0}[level],
        )
        state.quality_impact.level = level
        state.quality_impact.duration_hours = _IMPACT_DURATION_HOURS[level]
        state.quality_impact.reason = "nightmare"
        state.push_event("nightmare", now.timestamp(), detail=f"噩梦等级 {level}")
