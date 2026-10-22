#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OpenRouter Decisions API 客户端。

与 OpenAI 兼容的 ``chat/completions`` 不同，决策模型走独立端点：

    POST https://openrouter.ai/api/alpha/decisions
    {"model": ..., "state": ..., "questions": {...}}

返回的是**命名问题的校准概率**而不是文本：``noul`` 给 yes 概率、``choice`` 给完整分布
与最可能项、``score`` 给有序评分。``output_tokens`` 恒为 0（输出免费），因此成本只由
输入长度决定 —— state 越紧凑越便宜。

目前实测可用且共用同一协议的两个模型：

- ``openai/gpt-6-luna-decisions``   —— 时间粒度更细，适合打扰判断
- ``microsoft-decision-1``          —— 单价更低、中文分词更省，适合选项打分

注意 ``microsoft-decision-1`` 不在 ``/api/v1/models`` 公开目录里，但它确实挂在该端点上；
用 chat/completions 调它会返回 400 并提示改用本端点。
"""

from dataclasses import dataclass, field
import json
import os
import time
from typing import Any, Dict, Optional

import aiohttp

from core.llm.openai_compat.session_mixin import create_session
from core.utils.logger import get_logger

logger = get_logger("decisions_client")

DECISIONS_BASE_URL = "https://openrouter.ai/api/alpha/decisions"

# 实测两个模型共用的请求/响应协议，调用方按需二选一
MODEL_LUNA_DECISIONS = "openai/gpt-6-luna-decisions"
MODEL_MS_DECISION_1 = "microsoft-decision-1"

# noul 是 API 对「二分类 yes 概率」的字段名，保持线上原样，不做重命名
_ANSWER_TYPE_NOUL = "noul"
_ANSWER_TYPE_CHOICE = "choice"
_ANSWER_TYPE_SCORE = "score"


@dataclass(frozen=True)
class DecisionAnswer:
    """单个命名问题的回答。"""

    name: str
    type: str
    noul: Optional[float] = None
    choice: Optional[str] = None
    probabilities: Dict[str, float] = field(default_factory=dict)
    score: Optional[float] = None
    confidence: Optional[float] = None


@dataclass(frozen=True)
class DecisionResult:
    """一次决策请求的完整结果（含用量，便于成本归因）。"""

    model: str
    answers: Dict[str, DecisionAnswer]
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0

    def noul(self, name: str) -> Optional[float]:
        """取某个二分类问题的 yes 概率；问题不存在或类型不符时返回 None。"""
        answer = self.answers.get(name)
        return answer.noul if answer else None

    def choice(self, name: str) -> Optional[str]:
        """取某个选择问题的 argmax；问题不存在或类型不符时返回 None。"""
        answer = self.answers.get(name)
        return answer.choice if answer else None


def _parse_answer(name: str, raw: Any) -> Optional[DecisionAnswer]:
    """把单个 answer 字典解析成 DecisionAnswer，结构不符时返回 None。"""
    if not isinstance(raw, dict):
        return None
    answer_type = str(raw.get("type") or "").strip()
    probabilities: Dict[str, float] = {}
    raw_probs = raw.get("probabilities")
    if isinstance(raw_probs, dict):
        for key, value in raw_probs.items():
            try:
                probabilities[str(key)] = float(value)
            except (TypeError, ValueError):
                continue
    confidence = raw.get("confidence")
    try:
        confidence = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        confidence = None
    noul = raw.get("noul")
    try:
        noul = float(noul) if noul is not None else None
    except (TypeError, ValueError):
        noul = None
    score = raw.get("score")
    try:
        score = float(score) if score is not None else None
    except (TypeError, ValueError):
        score = None
    return DecisionAnswer(
        name=name,
        type=answer_type,
        noul=noul,
        choice=str(raw.get("choice")) if raw.get("choice") is not None else None,
        probabilities=probabilities,
        score=score,
        confidence=confidence,
    )


class DecisionsClient:
    """Decisions API 客户端（异步）。

    用 ``async with`` 管理 session 生命周期；也可显式调用 ``close()``。
    任何上游/解析失败都返回 ``None`` 并记 warning —— 决策槽位调用方必须能在
    拿不到结果时回落到原有路径，所以这里不抛异常。
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: str = DECISIONS_BASE_URL,
        proxy: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.proxy = proxy
        self.timeout = timeout
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self) -> "DecisionsClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = create_session(self.api_key, self.timeout, self.proxy)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    async def decide(
        self,
        *,
        model: str,
        state: str,
        questions: Dict[str, Dict[str, Any]],
    ) -> Optional[DecisionResult]:
        """发起一次决策请求。

        Args:
            model: 模型 id，见 ``MODEL_LUNA_DECISIONS`` / ``MODEL_MS_DECISION_1``。
            state: 被判定的内容（纯文本，或 JSON 字符串）。紧凑、事实性的 state
                既提高准确率也降低成本。
            questions: ``{问题名: {type, instructions, criteria}}``；单请求最多 200 个。

        Returns:
            解析后的结果；网络/上游/结构异常时返回 None。
        """
        if not self.api_key:
            logger.warning("Decisions API 未配置 api_key，跳过调用")
            return None
        if not state or not questions:
            logger.warning("Decisions API 调用缺少 state 或 questions，跳过")
            return None

        payload = {"model": model, "state": state, "questions": questions}
        started = time.monotonic()
        try:
            session = await self._get_session()
            async with session.post(self.base_url, json=payload) as response:
                body = await response.text()
                if response.status != 200:
                    logger.warning(
                        "Decisions API 返回 %s: %s", response.status, body[:300]
                    )
                    return None
        except aiohttp.ClientError as exc:
            logger.warning("Decisions API 请求失败: %s", exc)
            return None
        except Exception as exc:  # 兜底：决策槽位不允许把异常抛给主流程
            logger.warning("Decisions API 异常: %s", exc)
            return None

        latency_ms = (time.monotonic() - started) * 1000
        return self._parse_response(body, model, latency_ms)

    @staticmethod
    def _parse_response(body: str, model: str, latency_ms: float) -> Optional[DecisionResult]:
        """解析响应体；结构不符时返回 None。"""
        try:
            data = json.loads(body)
        except (TypeError, ValueError):
            logger.warning("Decisions API 响应不是合法 JSON: %s", str(body)[:200])
            return None
        if not isinstance(data, dict):
            return None

        raw_answers = data.get("answers")
        if not isinstance(raw_answers, dict):
            logger.warning("Decisions API 响应缺少 answers 字段: %s", str(data)[:200])
            return None

        answers: Dict[str, DecisionAnswer] = {}
        for name, raw in raw_answers.items():
            parsed = _parse_answer(str(name), raw)
            if parsed is not None:
                answers[str(name)] = parsed

        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return DecisionResult(
            model=str(data.get("model") or model),
            answers=answers,
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            cost_usd=float(usage.get("cost") or 0.0),
            latency_ms=latency_ms,
        )

    def get_status(self) -> Dict[str, Any]:
        """返回客户端状态，供健康检查/日志使用。"""
        return {
            "provider": "openrouter-decisions",
            "base_url": self.base_url,
            "api_key_configured": bool(self.api_key),
            "proxy_configured": bool(self.proxy),
            "session_active": self._session is not None and not self._session.closed,
        }


def resolve_decisions_client(
    *, timeout: float = 30.0, api_key: Optional[str] = None, proxy: Optional[str] = None
) -> DecisionsClient:
    """按项目既有约定解析 OpenRouter key 与代理，构造客户端。

    解析口径与 ``core/llm/factory.py`` 的 openrouter 分支保持一致：
    代理优先 ``OPENROUTER_PROXY_URL``，否则复用 ``TELEGRAM_PROXY_URL``。
    """
    resolved_key = api_key or os.getenv("OPENROUTER_API_KEY")
    resolved_proxy = proxy
    if resolved_proxy is None:
        resolved_proxy = os.getenv("OPENROUTER_PROXY_URL") or os.getenv("TELEGRAM_PROXY_URL") or None
    return DecisionsClient(
        api_key=resolved_key, proxy=resolved_proxy, timeout=timeout
    )


__all__ = [
    "DECISIONS_BASE_URL",
    "MODEL_LUNA_DECISIONS",
    "MODEL_MS_DECISION_1",
    "DecisionAnswer",
    "DecisionResult",
    "DecisionsClient",
    "resolve_decisions_client",
]
