"""决策 send 之后怎么发：按 style 决定是轻问候开场（话题进议程）还是直接说。

- greeting：生成层只写一句开场白（``agenda_opener``），选中的话题在送达后写进议程，
  由主聊天在他回话后一步步带过去；没有话题时不发（轻问候必须背着一件事）。
- direct：照原 intent 生成，但把选中的话题文本交给生成层，不再在半路丢掉
  （``planned_topic`` 原来拿到的是字面的 ``[PLANNED_TOPIC_TRIGGER]``）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from core.agents.chat_agent_components.persona_system.prompt.active_care_prompts import (
    RECENT_OPENERS_LINE,
)
from core.services.active_care.agenda.store import Agenda, open_agenda
from core.services.active_care.agenda.topics import find_topic, topic_text
from core.services.active_care.decision.action_protocol import STYLE_GREETING, normalize_style

OPENER_TYPE = "agenda_opener"
OPENER_TRIGGER = "[AGENDA_OPENER_TRIGGER]"
#: tasks.py 认的计划话题占位符（不是 [PLANNED_TOPIC_TRIGGER]）
PLANNED_TRIGGER = "[PLANNED_TRIGGER]"
#: 开场白去重提示里最多列几条最近用过的
OPENERS_IN_PROMPT = 6


@dataclass
class SendPlan:
    """一次发送的生成参数。``skip_reason`` 非空表示这次不发。"""

    sys_prompt_type: str
    user_input_mock: str
    specific_instruction: str
    style: str
    topic: Optional[Dict[str, str]] = None
    skip_reason: str = ""

    @property
    def is_opener(self) -> bool:
        return self.sys_prompt_type == OPENER_TYPE


def _pick_topic(decision: Mapping[str, Any], intent: str) -> Optional[Dict[str, str]]:
    """模型选的 topic_id 优先；没选时取菜单里第一个与本次 intent 相同的话题。"""
    menu = decision.get("topic_menu") or []
    chosen = find_topic(menu, decision.get("topic_id"))
    if chosen is not None:
        return chosen
    for item in menu:
        if isinstance(item, Mapping) and item.get("intent") == intent:
            return dict(item)
    return None


def build_send_plan(
    decision: Mapping[str, Any],
    *,
    intent: str,
    specific_instruction: str,
    recent_opener_texts: Optional[List[str]] = None,
) -> SendPlan:
    style = normalize_style(decision.get("style"))
    topic = _pick_topic(decision, intent)
    if style == STYLE_GREETING:
        if topic is None:
            return SendPlan("", "", "", style, None, skip_reason="greeting_without_topic")
        openers = [t for t in (recent_opener_texts or []) if t][:OPENERS_IN_PROMPT]
        dedup = RECENT_OPENERS_LINE.format(openers="、".join(openers)) if openers else ""
        return SendPlan(OPENER_TYPE, OPENER_TRIGGER, dedup, style, topic)

    text = topic_text(topic)
    instruction = str(specific_instruction or "")
    if intent == "planned_topic":
        return SendPlan(intent, text or PLANNED_TRIGGER, instruction, style, topic)
    if text:
        instruction = f"{instruction}\n本次要说的事：{text}".strip()
    return SendPlan(intent, f"[{intent.upper()}_TRIGGER]", instruction, style, topic)


async def open_agenda_for_plan(
    scope: str, plan: SendPlan, *, intent: str, opener_text: str
) -> Optional[Agenda]:
    """开场白送达后写入议程；非开场发送什么都不做。"""
    if not plan.is_opener or not plan.topic:
        return None
    agenda = Agenda(
        topic=topic_text(plan.topic),
        detail=str(plan.topic.get("detail") or ""),
        source_id=str(plan.topic.get("id") or ""),
        intent=intent,
        opener=str(opener_text or "").strip(),
    )
    return await open_agenda(scope, agenda)


__all__ = [
    "OPENER_TRIGGER",
    "OPENER_TYPE",
    "SendPlan",
    "build_send_plan",
    "open_agenda_for_plan",
]
