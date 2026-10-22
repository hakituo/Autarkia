#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OpenRouter Decisions API 客户端子包。

决策模型（Luna Decisions / Microsoft-Decision-1）走独立端点，与
``core/llm/openai_compat`` 的 chat/completions 协议不同，因此单独成包。
"""

from core.llm.decisions.client import (
    DECISIONS_BASE_URL,
    MODEL_LUNA_DECISIONS,
    MODEL_MS_DECISION_1,
    DecisionAnswer,
    DecisionResult,
    DecisionsClient,
    resolve_decisions_client,
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
