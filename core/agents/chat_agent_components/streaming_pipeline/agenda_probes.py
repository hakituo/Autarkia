"""议程候选项的探测函数 P1~P5（从 agenda_injections 拆出）。

每个 probe 都是 ``async (ctx) -> (text, commit)``：返回空 text 表示本轮没有这条议程；
返回 commit 表示「被选中后才消费」的动作（None 表示只读、无需消费）。
约定见 agenda_injections 的阶梯与 pick_agenda_injection。

【为什么拆】
agenda_injections 在 2026-10-02 加闲聊门控后涨到 420 行，越过 300 行门禁。
这里只搬走「怎么取这条议程的内容」，不改语义。

【优先级依据】
按「错过了会不会出事」排：P1 带时间点且 300s 过期；P2 一天只出一次；
P3 是昨日日记生成的「明天我要做 X」清单（催早饭的真凶之一）；
P4 是今日计划清单；P5 是三餐软提示（只兜底，不与计划抢位）。
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional, Tuple

from core.utils.logger import get_logger

logger = get_logger("ChatAgent")

Commit = Optional[Callable[[], Awaitable[None]]]
Probe = Callable[[dict], Awaitable[Tuple[str, Commit]]]


async def _probe_plan_reminder(ctx: dict) -> Tuple[str, Commit]:
    """P1：Active Care 计划提醒。peek 不消费，选中后才 clear。"""
    try:
        from core.services.active_care.shared.reminder_injection import (
            get_reminder_injection_store,
        )

        store = get_reminder_injection_store()
        pending = await store.peek()
        if not pending:
            return "", None
        parts = ["【计划提醒】"]
        merged_count = int(pending.get("merged_count") or 0)
        if merged_count > 1:
            parts.append(f"共有 {merged_count} 条提醒待自然带入本轮回复")
        if pending.get("task_title"):
            parts.append(f"任务：{pending['task_title']}")
        parts.append(f"提醒：{pending['reminder_text']}")
        if pending.get("recent_chat_summary"):
            parts.append(f"最近对话背景：{pending['recent_chat_summary']}")
        parts.append(
            "请在回复中自然地提醒用户这个计划，不要直接说'系统提醒你'，而是融入对话中。"
        )
        return "\n".join(parts), store.clear
    except Exception as e:
        logger.warning(f"Failed to peek Active Care reminder: {e}")
        return "", None


async def _probe_daily_study_task(ctx: dict) -> Tuple[str, Commit]:
    """P2：每日学习任务更新。peek 不落盘，选中后才 commit。"""
    prep = ctx.get("prep")
    if prep is not None and not (prep.is_cloud and not prep.is_sensitive_mode):
        return "", None
    agent = ctx.get("agent")
    user_id = str(ctx.get("user_id") or "")
    if agent is None:
        return "", None
    try:
        text = await agent._peek_daily_routine(user_id)
    except Exception as e:
        logger.warning(f"Failed to peek daily routine: {e}")
        return "", None
    if not text:
        return "", None
    ctx.get("events", []).append({
        "type": "thought_chain",
        "data": {
            "stage": "context_enrichment",
            "status": "success",
            "description": "Checking daily schedule...",
        },
        "done": False,
    })
    return f"【每日总结】\n{text}", lambda: agent._commit_daily_routine(user_id)


async def _probe_tomorrow_tone(ctx: dict) -> Tuple[str, Commit]:
    """P3：今日总基调（昨日日记生成）。只读，无消费。"""
    try:
        from core.services.journal.service import get_journal_service

        tone = await get_journal_service().get_tomorrow_tone()
        if not tone:
            return "", None
        return (
            f"【今日总基调（来自昨日日记总结）】\n{tone}\n"
            "这部分只用于语气、话题方向和互动节奏，不是日期或节日的事实来源。"
            "其中若出现‘今天/明天’或具体节日，不得直接复述，必须以权威日历事实锚点为准。"
        ), None
    except Exception as e:
        logger.warning(f"Failed to inject tomorrow_tone: {e}")
        return "", None


async def _probe_today_plan(ctx: dict) -> Tuple[str, Commit]:
    """P4：今日计划清单。只读，无消费（靠 pick_agenda_injection 的节流）。

    **文案在 2026-10-01 被改写过**：原版写着「你需要主动追踪主人的执行进度」与
    「如果主人长时间偏离计划（如该学习时在玩），可以自然地提醒一下进度」——
    这两句被模型直接执行成了「十八点半那个数学还挂着，现在八点二十了」这种催促。
    现在改成「背景资料 + 明确禁止催」，只保留勾选工具的使用说明。
    """
    try:
        from core.services.journal.service import get_journal_service

        svc = get_journal_service()
        today_plan = await svc.get_plan()
        if not (today_plan and today_plan.items):
            return "", None
        plan_text = svc.format_plan_for_injection(today_plan)
        if not plan_text:
            return "", None
        return (
            f"【今日计划（背景资料）】\n{plan_text}\n"
            "- 这只是他今天的安排，让你知道他在忙什么，**不是需要你监督的任务清单**。\n"
            "- 他主动说做完了某项时，可以调用 mark_plan_item_status 把对应项勾掉"
            "（传 item_id 和 status，date 留空默认今日）。\n"
            "- **不要主动追问进度，不要指出哪一项超时或还没做，不要催他去按计划做事。**\n"
            "  他聊什么就聊什么；他自己提起计划再谈。"
        ), None
    except Exception as e:
        logger.warning(f"Failed to inject today_plan: {e}")
        return "", None


async def _probe_meal_care(ctx: dict) -> Tuple[str, Commit]:
    """P5：三餐无记录时的软提示（只兜底，不与计划抢位）。

    原先这句是 user_bio 常驻块里的「- 用户三餐: 无记录（需要关注）」——
    「需要关注」被模型读成指令，实测 2026-09-28 早上 30 分钟内催了 6 次早饭。
    现在常驻块只留事实，提示降级成优先级最低的候选。
    """
    try:
        from core.services.daily.manager import get_daily_manager

        record = await asyncio.to_thread(get_daily_manager().get_record)
        if (record or {}).get("meals"):
            return "", None
    except Exception as e:
        logger.warning(f"Failed to peek meal care: {e}")
        return "", None
    return (
        "【饮食提醒】\n"
        "他今天还没有任何用餐记录。可以顺口问一句吃了没，问过就翻篇，不要连着追问。"
    ), None
