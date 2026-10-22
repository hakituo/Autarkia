"""跨模块共用的优先级词汇（聊天议程 + 主动关怀）。

两件事：`levels` 定义「这条有多急、多久能再催一次」，`throttle` 定义
「现在能不能放行」。详见两个子模块的 docstring。
"""

from __future__ import annotations

from core.services.priority.levels import (
    DEFAULT_COOLDOWN_SECONDS,
    PriorityLevel,
    cooldown_seconds_for_focus,
    cooldown_seconds_for_level,
    cooldown_seconds_for_reason,
    level_of_plan_priority,
    level_of_reason,
    registered_reasons,
)
from core.services.priority.throttle import (
    UNLIMITED,
    ThrottlePolicy,
    blocked_reason,
    may_fire,
    remaining_cooldown_seconds,
)

__all__ = [
    "DEFAULT_COOLDOWN_SECONDS",
    "PriorityLevel",
    "ThrottlePolicy",
    "UNLIMITED",
    "blocked_reason",
    "cooldown_seconds_for_focus",
    "cooldown_seconds_for_level",
    "cooldown_seconds_for_reason",
    "level_of_plan_priority",
    "level_of_reason",
    "may_fire",
    "registered_reasons",
    "remaining_cooldown_seconds",
]
