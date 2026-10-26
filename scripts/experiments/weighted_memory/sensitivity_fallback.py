"""内容审核 422 的降级通道：MiniMax 判敏感时改由 DeepSeek 跑同一条请求。

背景：MiniMax 对涉政 / 露骨输入直接返回 ``422 input new_sensitive (1026)``，
这是确定性拒绝，退避重试永远不会成功。离线实验与线上蒸馏都按同一规则处理：
命中该错误 → 不重试原模型 → 换 DeepSeek 重发 → 成功则原样落缓存。

``deepseek-v4-flash`` 是思考模型，reasoning 会吃掉输出预算，因此预算放大若干倍；
仍拿不到正文时再退一级到 ``deepseek-chat``（非思考，可用原预算）。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx

DEEPSEEK_BASE_URL = "https://api.deepseek.com/chat/completions"
#: 降级模型链：先跑用户指定的 v4.1 flash，再退非思考型号兜底
FALLBACK_MODELS: tuple = ("deepseek-v4-flash", "deepseek-chat")
#: 思考模型的首个型号放大预算，避免正文被 reasoning 挤空
REASONING_BUDGET_MULTIPLIER = 4
REASONING_BUDGET_FLOOR = 1024
DEFAULT_TIMEOUT = 90.0


def is_sensitive_rejection(status: Any, body: str) -> bool:
    """是否为上游内容审核拒绝；这类错误对同一 payload 不可重试。"""
    try:
        return int(status) == 422 and "new_sensitive" in str(body or "").lower()
    except (TypeError, ValueError):
        return False


def fallback_api_key(env_key: str = "DEEPSEEK_API_KEY") -> str:
    """读取降级通道的 API Key（环境变量优先，其次项目 .env）。"""
    key = str(os.getenv(env_key) or "").strip()
    if key:
        return key
    try:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env"))
    except Exception:  # noqa: BLE001 - 缺 key 时上层会退到占位结果
        pass
    return str(os.getenv(env_key) or "").strip()


def _budget_for(model: str, max_tokens: int) -> int:
    if model == "deepseek-chat":
        return max_tokens
    return max(REASONING_BUDGET_FLOOR, max_tokens * REASONING_BUDGET_MULTIPLIER)


def _post(
    model: str,
    system: str,
    user: str,
    *,
    max_tokens: int,
    temperature: float,
    api_key: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[Dict[str, Any]]:
    """单次调用；网络/限流/空正文都返回 None，交由下个型号或上层处理。"""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        response = httpx.post(
            DEEPSEEK_BASE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=timeout,
        )
    except Exception:  # noqa: BLE001
        return None
    if response.status_code != 200:
        return None
    body = response.json()
    choice = (body.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    text = str(message.get("content") or "").strip()
    usage = body.get("usage") or {}
    return {
        "text": text,
        "model": str(body.get("model") or model),
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "attempts": [],
    }


def call_sensitive_fallback(
    system: str,
    user: str,
    *,
    max_tokens: int,
    temperature: float,
    api_key: Optional[str] = None,
    models: tuple = FALLBACK_MODELS,
) -> Optional[Dict[str, Any]]:
    """按降级模型链重发一次请求，返回首个拿到非空正文的结果。"""
    key = api_key if api_key is not None else fallback_api_key()
    if not key:
        return None
    attempts: List[str] = []
    for model in models:
        budget = _budget_for(model, max_tokens)
        result = _post(
            model,
            system,
            user,
            max_tokens=budget,
            temperature=temperature,
            api_key=key,
        )
        if result and result["text"]:
            result["attempts"] = attempts + [f"{model}@{budget}:ok"]
            return result
        attempts.append(f"{model}@{budget}:empty" if result else f"{model}@{budget}:fail")
    return None


__all__ = [
    "DEEPSEEK_BASE_URL",
    "FALLBACK_MODELS",
    "call_sensitive_fallback",
    "fallback_api_key",
    "is_sensitive_rejection",
]
