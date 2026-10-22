#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主动关怀决策的「影子模式」：并行跑决策模型，只记录不切换。

目的：在不动线上行为的前提下，把 Luna Decisions / Microsoft-Decision-1 的判定
与现有 MiniMax 决策的实际结果并排记下来，攒够样本后再决定是否切换。

因此本模块**只读**：不修改决策结果、不改变发送行为、任何失败都只记日志。
落盘文件 ``logs/<年>/<月>/<日>/active_care_decision_shadow.log``，按行 grep 即可
统计「一致率 / 影子想发但线上没发 / 线上发了但影子想延后」。
"""

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.llm.decisions import (
    MODEL_LUNA_DECISIONS,
    MODEL_MS_DECISION_1,
    DecisionsClient,
    resolve_decisions_client,
)
from core.services.active_care.decision.engine.compact_state import build_compact_state
from core.utils.logger import get_module_logger

logger = get_module_logger(
    "ACTIVE_CARE_DECISION_SHADOW", "active_care_decision_shadow.log"
)

# 影子判定用的两个问题：与线上 action_protocol 的 send/defer 协议一一对应
QUESTION_WORTH_CONTACTING = "worth_contacting"
QUESTION_RETRY_BUCKET = "retry_bucket"

_RETRY_BUCKETS = {
    "60": "1 分钟后",
    "900": "15 分钟后",
    "1800": "30 分钟后",
    "3600": "1 小时后",
}


def running_under_pytest() -> bool:
    """是否运行在 pytest 进程里。

    pytest 在执行用例时会设置 ``PYTEST_CURRENT_TEST``。影子链路需要这个判据做两件事：
    1. 不发起真实网络请求（会产生费用，且测试环境未必能连上代理）；
    2. **不写生产影子日志** —— ``run_decision_shadow`` 是无条件记日志的，
       单测跑一次就会往 ``logs/<日期>/active_care_decision_shadow.log``
       灌几条 fixture 数据（``chosen_action="a"`` 那种），
       把用户用来统计一致率的日志污染掉。
    """
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


@dataclass
class ShadowVerdict:
    """单个影子模型的判定结果。"""

    model: str
    would_send: bool = False
    noul: Optional[float] = None
    retry_seconds: Optional[int] = None
    confidence: Optional[float] = None
    input_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    error: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "would_send": self.would_send,
            "noul": self.noul,
            "retry_seconds": self.retry_seconds,
            "confidence": self.confidence,
            "input_tokens": self.input_tokens,
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


@dataclass
class ShadowComparison:
    """一次决策轮次的影子对比结果。"""

    chosen_action: str
    real_action: str
    real_reason: str
    state_chars: int
    state_preview: str
    verdicts: List[ShadowVerdict] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "chosen_action": self.chosen_action,
            "real_action": self.real_action,
            "real_reason": self.real_reason,
            "state_chars": self.state_chars,
            "state_preview": self.state_preview,
            "verdicts": [v.as_dict() for v in self.verdicts],
        }


def build_questions() -> Dict[str, Dict[str, Any]]:
    """构造影子判定用的问题集（与线上 send/defer 协议对齐）。"""
    return {
        QUESTION_WORTH_CONTACTING: {
            "type": "noul",
            "instructions": (
                "现在是否值得主动联系用户？只有存在明确、具体、有依据的联系价值时才为真；"
                "仅仅想聊天、想问候、想找话题都不算。"
            ),
            "criteria": {
                "true": "存在明确、具体、有依据的联系价值",
                "false": "没有明确价值，应当继续等待",
            },
        },
        QUESTION_RETRY_BUCKET: {
            "type": "choice",
            "instructions": "如果不联系，多久之后应该重新判断？",
            "criteria": dict(_RETRY_BUCKETS),
        },
    }


async def _call_one(
    client: DecisionsClient,
    model: str,
    state: str,
    threshold: float,
) -> ShadowVerdict:
    """调用单个模型并把结果归一化成 ShadowVerdict（永不抛异常）。"""
    verdict = ShadowVerdict(model=model)
    try:
        result = await client.decide(
            model=model, state=state, questions=build_questions()
        )
    except Exception as exc:  # 影子模式不允许影响主流程
        verdict.error = f"{type(exc).__name__}: {exc}"
        return verdict
    if result is None:
        verdict.error = "no_result"
        return verdict

    verdict.input_tokens = result.input_tokens
    verdict.cost_usd = result.cost_usd
    verdict.latency_ms = result.latency_ms

    noul = result.noul(QUESTION_WORTH_CONTACTING)
    verdict.noul = noul
    if noul is not None:
        verdict.would_send = noul >= threshold

    answer = result.answers.get(QUESTION_RETRY_BUCKET)
    if answer is not None:
        verdict.confidence = answer.confidence
        if answer.choice is not None:
            try:
                verdict.retry_seconds = int(float(answer.choice))
            except (TypeError, ValueError):
                verdict.retry_seconds = None
    return verdict


async def run_decision_shadow(
    *,
    llm_ctx: Dict[str, Any],
    chosen_action: str,
    real_action: str,
    real_reason: str = "",
    persona_name: str = "",
    models: Optional[List[str]] = None,
    threshold: float = 0.5,
    extra_facts: Optional[Dict[str, str]] = None,
) -> Optional[ShadowComparison]:
    """跑一轮影子判定并记日志。

    Args:
        llm_ctx: 线上决策实际使用的上下文。
        chosen_action: 上游动作选择器已选定的动作。
        real_action: 线上决策的实际出口（send_active_care / defer_active_care）。
        real_reason: 线上决策的 reason_code，用于人工核对分歧原因。
        persona_name: 角色名。
        models: 影子模型列表，默认 Luna + Microsoft-Decision-1。
        threshold: noul 判定阈值，>= 阈值视为「值得发」。
        extra_facts: 补充给 state 的事实（如到期提醒）。

    Returns:
        对比结果；未启用或全部失败时返回 None。
    """
    model_list = list(models) if models else [MODEL_LUNA_DECISIONS, MODEL_MS_DECISION_1]
    state = build_compact_state(
        llm_ctx, persona_name=persona_name, extra_facts=extra_facts
    )
    if not state.strip():
        return None

    client = resolve_decisions_client()
    if not client.api_key:
        logger.warning("影子模式跳过：未配置 OPENROUTER_API_KEY")
        return None

    try:
        verdicts = await asyncio.gather(
            *[_call_one(client, model, state, threshold) for model in model_list]
        )
    finally:
        await client.close()

    comparison = ShadowComparison(
        chosen_action=str(chosen_action or ""),
        real_action=str(real_action or ""),
        real_reason=str(real_reason or ""),
        state_chars=len(state),
        state_preview=state.replace("\n", " | ")[:300],
        verdicts=list(verdicts),
    )
    _log_comparison(comparison, threshold)
    return comparison


def _log_comparison(comparison: ShadowComparison, threshold: float) -> None:
    """把对比结果写进影子日志（单行 JSON，便于统计）。

    测试进程下直接跳过：单测会用 fixture 调 ``run_decision_shadow``，
    写进生产日志会把真实样本淹掉（见 ``running_under_pytest``）。
    """
    if running_under_pytest():
        return

    import json

    payload = comparison.as_dict()
    payload["threshold"] = threshold
    payload["agree"] = [
        v.model
        for v in comparison.verdicts
        if not v.error
        and v.would_send == (comparison.real_action == "send_active_care")
    ]
    logger.info(
        "Active Care 决策影子对比 real=%s state=%d字 结果=%s",
        comparison.real_action,
        comparison.state_chars,
        json.dumps(payload, ensure_ascii=False),
    )


__all__ = [
    "QUESTION_WORTH_CONTACTING",
    "QUESTION_RETRY_BUCKET",
    "ShadowComparison",
    "ShadowVerdict",
    "build_questions",
    "run_decision_shadow",
]
