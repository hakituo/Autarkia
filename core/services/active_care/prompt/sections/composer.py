"""主动关怀 Prompt 的静态段与可选动态段组装。"""

from __future__ import annotations

from typing import List

from core.agents.chat_agent_components.persona_system.prompt import active_care_prompts as prompts
from core.services.active_care.prompt.sections.models import PromptSection


def _compat_module():
    from core.services.active_care.prompt import prompt_builder

    return prompt_builder


def resolve_care_role_id(profile_filename: str, persona_name: str) -> str:
    try:
        from core.services.dual_role.personas import resolve_role_id

        return resolve_role_id(profile_filename) or resolve_role_id(persona_name) or ""
    except Exception:  # noqa: BLE001
        return ""


# 角色活动投影里描述「此刻」的键；时间线键（recent/upcoming）不参与睡眠判断。
_CURRENT_ACTIVITY_KEYS = ("daily_activity", "scheduled_activity", "confirmed_activity")


def _current_activity_projection(role_activity_text: str) -> str:
    """只取描述此刻状态的行，避免把时间线里的睡觉/午休当成当前活动。"""
    current: list[str] = []
    for raw_line in role_activity_text.splitlines():
        key, separator, value = raw_line.partition("=")
        if separator and key.strip() in _CURRENT_ACTIVITY_KEYS:
            current.append(value.strip())
    return " ".join(current)


def build_role_activity_anchor(role_activity_text: str) -> str:
    role_activity = str(role_activity_text or "").strip()
    if not role_activity:
        return ""
    # 角色正在睡觉时忽略活动锚点；非 key=value 的历史调用退回全文判断。
    sleep_probe = (_current_activity_projection(role_activity) or role_activity).lower()
    if any(keyword in sleep_probe for keyword in ("sleeping", "napping", "睡觉", "午休", "睡梦中")):
        return ""
    return prompts.ROLE_ACTIVITY_ANCHOR_TEMPLATE.format(role_activity_text=role_activity)


def build_static_sections(
    persona_prompt: str,
    profile_filename: str,
    style_enforcement: str,
) -> List[PromptSection]:
    compat = _compat_module()
    fixed_prefix = compat.get_fixed_prefix()
    sensitive_prefix = compat.select_sensitive_prefix(profile_filename)
    persona_prompt = compat.strip_fixed_prefix(persona_prompt, fixed_prefix)
    persona_prompt = compat.strip_fixed_prefix(persona_prompt, sensitive_prefix)
    sections = []
    if fixed_prefix:
        sections.append(PromptSection("fixed_prefix", fixed_prefix + "\n\n"))
    if sensitive_prefix:
        sections.append(PromptSection("sensitive_prefix", sensitive_prefix + "\n\n"))
    sections.extend(
        [
            PromptSection("core_constraints", prompts.CORE_CONSTRAINTS),
            PromptSection("persona_prompt", f"{persona_prompt}\n\n"),
            PromptSection("style_enforcement", style_enforcement),
            PromptSection("voice_guide", prompts.VOICE_GUIDE),
        ]
    )
    return sections


def append_optional_sections(
    sections: List[PromptSection],
    *,
    tomorrow_tone: str,
    user_off_study: bool,
    proactive_state: dict | None,
    profile_filename: str,
) -> None:
    tone = str(tomorrow_tone or "").strip()
    if tone:
        sections.append(
            PromptSection(
                "tomorrow_tone",
                prompts.TOMORROW_TONE_TEMPLATE.format(tomorrow_tone=tone),
            )
        )
    compat = _compat_module()
    today_plan = "" if user_off_study else compat._build_today_plan_text()
    if today_plan:
        sections.append(
            PromptSection("today_plan", prompts.TODAY_PLAN_TEMPLATE.format(plan_text=today_plan))
        )
    if proactive_state:
        deferred = compat.build_deferred_reminders_text(proactive_state)
        if deferred:
            sections.append(
                PromptSection(
                    "deferred_reminders",
                    prompts.DEFERRED_REMINDERS_TEMPLATE.format(deferred_text=deferred),
                )
            )
    other_reminders = compat._build_other_persona_reminders_text(profile_filename)
    if other_reminders:
        sections.append(PromptSection("other_persona_reminders", other_reminders))
