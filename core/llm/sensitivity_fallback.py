#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上游内容审核拒绝（422 new_sensitive）的降级通道。

MiniMax 对涉政 / 露骨输入直接返回 ``422 input new_sensitive (1026)``，
它同时出现在 ``NON_RETRYABLE_STATUS`` 与 ``is_sensitive_input_rejection`` 里：
换同一模型重试永远不会成功。线上蒸馏这类后台任务不该因此丢一批记忆，
所以统一规则是——命中该错误就换 DeepSeek 型号重跑一次。

降级型号按 ``model_routing.memory_models.distillation_fallback`` 读取，
未配置时退回 ``cloud:deepseek:qqbot1:deepseek-v4-flash``。
"""

from __future__ import annotations

from typing import Any, Dict

from core.utils.logger import get_module_logger

logger = get_module_logger(__name__, "nightly_processor.log")

#: 默认降级型号：deepseek-v4-flash 是思考模型，预算需放宽（见 nightlies 调用点）
DEFAULT_FALLBACK_MODEL = "cloud:deepseek:qqbot1:deepseek-v4-flash"

#: 思考模型 reasoning 也占输出预算，降级调用至少给到这个量级
FALLBACK_MIN_TOKENS = 4096


def is_sensitive_rejection(status: Any, body: str) -> bool:
    """是否为上游内容审核拒绝；这类错误对同一模型不可重试。"""
    try:
        return int(status) == 422 and "new_sensitive" in str(body or "").lower()
    except (TypeError, ValueError):
        return False


def get_sensitivity_fallback_model() -> str:
    """读取降级型号；配置缺失或读取异常时用默认值。"""
    try:
        from config.model_config import load_model_config

        memory_models = load_model_config().get("memory_models", {}) or {}
        model = str(memory_models.get("distillation_fallback") or "").strip()
        return model or DEFAULT_FALLBACK_MODEL
    except Exception as exc:  # noqa: BLE001 - 配置读不到不应打断蒸馏
        logger.warning("读取蒸馏降级型号失败，使用默认值: %s", exc)
        return DEFAULT_FALLBACK_MODEL


def classify_stream_chunk_error(
    chunk: Dict[str, Any],
    current_model: str,
    fallback_model: str = "",
) -> str:
    """判定流式错误 chunk 该怎么处理。

    ``fallback_model`` 为空时读全局配置；按角色分 key 的调用方应显式传入该角色的
    DeepSeek 路由，避免降级到别的角色账户。

    Returns:
        ``"skipped"`` 普通错误（继续收正文）、``"switch"`` 换降级型号重跑、
        ``"give_up"`` 不再重试。
    """
    if not chunk.get("error"):
        return "skipped"
    details = chunk.get("details") or {}
    body = str(details.get("body") or "")
    if chunk.get("non_retryable"):
        if is_sensitive_rejection(details.get("status"), body):
            fallback = str(fallback_model or get_sensitivity_fallback_model())
            if current_model != fallback:
                logger.warning("上游判定敏感输入 (422)，改用降级型号重跑")
                return "switch"
            logger.warning("降级型号仍判定敏感输入 (422)，本批放弃")
            return "give_up"
        logger.warning("LLM 不可重试错误，跳过重试: %s", body or chunk.get("error"))
        return "give_up"
    return "skipped"


def _fallback_kwargs(llm_kwargs: Dict[str, Any], fallback_model: str = "") -> Dict[str, Any]:
    """把调用参数换成降级型号，并把思考模型的预算放宽。"""
    kwargs = dict(llm_kwargs)
    kwargs["model_hint"] = str(fallback_model or get_sensitivity_fallback_model())
    try:
        budget = int(kwargs.get("max_tokens") or 0)
    except (TypeError, ValueError):
        budget = 0
    kwargs["max_tokens"] = max(budget, FALLBACK_MIN_TOKENS)
    return kwargs


async def _collect(
    scheduler: Any,
    prompt: Any,
    llm_kwargs: Dict[str, Any],
    fallback_model: str = "",
) -> tuple:
    """收一次流式正文，返回 (正文, 处理指令)。"""
    text = ""
    action = "skipped"
    model = str(llm_kwargs.get("model_hint") or "")
    async for chunk in scheduler.submit_llm_task(prompt, **llm_kwargs):
        if isinstance(chunk, str):
            text += chunk
        elif isinstance(chunk, dict):
            verdict = classify_stream_chunk_error(chunk, model, fallback_model)
            if verdict == "give_up":
                return text, verdict
            if verdict == "switch":
                return text, verdict
            if chunk.get("content"):
                text += chunk["content"]
    return text, action


async def stream_text_with_sensitivity_fallback(
    scheduler: Any,
    prompt: Any,
    llm_kwargs: Dict[str, Any],
    *,
    fallback_model_hint: str = "",
) -> str:
    """收集流式正文；命中 422 内容审核时换 DeepSeek 型号重跑一次。

    ``fallback_model_hint`` 非空时优先用它（按角色分 key 的链路传该角色的 DeepSeek 路由）。
    """
    fallback_model = str(fallback_model_hint or get_sensitivity_fallback_model())
    text, action = await _collect(scheduler, prompt, llm_kwargs, fallback_model)
    if action == "switch":
        retried, _ = await _collect(
            scheduler, prompt, _fallback_kwargs(llm_kwargs, fallback_model), fallback_model
        )
        return retried
    return text


__all__ = [
    "DEFAULT_FALLBACK_MODEL",
    "FALLBACK_MIN_TOKENS",
    "classify_stream_chunk_error",
    "get_sensitivity_fallback_model",
    "is_sensitive_rejection",
    "stream_text_with_sensitivity_fallback",
]
