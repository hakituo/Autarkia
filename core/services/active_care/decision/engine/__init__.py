#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主动关怀「决策模型引擎」子包。

承载用专用决策模型（Luna Decisions / Microsoft-Decision-1）替换现有
MiniMax 决策调用的过渡期设施：

- ``compact_state``：把决策上下文压成模型需要的紧凑事实清单；
- ``shadow``       ：影子模式，并行跑决策模型但**不改变**线上发送行为。

``maybe_run_decision_shadow`` 是本包对外的唯一编排入口，调用方只需在拿到线上
决策结果后 await 一次即可；开关、阈值、模型列表全部由配置决定
（``active_care_decision_shadow_enabled`` 默认开启，置 false 即完全停用，
停用时本函数直接返回、不产生任何网络请求）。
"""

import asyncio
from typing import Any, Dict, Optional

from core.services.active_care.decision.engine.compact_state import build_compact_state
from core.services.active_care.decision.engine.shadow import (
    QUESTION_RETRY_BUCKET,
    QUESTION_WORTH_CONTACTING,
    ShadowComparison,
    ShadowVerdict,
    build_questions,
    run_decision_shadow,
    running_under_pytest,
)
from core.utils.config_accessor import get_active_care_config
from core.utils.logger import get_module_logger

logger = get_module_logger(
    "ACTIVE_CARE_DECISION_SHADOW", "active_care_decision_shadow.log"
)

# 影子请求的整体超时：决策槽位在后台调度器里跑，多等 1~2 秒无妨，
# 但绝不允许因为影子请求卡住整条决策链路。
_SHADOW_TIMEOUT_SECONDS = 20.0


def _resolve_models() -> Optional[list]:
    """读取影子模型列表配置；为空或非法时返回 None（调用方走默认值）。"""
    raw = get_active_care_config("active_care_decision_shadow_models", default=None)
    if not raw:
        return None
    if isinstance(raw, str):
        return [item.strip() for item in raw.split(",") if item.strip()]
    if isinstance(raw, (list, tuple)):
        return [str(item).strip() for item in raw if str(item).strip()]
    return None


async def maybe_run_decision_shadow(
    *,
    llm_ctx: Dict[str, Any],
    chosen_action: str,
    result: Dict[str, Any],
    persona_name: str = "",
    extra_facts: Optional[Dict[str, str]] = None,
) -> Optional[ShadowComparison]:
    """按配置决定是否跑一轮影子判定。

    Args:
        llm_ctx: 线上决策实际使用的上下文。
        chosen_action: 上游动作选择器已选定的动作。
        result: 线上决策返回的字典（读 action / reason_code 作为对照基准）。
        persona_name: 角色名。
        extra_facts: 补充给 state 的事实（如到期提醒）。

    Returns:
        对比结果；未启用、无 key 或异常时返回 None —— 本函数永不抛异常。
    """
    if running_under_pytest():
        return None

    enabled = bool(
        get_active_care_config("active_care_decision_shadow_enabled", default=False)
    )
    if not enabled:
        return None

    try:
        threshold = float(
            get_active_care_config("active_care_decision_send_threshold", default=0.5)
            or 0.5
        )
    except (TypeError, ValueError):
        threshold = 0.5

    try:
        return await asyncio.wait_for(
            run_decision_shadow(
                llm_ctx=llm_ctx,
                chosen_action=chosen_action,
                real_action=str(result.get("action") or ""),
                real_reason=str(result.get("reason_code") or ""),
                persona_name=persona_name,
                models=_resolve_models(),
                threshold=threshold,
                extra_facts=extra_facts,
            ),
            timeout=_SHADOW_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("Active Care 决策影子模式超时（%.0fs），已放弃本轮", _SHADOW_TIMEOUT_SECONDS)
        return None
    except Exception as exc:  # 影子模式绝不影响主流程
        logger.warning("Active Care 决策影子模式异常: %s", exc)
        return None


__all__ = [
    "QUESTION_RETRY_BUCKET",
    "QUESTION_WORTH_CONTACTING",
    "ShadowComparison",
    "ShadowVerdict",
    "build_compact_state",
    "build_questions",
    "maybe_run_decision_shadow",
    "run_decision_shadow",
]
