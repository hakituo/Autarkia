"""议程类注入的优先级竞争（从 dynamic_context.build_stream_messages 拆出）。

本模块只做「这一轮该不该放一条议程、放哪一条」：阶梯 + 竞争 + 提交编排。
「每条议程怎么取内容」在 ``agenda_probes``，「已经放过什么 / 闲聊了几轮」在
``agenda_state``（2026-10-02 拆出，原文件越过 300 行门禁）。

【为什么拆】
原来这里是 5 段 `if` 顺序 append：谁都不让谁，于是同一轮回复里可能同时出现
「催吃饭」「催背单词」「盯计划进度」。实测 2026-10-01 那轮，用户只说
「我买了个华为的显示器1669」，Aveline 的回复里同时塞了催饭和「176 个词今天压着呢」。
拆出来后：语气类（【情感影响指令】）保持常驻，议程类每轮**最多注入 1 条**。

【不丢东西】
P1（计划提醒）与 P2（每日学习任务）原本都是「取走即消费」——
P1 走 `get_and_clear()`，P2 先落盘再返回（落盘后当天再也取不到）。
改成 peek + 选中后 commit：没被选中的下一轮还能取到，只是不再和别的事挤在一句里。

【每天最多一次（2026-10-01 补）】
只靠「按优先级取第一条」还不够：P1/P2 天然是取走即消费，但 P3/P4/P5 是只读的
状态型条目 —— 只要它有内容就会**每一轮都胜出**。实测当天 P1/P2/P3 全空，
P4 连续 7 轮胜出，角色每轮都在提「十八点半那个数学还挂着」。
所以状态型条目加了 once_per_day：当天第一次提过就沉寂，之后轮到别的条目或什么都不注入。

【聊天就是聊天（2026-10-02 补）】
once_per_day 只解决了「同一件事重复催」，没解决「每天必催一次」：主人随口聊两句，
照样会被塞一条催办。现在加了 chitchat 门控 —— 带 ``chitchat_gated`` 的条目
只有连续 ``CHITCHAT_TURNS_BEFORE_AGENDA`` 轮「什么都没做、纯闲聊」之后才允许出场，
催过一次计数归零。没攒够就什么都不注入，回复里只剩正常聊天内容。

计数状态与 once_per_day 标记共用同一个当日文件，格式与兼容规则见 ``agenda_state``。
"""

from __future__ import annotations

import asyncio
from typing import Any, List, NamedTuple, Optional, Tuple

from core.utils.logger import get_logger

from core.services.priority import PriorityLevel, ThrottlePolicy, may_fire

from .agenda_probes import (
    Commit,
    Probe,
    _probe_active_care_agenda,
    _probe_daily_study_task,
    _probe_meal_care,
    _probe_plan_reminder,
    _probe_today_plan,
    _probe_tomorrow_tone,
)
from .agenda_state import (
    _bump_chitchat_streak,
    _mark_injected,
    _read_state,
    _reset_chitchat_streak,
)

logger = get_logger("ChatAgent")

__all__ = [
    "AgendaItem",
    "AGENDA_PRIORITY",
    "CHITCHAT_TURNS_BEFORE_AGENDA",
    "Commit",
    "Probe",
    "pick_agenda_injection",
]

# 连续「纯闲聊」多少轮之后，才允许放一条催办类议程出来。
# 想调松/调紧只改这一个数：10 ≈ 聊了小半天还没干正事。
CHITCHAT_TURNS_BEFORE_AGENDA = 10


class AgendaItem(NamedTuple):
    """阶梯上的一条议程。

    用具名字段而不是位置元组：之前是 ``(name, probe, once_per_day)`` 三元素，
    再加一个门控位就变成「第四个布尔是什么」的猜谜，且改错顺序不会报错。

    ``level`` 取自跨模块共用的优先级词汇（``core.services.priority``），
    让「这条有多急」和主动关怀侧用同一套档位；阶梯顺序仍由元组位置决定
    （它编码的是「错过了会不会出事」，比档位更细），但必须与 level 单调不增。
    """

    name: str
    probe: Probe
    once_per_day: bool         # 状态型：当天提过就沉寂，不再参与竞争
    chitchat_gated: bool       # 只有连续纯闲聊攒够轮数才允许出场
    level: PriorityLevel = PriorityLevel.ROUTINE


