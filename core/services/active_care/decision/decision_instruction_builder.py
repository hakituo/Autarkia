"""主动关怀决策指令构建模块

从 decision.py 拆分而来，包含：
- 行为指引文本构建（任务/模式/时段等约束）

关键词映射与覆盖检测已迁移到 portrait_keyword_map 模块统一管理。
"""

from typing import Any, Dict

from core.utils.logger import get_logger
from core.services.active_care.decision.portrait_keyword_map import (
    detect_user_already_covered as _detect_user_already_covered,
)

logger = get_logger("ACTIVE_CARE_DECISION")


def _build_specific_instruction(
    base_instruction: str,
    task_probe: Dict[str, Any],
    focus_stage: str,
    quiet_mode_active: bool,
    reduced_mode_active: bool,
    reduced_mode_reason: str,
    active_care_mode: str,
    elapsed_seconds: int,
    now_hour: int,
    context: Dict[str, Any],
) -> str:
    """构建行为指引文本，整合任务/模式/时段等约束"""
    from core.services.active_care.shared.prompt_helpers import build_quiet_mode_instruction

    instruction = base_instruction
    should_probe = elapsed_seconds > 1200

    # 检测用户最近是否明确表示已起床/已吃饭等，避免矛盾追问
    user_already_covered = _detect_user_already_covered(context)

    # 画像补齐指令（「此轮只追问一个画像项」）已于 2026-10-28 移除。
    if task_probe and should_probe:
        task_title = str(task_probe.get("task_title") or "").strip()
        if task_title:
            instruction += f"\n优先询问每日任务进展，重点任务：{task_title}。"

    if not should_probe:
        instruction += "\n注意：用户刚刚和你互动过。请自然延续之前的对话氛围，**严禁**像查户口一样询问作息或任务！只聊轻松的话题。"

    # 用户已明确表示起床/吃饭等，硬约束禁止矛盾追问
    if "wakeup" in user_already_covered:
        instruction += (
            "\n【硬约束】用户已在最近对话中明确表示已起床/醒了。"
            "绝对不要说任何暗示用户还在睡觉、还没醒、或需要起床的话。"
            "不要问'醒了没/起床了没/还在睡吧'。"
        )
    if "meal" in user_already_covered:
        instruction += (
            "\n【硬约束】用户已在最近对话中提到吃饭相关内容。"
            "不要问'吃了没/吃饭了吗'。"
        )

    if 0 <= now_hour < 6:
        instruction += '\n当前是凌晨时段。禁止催问"起床/早餐/午饭"类画像问题，优先简短陪伴或不打扰。'

    late_night_info = (context.get("sleep_session") or {}).get("inferred_late_night_activity") or {}
    has_late_night = bool(late_night_info.get("has_late_night_activity", False))
    hours_since_late_night = int(late_night_info.get("hours_since_late_night", -1))
    if has_late_night and 6 <= now_hour < 12 and hours_since_late_night >= 0 and hours_since_late_night < 6:
        instruction += '\n【重要】用户凌晨有活动记录，可能晚睡或通宵。当前虽为早上，但用户可能刚睡不久。严禁发送"醒了没/起床了没/早饭吃了没"类消息，仅允许低打扰陪伴如"想你了/早安（不带起床暗示）"。'

    instruction += build_quiet_mode_instruction(
        quiet_mode_active, reduced_mode_active, reduced_mode_reason,
    )

    if active_care_mode == "study_teaching":
        instruction += (
            "\n当前用户处于学习主模式。主动内容优先学习支持，避免闲聊扩散。"
            "\n你的角色是严厉但关心他的学伴/导师——关注效率、知识点掌握、时间管理。"
            "\n禁止催办任务或追问生活画像，专注学习场景。"
        )
        # 注入 TutorEngine 实时数据作为决策指引
        try:
            from core.services.study.tutor_engine import get_tutor_engine as _get_te
            _te_briefing = _get_te().generate_daily_briefing()
            _te_streak = _te_briefing.get("streak_info") or {}
            _te_reviews = _te_briefing.get("review_reminders") or []
            _te_yday = _te_briefing.get("yesterday_review") or {}
            _te_plan = _te_briefing.get("today_plan") or {}
            _te_plan_items = _te_plan.get("items") or []

            _study_hints = []
            _cs = _te_streak.get("current_streak", 0)
            if _cs >= 3:
                _study_hints.append(f"streak已达{_cs}天，鼓励保持")
            elif _cs >= 1:
                _study_hints.append(f"streak {_cs}天，提醒别断")

            if _te_reviews:
                _rv = _te_reviews[0]
                _study_hints.append(
                    f"最紧急复习：{_rv.get('subject', '')}·{_rv.get('topic', '')}"
                    f"（掌握度{_rv.get('confidence', 5):.0f}）"
                )

            if _te_plan_items:
                _pi = _te_plan_items[0]
                _study_hints.append(
                    f"今日建议：{_pi.get('title', '')}（{_pi.get('duration_minutes', 0)}分钟）"
                )

            if _study_hints:
                instruction += (
                    "\n【教学引擎实时数据】" + "；".join(_study_hints)
                    + "\n用这些数据自然引导话题，不要生硬复述。"
                )
        except Exception:
            pass

    # 用户进程活动状态指引
    user_activity = context.get("user_activity") or {}
    if user_activity:
        activity_category = str(user_activity.get("category") or "unknown")
        activity_app = str(user_activity.get("display_name") or "")
        activity_busy = bool(user_activity.get("is_busy", False))
        activity_busy_level = float(user_activity.get("busy_level") or 0.0)

        if activity_category == "gaming":
            instruction += (
                f"\n【用户正在游戏中】检测到用户正在使用 {activity_app}。"
                "用户正在打游戏，可能不想被打断。"
                "可以 should_send=true，但内容必须极简短（一句话，像突然想到他），"
                "不期待回复、不追问、不催促。"
            )
        elif activity_category == "studying":
            instruction += (
                f"\n【用户正在学习中】检测到用户正在使用 {activity_app}。"
                "用户正在学习/做题，可以发极简短消息（一句即停），"
                "内容应与学习相关或单纯表达想念，避免长篇闲聊。"
            )
            # 注入当前学习状态感知
            try:
                from core.services.study.tutor_engine import get_tutor_engine as _get_te2
                _te2 = _get_te2()
                _te2_reviews = _te2.get_review_reminders()
                if _te2_reviews:
                    instruction += (
                        f"\n他有{_te2_reviews.__len__()}个知识点待复习，"
                        '可以顺便提起\u201c学完手头的内容后，别忘了复习之前的知识点\u201d。'
                    )
            except Exception:
                pass
        elif activity_category == "working":
            instruction += (
                f"\n【用户正在工作中】检测到用户正在使用 {activity_app}。"
                "用户正在工作/写代码，可以发极简短消息（一句即停），"
                "内容应简短到不打断工作流，像路过时随口说一句。"
            )
        elif activity_category == "communication":
            instruction += (
                f"\n【用户正在通讯中】检测到用户正在使用 {activity_app}。"
                "用户正在聊天/开会，可以发消息但内容要极简短，避免占用注意力。"
            )
        elif activity_category == "entertainment":
            instruction += (
                f"\n【用户正在娱乐中】检测到用户正在使用 {activity_app}。"
                "用户在看视频/听歌，可以适度发送轻松的消息。"
            )
        elif activity_category == "browsing":
            instruction += (
                f"\n【用户正在浏览中】检测到用户正在使用 {activity_app}。"
                "用户在浏览网页，可以正常发送消息。"
            )
        elif activity_category == "idle":
            instruction += (
                "\n【用户处于空闲状态】用户当前没有活跃操作，"
                "适合发送主动关怀消息。"
            )

        if activity_busy and activity_busy_level >= 0.5:
            instruction += (
                f"\n注意：用户忙碌程度为 {activity_busy_level:.0%}，"
                "若发送，内容应极简短（一句话，不期待回复），像突然想到他顺口说一句。"
            )

    return instruction
