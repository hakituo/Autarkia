"""外部事件写入与活动覆盖（Mixin）。

被动回复、聊天活跃、日程引擎都通过这里改睡眠状态或读取活动覆盖，
是本模块唯一的「写入口」。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from core.utils.time_utils import get_current_time

from ..sleep_models import SleepPhase, SleepRuntimeState

# 起床后惯性期内把活动覆盖成 waking_up 的窗口（秒）
_WAKING_UP_OVERRIDE_WINDOW_SECONDS = 20 * 60


class SleepEventsMixin:
    """外部事件与活动覆盖。"""

    def notify_sleep_interruption(
        self,
        role_id: str,
        message: str = "",
        conversation_id: str = "",
        now: Optional[datetime] = None,
    ) -> SleepRuntimeState:
        """记录角色夜间被叫醒。"""
        dt = now or get_current_time()
        state = self.get_state(role_id, now=dt)
        if state.phase == SleepPhase.NIGHT_AWAKE:
            # 同一夜内已经被叫醒过：只刷新聊天时间，不重复记「夜间被吵醒」，
            # 否则用户在睡眠窗口内连发几条就会把 night_wake_count 刷爆。
            return self.notify_sleep_chat_activity(role_id, message=message, now=dt)
        profile = self._get_profile(role_id)
        state.phase = SleepPhase.NIGHT_AWAKE
        state.is_sleeping = False
        state.last_wake_ts = dt.timestamp()
        state.last_chat_ts = dt.timestamp()
        state.night_wake_count += 1
        state.night_wake.wake_ts = dt.timestamp()
        state.night_wake.last_chat_ts = dt.timestamp()
        state.night_wake.silence_window_seconds = int(profile.silence_window_seconds)
        state.night_wake.wake_reason = "user_message"
        if message:
            state.night_wake.messages.append(str(message))
            state.night_wake.messages = state.night_wake.messages[-10:]
        state.push_event(
            "sleep_interruption",
            dt.timestamp(),
            detail="夜间被消息叫醒",
            conversation_id=conversation_id,
        )
        self._persist()
        return state

    def notify_sleep_chat_activity(
        self,
        role_id: str,
        message: str = "",
        now: Optional[datetime] = None,
    ) -> SleepRuntimeState:
        """记录被叫醒后的后续聊天。"""
        dt = now or get_current_time()
        state = self.get_state(role_id, now=dt)
        state.last_chat_ts = dt.timestamp()
        state.night_wake.last_chat_ts = dt.timestamp()
        if message:
            state.night_wake.messages.append(str(message))
            state.night_wake.messages = state.night_wake.messages[-10:]
        if state.phase == SleepPhase.SLEEPING:
            state.phase = SleepPhase.NIGHT_AWAKE
            state.is_sleeping = False
        self._persist()
        return state

    def get_activity_override(
        self, role_id: str, now: Optional[datetime] = None
    ) -> Optional[str]:
        """为角色日常提供高优先级活动覆盖（异常时降级为「不覆盖」）。"""
        try:
            return self._resolve_activity_override(role_id, now=now)
        except Exception as exc:  # noqa: BLE001 - 边界隔离，禁止异常外溢
            self._log_runtime_error(role_id, "get_activity_override", exc)
            return None

    def _resolve_activity_override(
        self, role_id: str, now: Optional[datetime] = None
    ) -> Optional[str]:
        """真正的活动覆盖解析。"""
        dt = now or get_current_time()
        state = self.get_state(role_id, now=dt)
        if state.phase == SleepPhase.SLEEPING:
            # 2026-09-22 打断"睡觉↔被叫醒"震荡循环：
            # 角色按作息表入睡时，若用户正在跟该角色正常聊天，则不再把
            # 活动覆盖成 sleeping（sleeping 是 DND，会让 reply_policy 走
            # 静默累积 → 强制唤醒 → 计数重置 → 又判定在睡 的死循环，每轮
            # 还触发一次 goodnight_proactive 催用户睡觉）。
            # 语义选择：用户在聊 = 角色清醒陪着聊，符合"角色陪着我"的预期；
            # 用户安静下来超过宽限期后，睡眠窗口照常生效。
            # 仅对"按作息自主入睡"生效：被 /sleep 强制入睡或用户明确要求
            # 角色去睡时不绕过（那种场景角色本就不该继续陪聊）。
            if not self._is_user_chatting_with_role(role_id):
                return "sleeping"
        wake_elapsed = (
            dt.timestamp() - float(state.actual_wakeup_ts or 0.0)
            if float(state.actual_wakeup_ts or 0.0) > 0
            else float("inf")
        )
        if (
            state.phase == SleepPhase.WAKING_UP
            and state.sleep_inertia_score > 15
            and wake_elapsed <= _WAKING_UP_OVERRIDE_WINDOW_SECONDS
        ):
            return "waking_up"
        if state.phase == SleepPhase.NIGHT_AWAKE:
            return "idle"
        if state.phase == SleepPhase.STAY_UP_LATE:
            return "phone_scrolling" if state.stay_up_activity == "phone_scrolling" else "idle"
        if state.phase == SleepPhase.SLEEP_LATER:
            if state.stay_up_activity == "reading":
                return "reading"
            if state.stay_up_activity == "late_snack":
                return "idle"
            return "idle"
        return None

    def consume_patch_pending(self, role_id: str) -> bool:
        """消费熬夜补丁标记。"""
        state = self.get_state(role_id)
        if not state.patch_pending:
            return False
        state.patch_pending = False
        self._persist()
        return True
