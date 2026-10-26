"""Peer Chat 多人执行编排。

与旧路径的区别：
- 参与者由 ``select_peer_chat_group`` 选出（2 或 3 人），不再固定 aveline↔ling；
- 情境来自角色日常系统的**已落盘事实**（ActivityInstance：地点/同行/目的 + 课程），
  不再只有「刚学习完」这种粗粒度动词；
- 分发走 ``peer_chat_channels``：本地通道永远可用，QQ 通道有在线连接才执行。

本模块只做编排；LLM prompt 仍在 peer_script_* / qq_peer_context 里。
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.utils.logger import get_module_logger
from core.utils.time_utils import now_str

logger = get_module_logger("PEER_CHAT", "peer_chat.log")


def _activity_facts_text(role_id: str, *, max_lines: int = 6) -> str:
    """读取该角色已落盘的活动事实（只读，不生成实例）。

    复用主对话的 ``build_character_daily_context``，保证互聊看到的生活与角色
    自己聊天时说的是同一份事实。
    """
    try:
        from core.agents.chat_agent_components.persona_system.prompt.components.character_daily_context import (
            build_character_daily_context,
        )
        from core.services.dual_role.personas import get_persona

        persona = get_persona(role_id)
        if persona is None:
            return ""
        text = build_character_daily_context(persona.config_filename) or ""
        if not text:
            return ""
        # 去掉标题行，保留事实键值行；时间线行也保留（recent/upcoming）。
        lines = [ln for ln in text.splitlines() if ln.strip()]
        body = [ln for ln in lines if not ln.startswith("【")]
        return "\n".join(body[:max_lines])
    except Exception as exc:
        logger.debug("PeerChat 读取活动事实失败 role=%s: %s", role_id, exc)
        return ""


def build_multi_situation(
    participants: List[str],
    plans: Dict[str, Any],
    initiator: str,
) -> str:
    """多人情境：粗粒度活动 + 各自已落盘的具体生活事实。"""
    from core.services.active_care.peer_chat.peer_chat_group import build_group_situation
    from core.services.dual_role.personas import get_role_names

    base = build_group_situation(participants, plans, initiator)
    parts: List[str] = [base] if base else []

    for role_id in participants:
        if role_id == initiator:
            continue
        facts = _activity_facts_text(role_id)
        if not facts:
            continue
        name = get_role_names(role_id)["cn_name"]
        # 只注入可观察的公开事实，不注入 bio 私有状态（那些走知识防火墙分桶）。
        parts.append(f"{name}那边的情况：{facts}")

    return "\n".join(p for p in parts if p).strip()


async def run_peer_chat(
    engine,
    group,
    now: Optional[datetime] = None,
) -> bool:
    """执行一次多人互聊；成功返回 True。"""
    now = now or datetime.now()
    participants = [str(p).strip().lower() for p in group.participants]
    initiator = str(group.initiator or "").strip().lower()
    if len(participants) < 2 or initiator not in participants:
        logger.warning(
            "PeerChat: 非法组队 participants=%s initiator=%s", participants, initiator
        )
        return False

    scheduler = getattr(engine, "_peer_chat_scheduler", None)
    if scheduler is None:
        logger.warning("PeerChat: PeerChatScheduler 未注入，无法执行")
        return False

    plans = {
        role_id: engine._state.get_plan(role_id)
        for role_id in participants
    }
    if any(plan is None for plan in plans.values()):
        logger.info("PeerChat: 参与者缺少当日计划，跳过 participants=%s", participants)
        return False

    situation = build_multi_situation(participants, plans, initiator)

    # ---- 1. LLM 决策（发起者视角）----
    from core.services.dual_role.personas import get_role_names

    peer_names = "、".join(
        get_role_names(role_id)["cn_name"]
        for role_id in participants
        if role_id != initiator
    )
    bio_state: Dict[str, Any] = {}
    try:
        from core.services.life_simulation import get_life_simulation_service

        life_sim = get_life_simulation_service()
        if life_sim:
            bio_state = life_sim.get_bio_state(initiator)
    except Exception:
        pass

    global_last_ts = float(getattr(engine._state, "global_last_peer_chat_ts", 0.0) or 0.0)
    now_ts = time.time()
    decision_context = {
        "now": now_str("%Y-%m-%d %H:%M:%S"),
        "now_ts": now_ts,
        "bio_state": bio_state,
        "elapsed_seconds": int(now_ts - global_last_ts) if global_last_ts > 0 else 9999,
        "recent_peer_chat_topics": list(
            getattr(engine._state, "recent_peer_chat_topics", []) or []
        ),
        "character_daily_situation": situation,
        "participants": participants,
    }

    try:
        decision = await scheduler._decision.decide(
            decision_context,
            initiator,
            peer_names,
        )
    except Exception as exc:
        logger.error("PeerChat 决策异常: %s", exc, exc_info=True)
        return False

    if not decision.get("should_send", False):
        logger.info(
            "PeerChat 决策不发送 initiator=%s peers=%s thought=%s",
            initiator, peer_names, str(decision.get("thought", ""))[:80],
        )
        return False

    topic = str(
        decision.get("topic", "") or decision.get("planned_topic", "")
    ).strip()
    situation_from_llm = str(decision.get("situation", "")).strip() or situation
    opening_idea = str(decision.get("opening_idea", "")).strip()

    # ---- 2. 生成剧本 + 分发（含本地通道）----
    executor = getattr(scheduler, "_executor", None)
    if executor is None:
        logger.warning("PeerChat: executor 不可用")
        return False

    try:
        sent = await executor.generate_peer_script(
            role_id=initiator,
            participants=participants,
            topic=topic,
            situation=situation_from_llm,
            opening_idea=opening_idea,
            avoid=decision.get("avoid") or None,
        )
    except Exception as exc:
        logger.error("PeerChat 生成/分发异常: %s", exc, exc_info=True)
        return False

    if not sent:
        return False

    # ---- 3. 更新状态（全局 + 每个参与者）----
    try:
        _record_multi_chat(engine, participants, initiator, now_ts, topic)
    except Exception as exc:
        logger.warning("PeerChat 状态更新失败: %s", exc)

    return True


def _record_multi_chat(
    engine,
    participants: List[str],
    initiator: str,
    ts: float,
    topic: str,
) -> None:
    """所有参与者的 last_peer_chat_ts 同步，计数只记发起者。"""
    plan_initiator = engine._state.get_plan(initiator)
    if plan_initiator is not None:
        plan_initiator.today_peer_chat_count += 1
        plan_initiator.last_peer_chat_ts = ts

    for role_id in participants:
        plan = engine._state.get_plan(role_id)
        if plan is not None:
            plan.last_peer_chat_ts = ts

    engine._state.global_last_peer_chat_ts = ts

    if topic:
        recent = list(getattr(engine._state, "recent_peer_chat_topics", []) or [])
        recent.append(topic)
        engine._state.recent_peer_chat_topics = recent[-5:]

    store = getattr(engine, "_store", None)
    if store is not None:
        store.save(engine._state)

    # proactive_state 的全局日计数也要同步，避免独立 scheduler 与 engine 各算一套。
    try:
        storage = getattr(getattr(engine, "_peer_chat_scheduler", None), "_storage", None)
        if storage is not None:
            import asyncio

            async def _sync():
                from core.utils.time_utils import get_current_time

                storage.set_runtime_scope(initiator)
                state = await storage.get_proactive_state()
                date_key = get_current_time().strftime("%Y-%m-%d")
                state[f"peer_chat_count_{date_key}"] = int(
                    state.get(f"peer_chat_count_{date_key}", 0)
                ) + 1
                state[f"peer_chat_global_count_{date_key}"] = int(
                    state.get(f"peer_chat_global_count_{date_key}", 0)
                ) + 1
                state["last_peer_chat_ts"] = ts
                await storage.save_proactive_state(state)

            asyncio.create_task(_sync())
    except Exception:
        pass
