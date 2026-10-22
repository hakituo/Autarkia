"""跨模块共用的优先级词汇（聊天议程 + 主动关怀）。

【为什么要抽这一层】
2026-10-02 排查「角色反复催」时发现，「什么该先催、多急、多久能再催一次」被写在了
**三处互不共享的实现**里：

| 位置 | 形态 |
| --- | --- |
| `streaming_pipeline/agenda_injections.py` | 声明式有序阶梯（5 条，靠元组顺序表达优先级） |
| `active_care/decision/priority_analyzer.py` | 规则级联（overdue > due_soon > pending）+ 硬编码冷却秒数 |
| `active_care/decision/daily_push_priority.py` | 打分候选表（92/86/80/95/88…）交给 LLM 排序 |

三者表达方式不同（有序表 / 级联 / 打分），**不该强行合成一个实现**；
但「档位」这件事是共用的：`overdue` 比 `due_soon` 急、`due_soon` 比挂着没做的急、
日常软提示最不急 —— 这套词汇与「同一档多久能再催一次」应当只有一份。

本模块只放这两样：档位枚举 + 档位/理由到冷却时长的映射。
**不放**打分（各调用点分值不同，抽出来必然失真）与节流持久化（见 agenda_state）。
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any, Dict, Optional


class PriorityLevel(IntEnum):
    """优先级档位。数值越大越急，跨聊天议程与主动关怀共用一套。"""

    ROUTINE = 10    # 日常软提示：三餐、画像补全、streak 守护
    PENDING = 20    # 挂着没做的：未完成计划项、到期复习
    DUE_SOON = 30   # 快到点了
    OVERDUE = 40    # 已经过期
    CRITICAL = 50   # 安全类，压过一切（睡眠/健康预警）


# 理由字符串 → 档位。三处实现共用的 reason 词汇都登记在这里；
# 新增 reason 必须在这里登记，否则 level_of_reason 会落到 ROUTINE 并记 debug。
_REASON_LEVELS: Dict[str, PriorityLevel] = {
    # 任务类
    "overdue": PriorityLevel.OVERDUE,
    "due_soon": PriorityLevel.DUE_SOON,
    "timed_pending": PriorityLevel.PENDING,
    "untimed_pending": PriorityLevel.PENDING,
    "task_follow_up": PriorityLevel.PENDING,
    # 学习类
    "review_due": PriorityLevel.PENDING,
    "streak_at_risk": PriorityLevel.ROUTINE,
    # 画像 / 日常类
    "portrait": PriorityLevel.ROUTINE,
    "portrait_missing": PriorityLevel.ROUTINE,
    "daily_routine": PriorityLevel.ROUTINE,
    "meal_care": PriorityLevel.ROUTINE,
    "peer_chat_share": PriorityLevel.ROUTINE,
    "fallback": PriorityLevel.ROUTINE,
    # 计划项：默认 PENDING（「挂着要做的」）。计划项自带 high/normal/low，
    # 调用点应改用 level_of_plan_priority() 覆盖成更准的档位。
    "plan_item": PriorityLevel.PENDING,
    # 突发状态（tired / sick / low_battery 等）按安全类处理
    "urgent": PriorityLevel.CRITICAL,
    # 聊天议程阶梯的五条（streaming_pipeline/agenda_injections）。
    # 档位与阶梯顺序一致：计划提醒最急（带 300s TTL），每日学习任务次之，
    # 其余三条同为日常软提示，它们之间靠阶梯顺序做 tie-break。
    "plan_reminder": PriorityLevel.OVERDUE,
    "daily_study_task": PriorityLevel.PENDING,
    "tomorrow_tone": PriorityLevel.ROUTINE,
    "today_plan": PriorityLevel.ROUTINE,
    # 安全类
    "sleep_deprived": PriorityLevel.CRITICAL,
    "high_heart_rate": PriorityLevel.CRITICAL,
    "low_spo2": PriorityLevel.CRITICAL,
    "high_stress": PriorityLevel.CRITICAL,
}

# 档位 → 同一档「多久之内不要再催一次」。
# 原值来自 priority_analyzer.get_priority_probe_cooldown_seconds，逐档搬过来：
# overdue 20min / due_soon 15min / pending 45min / routine 90min。
_COOLDOWN_SECONDS: Dict[PriorityLevel, int] = {
    PriorityLevel.CRITICAL: 5 * 60,
    PriorityLevel.OVERDUE: 20 * 60,
    PriorityLevel.DUE_SOON: 15 * 60,
    PriorityLevel.PENDING: 45 * 60,
    PriorityLevel.ROUTINE: 90 * 60,
}

DEFAULT_COOLDOWN_SECONDS = 3600


def level_of_reason(reason: Optional[str]) -> PriorityLevel:
    """理由字符串 → 档位。没登记的理由按 ROUTINE 处理（不抛，保证链路不炸）。"""
    key = str(reason or "").strip().lower()
    if not key:
        return PriorityLevel.ROUTINE
    if key not in _REASON_LEVELS:
        from core.utils.logger import get_logger

        get_logger("PRIORITY").debug("未登记的理由 %r，按 ROUTINE 处理", key)
        return PriorityLevel.ROUTINE
    return _REASON_LEVELS[key]


def cooldown_seconds_for_reason(reason: Optional[str]) -> int:
    """理由 → 冷却秒数（同一档共用）。"""
    return _COOLDOWN_SECONDS.get(level_of_reason(reason), DEFAULT_COOLDOWN_SECONDS)


def cooldown_seconds_for_level(level: PriorityLevel) -> int:
    """档位 → 冷却秒数。"""
    return _COOLDOWN_SECONDS.get(level, DEFAULT_COOLDOWN_SECONDS)


# 计划项自带的高/中/低优先级 → 档位。
# 计划项的 reason 都是 `plan_item`，光看 reason 只能给一个默认档位；
# 真正决定它多急的是它自己的 priority 字段，所以调用点要用下面这个函数覆盖。
_PLAN_PRIORITY_LEVELS: Dict[str, PriorityLevel] = {
    "high": PriorityLevel.DUE_SOON,
    "normal": PriorityLevel.PENDING,
    "low": PriorityLevel.ROUTINE,
}


def level_of_plan_priority(priority: Optional[str]) -> PriorityLevel:
    """计划项 priority（high/normal/low）→ 档位；不认识的值按 PENDING。"""
    key = str(priority or "").strip().lower()
    return _PLAN_PRIORITY_LEVELS.get(key, PriorityLevel.PENDING)


def cooldown_seconds_for_focus(focus: Dict[str, Any]) -> int:
    """从主动关怀的 priority_focus 结构算冷却秒数。

    口径与 `PriorityAnalyzer.get_priority_probe_cooldown_seconds` 原实现逐条对齐：
    先看 task_probe 的 reason，再看有没有画像补全项，都没有才落到默认值。

    注意这里**只认 `build_priority_focus` 实际会产出的 4 个 reason**
    （overdue / due_soon / timed_pending / untimed_pending）。其它字符串
    （例如 daily_push_priority 里当兜底用的 `task_follow_up`，那个字段不在
    focus.task_probe 上）保持原实现的「落到默认 3600」，不按档位换算，
    避免重构顺手改了行为。
    """
    if not isinstance(focus, dict):
        return DEFAULT_COOLDOWN_SECONDS
    task_probe = focus.get("task_probe") or {}
    reason = str(task_probe.get("reason") or "").strip().lower()
    if reason in {"overdue", "due_soon", "timed_pending", "untimed_pending"}:
        return cooldown_seconds_for_reason(reason)
    if focus.get("portrait_priority"):
        return cooldown_seconds_for_level(PriorityLevel.ROUTINE)
    return DEFAULT_COOLDOWN_SECONDS


def registered_reasons() -> Dict[str, PriorityLevel]:
    """只读快照，给校验脚本与测试用。"""
    return dict(_REASON_LEVELS)
