"""Peer Chat 组队（谁和谁聊）。

从「固定 aveline↔ling 两人」改成「从已登记的互聊组合里选一个」：
- 组合来自 ``personas.PEER_CHAT_GROUPS``（2 人或 3 人，数据驱动）；
- 参与资格沿用自主角色判定（peer chat 是自主行为，不是日程角色行为）；
- 组队与信息可见性解耦：Ye可以参与互聊，但不会因此获得Aveline的档案/记忆可见性
  （详见 ``personas.PEER_CHAT_RELATIONS`` 注释）。

本模块只负责「选谁聊」，不做 LLM 决策、不生成剧本。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from core.services.character_daily.activity_model import (
    CHAT_ELIGIBLE_ACTIVITIES,
    DO_NOT_DISTURB_ACTIVITIES,
    ActivityType,
    DailyPlan,
)

# 最闲的活动：作为发起者的优先候选
_IDLE_ACTIVITIES = {ActivityType.IDLE, ActivityType.PHONE_SCROLLING}


@dataclass(frozen=True)
class PeerChatGroup:
    """一次互聊的参与者与发起者。"""

    participants: Tuple[str, ...]
    initiator: str

    @property
    def is_multi(self) -> bool:
        return len(self.participants) > 2


def _group_weight(group: Tuple[str, ...], trio_probability: float) -> float:
    """组合基础权重：两人组 1.0，三人组按配置概率缩小。"""
    return 1.0 if len(group) <= 2 else max(0.0, float(trio_probability))


def _passes_group_mode(group: Tuple[str, ...], group_mode: str) -> bool:
    mode = str(group_mode or "mixed").strip().lower()
    if mode == "pair":
        return len(group) <= 2
    if mode == "trio":
        return len(group) >= 3
    return True


def _group_is_awake(group: Tuple[str, ...], plans: Mapping[str, DailyPlan]) -> bool:
    for role_id in group:
        plan = plans.get(role_id)
        if plan is None:
            return False
        if plan.current_activity == ActivityType.SLEEPING:
            return False
    return True


def _group_is_available(group: Tuple[str, ...], plans: Mapping[str, DailyPlan]) -> bool:
    """至少一人可聊天，且不能所有人都在不可打扰状态。"""
    activities = [
        plans[role_id].current_activity
        for role_id in group
        if role_id in plans
    ]
    if not activities:
        return False
    if all(a in DO_NOT_DISTURB_ACTIVITIES for a in activities):
        return False
    return any(a in CHAT_ELIGIBLE_ACTIVITIES for a in activities)


def _pick_initiator(
    group: Tuple[str, ...],
    plans: Mapping[str, DailyPlan],
) -> str:
    """在组内选发起者：优先空闲、其次最久没聊的人。"""
    candidates: List[str] = []
    for role_id in group:
        plan = plans.get(role_id)
        if plan is not None and plan.current_activity in CHAT_ELIGIBLE_ACTIVITIES:
            candidates.append(role_id)
    if not candidates:
        candidates = list(group)

    idle = [
        rid for rid in candidates
        if plans.get(rid) is not None
        and plans[rid].current_activity in _IDLE_ACTIVITIES
    ]
    pool = idle or candidates

    def _last_ts(role_id: str) -> float:
        plan = plans.get(role_id)
        return float(plan.last_peer_chat_ts or 0.0) if plan else 0.0

    # 最久没聊的人更可能先开口；相同则按组合内定义顺序，保证可复现。
    return min(pool, key=lambda rid: (_last_ts(rid), group.index(rid)))


def select_peer_chat_group(
    now: datetime,
    plans: Mapping[str, DailyPlan],
    *,
    autonomous_roles: Iterable[str],
    config,
    rng: Optional[random.Random] = None,
) -> Optional[PeerChatGroup]:
    """选一个可聊的组合；没有可用组合时返回 None。

    Args:
        now: 当前时间（保留给按时段加权，当前未使用，调用方保证在允许时段内）。
        plans: role_id -> DailyPlan
        autonomous_roles: 拥有自主行为的角色集合
        config: CharacterDailyConfig（读 ``config.peer_chat``）
        rng: 可注入随机源，便于测试
    """
    from core.services.dual_role.personas import get_peer_chat_groups

    pc = getattr(config, "peer_chat", None)
    group_mode = str(getattr(pc, "group_mode", "mixed") or "mixed")
    trio_probability = float(getattr(pc, "trio_probability", 0.25) or 0.0)
    picker = rng or random

    allowed = {str(r).strip().lower() for r in autonomous_roles}
    candidates: List[Tuple[Tuple[str, ...], float]] = []

    for raw_group in get_peer_chat_groups():
        group = tuple(str(m).strip().lower() for m in raw_group)
        if len(group) < 2:
            continue
        if not _passes_group_mode(group, group_mode):
            continue
        if any(member not in allowed for member in group):
            continue
        if any(member not in plans for member in group):
            continue
        if not _group_is_awake(group, plans):
            continue
        if not _group_is_available(group, plans):
            continue

        weight = _group_weight(group, trio_probability)
        if weight <= 0:
            continue
        # 越久没聊的组合权重越高（最多放大 2 倍），避免总是同一组在聊。
        last_ts = max(
            float(plans[member].last_peer_chat_ts or 0.0) for member in group
        )
        elapsed = max(0.0, now.timestamp() - last_ts) if last_ts > 0 else 86400.0
        weight *= 1.0 + min(1.0, elapsed / 14400.0)
        candidates.append((group, weight))

    if not candidates:
        return None

    total = sum(w for _, w in candidates)
    threshold = picker.random() * total
    chosen: Tuple[str, ...] = candidates[-1][0]
    acc = 0.0
    for group, weight in candidates:
        acc += weight
        if threshold <= acc:
            chosen = group
            break

    return PeerChatGroup(
        participants=chosen,
        initiator=_pick_initiator(chosen, plans),
    )


def build_group_situation(
    participants: Iterable[str],
    plans: Mapping[str, DailyPlan],
    initiator: str,
) -> str:
    """为剧本生成构建多人情境（谁能被观察到、谁在忙）。

    只描述代码能确认的事实：各自当前粗粒度活动。具体地点/同行/目的由
    ActivityInstance 在 runner 里补齐，不在这里猜。
    """
    from core.services.character_daily.activity_model import (
        ACTIVITY_VERBS,
        ACTIVITY_VERBS_ONGOING,
    )
    from core.services.dual_role.personas import get_persona

    members = [str(m).strip().lower() for m in participants]
    lines: List[str] = []

    for role_id in members:
        plan = plans.get(role_id)
        if plan is None:
            continue
        persona = get_persona(role_id)
        name = persona.cn_name if persona else role_id
        activity = plan.current_activity
        if role_id == initiator:
            verb = ACTIVITY_VERBS.get(activity, "休息")
            lines.append(f"{name}刚{verb}")
        else:
            if activity in CHAT_ELIGIBLE_ACTIVITIES:
                verb = ACTIVITY_VERBS.get(activity, "休息")
                lines.append(f"{name}也在{verb}")
            else:
                ongoing = ACTIVITY_VERBS_ONGOING.get(activity, "做事")
                lines.append(f"{name}正在{ongoing}，不一定马上回")

    return "；".join(lines) + "。" if lines else ""
