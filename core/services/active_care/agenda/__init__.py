"""开场议程：轻问候开口，要聊的事放进主聊天 prompt 一步步带过去。

- ``store``：议程持久化（按角色一份，开 / 关 / 轮数 / 最近开场白）；
- ``topics``：从今日推送排序里取可带的话题，供决策模型挑选；
- ``paths``：文件位置与会话 → scope 解析。
"""

from core.services.active_care.agenda.paths import is_agenda_conversation, scope_for_conversation
from core.services.active_care.agenda.store import (
    MAX_AGE_SECONDS,
    Agenda,
    close_agenda,
    get_active_agenda,
    open_agenda,
    recent_openers,
    record_agenda_turn,
)

__all__ = [
    "MAX_AGE_SECONDS",
    "Agenda",
    "close_agenda",
    "get_active_agenda",
    "is_agenda_conversation",
    "open_agenda",
    "recent_openers",
    "record_agenda_turn",
    "scope_for_conversation",
]
