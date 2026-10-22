"""跨模块共用的「节流」判定（聊天议程 + 主动关怀）。

【为什么要抽这一层】
`levels.py` 解决了「这条有多急」，但「多久之内不许再催一次」原本还是两套实现：

| 位置 | 机制 | 判据 |
| --- | --- | --- |
| `streaming_pipeline/agenda_state.py` | 当日标记文件 | 当天提过就沉寂（once_per_day）+ 连续纯闲聊攒够轮数（chitchat gate） |
| `active_care/checker/checker_action_flow.py` | `state_data` 里的时间戳 | 同一签名且 `now - last_probe_ts < cooldown_seconds` |

两处的**判定规则**其实是同一件事：给定「上次什么时候放行过」「攒了多少轮」，
判断现在能不能放行。这里把规则收成一处；**持久化仍留在各自家里**
（agenda 用当日 json、active_care 用 state_data），不强行合并存储。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ThrottlePolicy:
    """一条「多久之内不许再催」的策略。

    三个维度可任意组合，都为「不限」时表示随时可放行：
    - ``cooldown_seconds``：距上次放行不足该秒数就不再放行（0 = 不限）；
    - ``once_per_day``：当天放过一次就沉寂；
    - ``chitchat_turns``：需连续纯闲聊攒够该轮数才允许放行（0 = 不需要）。
    """

    cooldown_seconds: int = 0
    once_per_day: bool = False
    chitchat_turns: int = 0

    def is_unlimited(self) -> bool:
        return not (self.cooldown_seconds or self.once_per_day or self.chitchat_turns)


UNLIMITED = ThrottlePolicy()


def may_fire(
    policy: ThrottlePolicy,
    *,
    fired_today: bool = False,
    last_fired_ts: Optional[float] = None,
    now: Optional[float] = None,
    chitchat_streak: int = 0,
) -> bool:
    """现在能不能放行。

    缺参数一律按「不拦」处理（例如没给 last_fired_ts 就视为冷却已过），
    避免调用方少传一个字段就把整条议程永久锁死。
    """
    if policy.once_per_day and fired_today:
        return False
    if policy.chitchat_turns > 0 and chitchat_streak < policy.chitchat_turns:
        return False
    if policy.cooldown_seconds > 0 and last_fired_ts is not None and now is not None:
        if (now - last_fired_ts) < policy.cooldown_seconds:
            return False
    return True


def remaining_cooldown_seconds(
    policy: ThrottlePolicy,
    *,
    last_fired_ts: Optional[float] = None,
    now: Optional[float] = None,
) -> int:
    """还要等多少秒才过冷却；不在冷却期返回 0。"""
    if policy.cooldown_seconds <= 0 or last_fired_ts is None or now is None:
        return 0
    remaining = policy.cooldown_seconds - (now - last_fired_ts)
    return int(remaining) if remaining > 0 else 0


def blocked_reason(
    policy: ThrottlePolicy,
    *,
    fired_today: bool = False,
    last_fired_ts: Optional[float] = None,
    now: Optional[float] = None,
    chitchat_streak: int = 0,
) -> str:
    """被拦时的原因（给日志/排查用）；可放行返回空串。"""
    if policy.once_per_day and fired_today:
        return "once_per_day"
    if policy.chitchat_turns > 0 and chitchat_streak < policy.chitchat_turns:
        return f"chitchat_streak {chitchat_streak}/{policy.chitchat_turns}"
    if policy.cooldown_seconds > 0 and last_fired_ts is not None and now is not None:
        if (now - last_fired_ts) < policy.cooldown_seconds:
            return f"cooldown {remaining_cooldown_seconds(policy, last_fired_ts=last_fired_ts, now=now)}s left"
    return ""