# 顺序即优先级，从高到低。后两个布尔位决定这条议程什么时候才允许出场；
# level 取自共用优先级词汇，必须与顺序单调不增（tests/unit/test_agenda_injections.py 钉住）。
#
# 事件型（once_per_day=False）里 P1 保持不门控：它是 Active Care 排定的提醒，
# 带 300s TTL，压到门开就过期了。P2 带的是当天学习进度，属于「没事找事」，
# 跟状态型一起门控。
_LADDER: Tuple[AgendaItem, ...] = (
    AgendaItem(
        "plan_reminder", _probe_plan_reminder,
        once_per_day=False, chitchat_gated=False, level=PriorityLevel.OVERDUE,
    ),
    # 开场议程：轻问候之后一步步带的那件事。不门控、不限每天一次——
    # 它本来就只在开场之后存在，结束由模型调用 close_agenda 决定。
    AgendaItem(
        "active_care_agenda", _probe_active_care_agenda,
        once_per_day=False, chitchat_gated=False, level=PriorityLevel.OVERDUE,
    ),
    AgendaItem(
        "daily_study_task", _probe_daily_study_task,
        once_per_day=False, chitchat_gated=True, level=PriorityLevel.PENDING,
    ),
    AgendaItem(
        "tomorrow_tone", _probe_tomorrow_tone,
        once_per_day=True, chitchat_gated=True, level=PriorityLevel.ROUTINE,
    ),
    AgendaItem(
        "today_plan", _probe_today_plan,
        once_per_day=True, chitchat_gated=True, level=PriorityLevel.ROUTINE,
    ),
    AgendaItem(
        "meal_care", _probe_meal_care,
        once_per_day=True, chitchat_gated=True, level=PriorityLevel.ROUTINE,
    ),
)

AGENDA_PRIORITY: Tuple[str, ...] = tuple(item.name for item in _LADDER)


async def pick_agenda_injection(
    *,
    agent: Any,
    user_id: str,
    prep: Any = None,
    events: Optional[List[dict]] = None,
) -> Tuple[str, str, Commit]:
    """按优先级逐个探测，返回第一条命中的 (名称, 文本, 提交回调)。

    命中的那条由调用方决定何时提交（消费）；**没命中的一律不消费**，留到下一轮。
    标记为 once_per_day 的条目，当天已经放过就跳过（不再参与竞争）。
    chitchat_gated 的条目只有在「连续纯闲聊 ≥ CHITCHAT_TURNS_BEFORE_AGENDA 轮」
    时才允许出场；本轮什么都没注入，就给闲聊计数 +1。

    返回 ``("", "", None)`` 表示本轮没有任何议程要注入（也就是一轮正常聊天）。
    """
    from core.utils.time_utils import now_str

    today = now_str("%Y-%m-%d")
    uid = str(user_id)
    ctx = {
        "agent": agent,
        "user_id": user_id,
        "prep": prep,
        "events": events if events is not None else [],
    }

    # 当日状态只读一次（原先 once_per_day 条目各读一遍文件），
    # 节流判定统一交给共用的 may_fire：档位管「多急」，节流管「能不能放」。
    try:
        state = await asyncio.to_thread(_read_state, uid, today)
    except Exception as e:  # noqa: BLE001
        logger.debug("读议程状态失败，按空状态处理：%s", e)
        state = {"injected": [], "chitchat_streak": 0}
    injected = {str(n) for n in (state.get("injected") or [])}
    streak = state.get("chitchat_streak") or 0

    for item in _LADDER:
        policy = ThrottlePolicy(
            once_per_day=item.once_per_day,
            chitchat_turns=CHITCHAT_TURNS_BEFORE_AGENDA if item.chitchat_gated else 0,
        )
        if not may_fire(
            policy, fired_today=item.name in injected, chitchat_streak=streak
        ):
            continue
        try:
            text, commit = await item.probe(ctx)
        except Exception as e:
            logger.warning("Agenda probe %s failed: %s", item.name, e)
            continue
        if text:
            logger.info(
                "Agenda '%s' 出场（level=%s, once_per_day=%s, chitchat_gated=%s, streak=%d）",
                item.name, item.level.name, item.once_per_day, item.chitchat_gated, streak,
            )
            return item.name, text, _compose_commit(
                commit, uid, item.name, today, item.once_per_day
            )

    # 走到这里说明本轮是纯聊天 —— 计数 +1，攒够了下一轮才可能放议程。
    try:
        new_streak = await asyncio.to_thread(_bump_chitchat_streak, uid, today)
        logger.info(
            "本轮无议程注入（纯闲聊 streak=%d/%d）",
            new_streak, CHITCHAT_TURNS_BEFORE_AGENDA,
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("累加闲聊计数失败：%s", e)
    return "", "", None


def _compose_commit(
    commit: Commit, user_id: str, name: str, today: str, once_per_day: bool
) -> Commit:
    """把「条目自己的提交」「写 once_per_day 标记」「重置闲聊计数」合成一个回调。

    不管是不是 once_per_day 都要包一层：真的催过一次就得把计数归零，
    否则门会一直开着，退回「每轮都催」的老毛病。
    """

    async def _commit() -> None:
        if commit is not None:
            await commit()
        if once_per_day:
            await asyncio.to_thread(_mark_injected, user_id, name, today)
        await asyncio.to_thread(_reset_chitchat_streak, user_id, today)

    return _commit
