"""睡眠子模块。

- `windows`：时间窗口的纯函数（无状态、无 IO，可单独复用）
- `transitions`：状态推进
- `metrics`：睡眠指标与噩梦
- `triggers`：入睡 / 起床的上游事件
- `recovery`：被叫醒后的恢复决策
- `events`：外部事件写入与活动覆盖

对外门面仍是 `..sleep_manager.SleepManager`。
"""

from .windows import (
    apply_locked_sleep_window,
    build_sleep_window,
    minutes_to_hhmm,
    parse_hhmm_to_minutes,
    planned_minutes,
    resolve_effective_sleep_start_ts,
    resolve_next_wake_dt,
    resolve_sleep_window,
)

__all__ = [
    "apply_locked_sleep_window",
    "build_sleep_window",
    "minutes_to_hhmm",
    "parse_hhmm_to_minutes",
    "planned_minutes",
    "resolve_effective_sleep_start_ts",
    "resolve_next_wake_dt",
    "resolve_sleep_window",
]
