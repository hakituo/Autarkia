"""睡眠阶段切换的上游事件触发（Mixin）。

进入 SLEEPING / WAKING_UP 时决定要不要发「晚安」「早安」主动消息，
以及判断用户是否正在跟该角色聊天（用于打断睡觉↔被叫醒的震荡）。
"""

from __future__ import annotations

from datetime import datetime

from core.character.runtime_roles import is_autonomous_role
from core.utils.logger import get_logger

from ..sleep_models import SleepPhase

logger = get_logger(__name__)


class SleepTriggersMixin:
    """入睡 / 起床事件触发。"""

    def _on_enter_sleeping(
        self,
        role_id: str,
        prev_phase: "SleepPhase",
        now: datetime,
        is_sleep_again: bool = False,
    ) -> None:
        """角色刚进入 SLEEPING 状态时触发主动晚安消息。

        角色运行资格属于通用 Character Runtime；这里仅消费资格并调用
        Active Care 的主动消息发送能力。
        """
        if prev_phase == SleepPhase.SLEEPING:
            return
        if not is_autonomous_role(role_id):
            logger.debug(
                "角色 %s 未启用自主角色运行时，跳过%s主动消息触发",
                role_id,
                "睡回去" if is_sleep_again else "晚安",
            )
            return
        # 2026-09-22 深夜免打扰：用户此刻正在跟该角色聊天时，不发"我先睡了"的
        # 告别消息。起因：角色作息引擎在凌晨反复在 sleeping / 被叫醒之间震荡，
        # 每轮都触发一次 goodnight_proactive；其 prompt 模板会硬塞
        # "现在是深夜 / 你要睡了 / 说句告别"，导致用户在正常聊天时被反复催睡。
        # 语义上，人正在跟你说话时不该冒出来告别；等用户安静下来（超过宽限期）
        # 后若仍在睡眠窗口，下一次进入 SLEEPING 时会正常补发。
        if self._is_user_chatting_with_role(role_id):
            logger.info(
                "角色 %s 进入 SLEEPING 但用户正在聊天，跳过%s主动消息",
                role_id,
                "睡回去" if is_sleep_again else "晚安",
            )
            return
        try:
            from core.services.active_care.goodnight_proactive import (
                trigger_character_goodnight_async,
            )

            trigger_character_goodnight_async(role_id, is_sleep_again=is_sleep_again)
            logger.info(
                "角色 %s 进入 SLEEPING（prev=%s, is_sleep_again=%s），已异步触发%s主动消息",
                role_id,
                getattr(prev_phase, "value", prev_phase),
                is_sleep_again,
                "睡回去" if is_sleep_again else "晚安",
            )
        except Exception as exc:
            logger.warning(
                "角色 %s 触发%s主动消息失败: %s",
                role_id,
                "睡回去" if is_sleep_again else "晚安",
                exc,
            )

    def _on_enter_waking_up(
        self,
        role_id: str,
        prev_phase: "SleepPhase",
        now: datetime,
        wake_dt: datetime,
        is_stay_up_recovery: bool = False,
    ) -> None:
        """角色刚进入 WAKING_UP 状态时触发主动起床问候消息。"""
        if prev_phase == SleepPhase.WAKING_UP:
            return
        if not is_autonomous_role(role_id):
            logger.debug(
                "角色 %s 未启用自主角色运行时，跳过起床问候消息触发",
                role_id,
            )
            return
        try:
            from core.services.active_care.good_morning_proactive import (
                trigger_character_good_morning_async,
            )

            trigger_character_good_morning_async(
                role_id, is_stay_up_recovery=is_stay_up_recovery,
            )
            logger.info(
                "角色 %s 进入 WAKING_UP（prev=%s, is_stay_up_recovery=%s），已异步触发起床问候消息",
                role_id,
                getattr(prev_phase, "value", prev_phase),
                is_stay_up_recovery,
            )
        except Exception as exc:
            logger.warning(
                "角色 %s 触发起床问候消息失败: %s",
                role_id,
                exc,
            )

    def _is_user_chatting_with_role(self, role_id: str) -> bool:
        """用户最近是否正在与该角色聊天（用于打断睡觉↔被叫醒的震荡循环）。

        实现走 ``UserActivityTracker.is_active_for_scope``，只认"用户跟这个
        角色说话"，避免用户在跟 A 角色聊天时把 B 角色的睡眠也一并绕过。

        宽限期可由 ``life_simulation.role_awake_while_user_chatting_grace_seconds``
        配置（默认 600s）。异常时保守返回 False：宁可让角色照常睡，也不要
        因为上游抖动把睡眠窗口整体失效。
        """
        try:
            from core.services.active_care.core.service import get_active_care_service

            ac = get_active_care_service()
            if not ac:
                return False
            scheduler = getattr(ac, "peer_chat_scheduler", None)
            if not scheduler:
                return False
            tracker = getattr(scheduler, "_user_activity_tracker", None)
            if tracker is None:
                return False
            from core.services.active_care.peer_chat.user_activity import (
                resolve_role_scope,
            )
            from core.utils.config_accessor import get_config

            scope = resolve_role_scope(role_id)
            if not scope:
                return False
            grace = float(
                get_config(
                    "life_simulation.role_awake_while_user_chatting_grace_seconds",
                    default=600.0,
                )
            )
            return bool(tracker.is_active_for_scope(scope, grace))
        except Exception as exc:
            logger.debug(
                "角色 %s 判断用户是否在聊天失败（按未在聊天处理）: %s", role_id, exc
            )
            return False
