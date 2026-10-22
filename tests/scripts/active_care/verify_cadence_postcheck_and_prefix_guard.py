"""验证决策后频控复检 + 状态报备前缀发送门（2026-10-12 线上两起事件复刻）。

事件一（10/12 12:03，报备前缀 + 连问）：
    11:17 已主动问"快中午了，打算吃点啥？"（curious_question:food），用户未回；
    12:03 又以 share_thought 发出"在炒菜。你中午一般自己做饭还是点外卖？"。
    旧链路两个洞：
      1. 决策后复检是死接线，同题材冷却永远拿到 general；
      2. share_thought 即便带问号也不适用未回复抑制；
      3. 发送门只抓"话说/对了"转场词，抓不到"在炒菜。"式状态报备前缀。

事件二（10/11 10:31，回归消息复述正常对话）：
    10:29 正常对话刚回复过，132 秒后活动回归消息又复述了同一内容。
    旧宽限只有 90 秒，回归消息模板也没禁止复述刚说过的话。

本脚本纯离线判定，不调用 LLM。
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))


def _now() -> float:
    return time.time()


class Incident1012PostcheckCase(unittest.IsolatedAsyncioTestCase):
    """10/12：连问 + 报备前缀必须被复检与发送门拦住。"""

    def test_second_food_question_blocked_by_postcheck(self):
        """46 分钟前 food 提问未回复 → share_thought 形态的再提问被复检拦截。"""
        from core.services.active_care.cadence.cadence_guard import CadenceGuard

        state = {
            "last_proactive_at": _now() - 46 * 60,
            "last_proactive_type": "curious_question",
            "last_proactive_replied": False,
            "last_sent_topic": "curious_question:food",
        }
        verdict = CadenceGuard().evaluate_final_text(
            now=_now(),
            intent="share_thought",
            final_text="在炒菜。你中午一般自己做饭还是点外卖？",
            proactive_state=state,
        )
        self.assertFalse(verdict.allowed, "决策后复检应拦截未回复的换名追问")
        self.assertEqual(verdict.reason, "last_proactive_unanswered")
        self.assertGreaterEqual(verdict.retry_after_minutes, 15)

    def test_replied_but_same_meal_group_still_blocked(self):
        """用户回了上一条，但 3 小时同题材窗口内仍不得换 intent 再问吃饭。"""
        from core.services.active_care.cadence.cadence_guard import CadenceGuard

        state = {
            "last_proactive_at": _now() - 90 * 60,
            "last_proactive_type": "curious_question",
            "last_proactive_replied": True,
            "last_sent_topic": "curious_question:food",
        }
        verdict = CadenceGuard().evaluate_final_text(
            now=_now(),
            intent="share_thought",
            final_text="你做饭还是点外卖？",
            proactive_state=state,
        )
        self.assertFalse(verdict.allowed)
        self.assertEqual(verdict.reason, "cadence_same_topic_group")

    def test_prefixed_status_report_rejected_by_send_gate(self):
        """发送门识别'在炒菜。+ 提问'，交给压缩一步而不是直接发送。"""
        from core.services.active_care.postprocess.send_validator import (
            ActiveCareSendValidator,
        )

        result = ActiveCareSendValidator().validate(
            "在炒菜。你中午一般自己做饭还是点外卖？", "share_thought"
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "padded_status_report")

    def test_plain_colloquial_question_passes(self):
        """去掉报备前缀和书面化冗余后的口语问法应直接放行。"""
        from core.services.active_care.postprocess.send_validator import (
            ActiveCareSendValidator,
        )

        result = ActiveCareSendValidator().validate(
            "你做饭还是点外卖？", "share_thought"
        )
        self.assertTrue(result.allowed)


class Incident1011ActivityReturnCase(unittest.IsolatedAsyncioTestCase):
    """10/11：对话刚收尾 132 秒，回归消息应顺延且模板禁止复述。"""

    def test_return_grace_covers_132_second_gap(self):
        from core.services.character_daily.reply_policy_support import (
            ACTIVITY_RETURN_GRACE_SECONDS,
        )

        # 事件间隔 132 秒，旧宽限 90 秒漏过；新专用宽限必须覆盖
        self.assertGreaterEqual(ACTIVITY_RETURN_GRACE_SECONDS, 300)
        self.assertGreater(ACTIVITY_RETURN_GRACE_SECONDS, 132)

    async def test_return_message_deferred_while_user_recently_active(self):
        """最近活跃判定为 True 时，回归决策必须顺延（不生成离场消息）。"""
        from core.services.character_daily.activity_return import core as return_core

        ac = object()
        with patch.object(
            return_core, "is_user_recently_active", return_value=True
        ) as mock_active:
            deferred = await return_core._decide_work_return_should_defer(
                ac, "private_1__persona__core_aveline", "aveline", "cooking"
            )
        self.assertTrue(deferred)
        # 必须使用回归专用宽限而非通用 90 秒
        self.assertEqual(
            mock_active.call_args.kwargs.get("lookback_seconds"),
            300.0,
        )

    def test_return_templates_forbid_restating_dialogue(self):
        """三个回归/告别模板都必须明确禁止复述刚才正常对话的内容。"""
        from core.agents.chat_agent_components.persona_system.prompt import (
            active_care_prompts_tasks as tasks,
        )
        from core.services.character_daily.activity_return.instruction import (
            build_activity_start_farewell_instruction,
            build_return_instruction,
        )

        task_tpl = tasks.TASK_ACTIVITY_RETURN_PROACTIVE_TEMPLATE
        self.assertIn("不得复述", task_tpl)
        self.assertIn("不要提问", task_tpl)

        work_return = build_return_instruction("aveline", "cooking", "work")
        self.assertIn("不得复述", work_return)

        farewell = build_activity_start_farewell_instruction("aveline", "cooking")
        self.assertIn("不得复述", farewell)

    def test_activity_return_keeps_length_but_not_style_exemption(self):
        """回归消息豁免长度压缩，但不豁免报备前缀+提问风格门。"""
        from core.services.active_care.postprocess.send_validator import (
            POKE_LENGTH_EXEMPT_TYPES,
            POKE_STYLE_EXEMPT_TYPES,
            ActiveCareSendValidator,
        )

        self.assertIn("activity_return_proactive", POKE_LENGTH_EXEMPT_TYPES)
        self.assertNotIn("activity_return_proactive", POKE_STYLE_EXEMPT_TYPES)

        validator = ActiveCareSendValidator()
        # 长告别（无提问）仍受长度豁免保护
        long_farewell = (
            "我先回去做饭啦，你也记得按时吃东西，别饿着了，今天上班别太累，晚上再聊。"
        )
        self.assertTrue(
            validator.validate(long_farewell, "activity_return_proactive").allowed
        )
        # 报备状态 + 追问必须被拦
        blocked = validator.validate(
            "在做饭。你要不要一起？", "activity_return_proactive"
        )
        self.assertFalse(blocked.allowed)
        self.assertEqual(blocked.reason, "padded_status_report")


class StylePromptColloquialRuleCase(unittest.TestCase):
    """生成层 P5 软规则：口语化 + 反例对照。"""

    def test_proactive_style_rules_require_colloquial(self):
        from core.agents.chat_agent_components.persona_system.prompt import (
            active_care_prompts_style as style,
        )

        self.assertIn("口语", style.PROACTIVE_SHORT_POKE_RULES)
        self.assertIn(
            "你中午一般自己做饭还是点外卖？",
            style.PROACTIVE_SHORT_POKE_EXAMPLES,
        )
        self.assertIn("你做饭还是点外卖？", style.PROACTIVE_SHORT_POKE_EXAMPLES)


if __name__ == "__main__":
    unittest.main(verbosity=2)
