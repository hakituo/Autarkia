"""兼容导出：客户端实现与 provider 定义分在 client_core / client_providers。"""

from __future__ import annotations

from .client_core import BudgetExceeded, LLMResult, OpenAICompatClient
from .client_providers import (
    DEFAULT_PROVIDER,
    PROVIDERS,
    ProviderSpec,
    load_api_key,
    split_reasoning,
)

__all__ = [
    "BudgetExceeded",
    "DEFAULT_PROVIDER",
    "LLMResult",
    "OpenAICompatClient",
    "PROVIDERS",
    "ProviderSpec",
    "load_api_key",
    "split_reasoning",
]
