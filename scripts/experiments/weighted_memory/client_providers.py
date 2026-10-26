"""离线实验的 provider 定义、密钥加载与推理正文清洗。"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

DEFAULT_PROVIDER = "minimax-plan"

_THINK_RE = re.compile(r"<think(?:ing)?>(.*?)</think(?:ing)?>", re.DOTALL | re.IGNORECASE)
_UNCLOSED_THINK_RE = re.compile(r"<think(?:ing)?>(.*)$", re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    env_key: str
    base_url: str
    default_model: str
    json_mode: bool
    reasoning_split: bool = False


PROVIDERS: Dict[str, ProviderSpec] = {
    "minimax-plan": ProviderSpec(
        name="minimax-plan",
        env_key="MINIMAX_PLAN_API_KEY",
        base_url="https://api.minimaxi.com/v1/chat/completions",
        default_model="MiniMax-M3.1-Flash",
        json_mode=False,
        reasoning_split=True,
    ),
    "deepseek": ProviderSpec(
        name="deepseek",
        env_key="DEEPSEEK_API_KEY",
        base_url="https://api.deepseek.com/chat/completions",
        default_model="deepseek-chat",
        json_mode=True,
    ),
}


def load_api_key(env_key: str) -> str:
    key = str(os.getenv(env_key) or "").strip()
    if key:
        return key
    try:
        from dotenv import load_dotenv

        root = Path(__file__).resolve().parents[3]
        load_dotenv(root / ".env")
    except Exception:  # noqa: BLE001
        pass
    return str(os.getenv(env_key) or "").strip()


def split_reasoning(content: str, reasoning_details: Any = None) -> tuple[str, str]:
    """把 ``<think>`` 块与 ``reasoning_details`` 从正文剥离，返回 (正文, 推理)。"""
    text = str(content or "")
    parts: list[str] = []
    for block in _THINK_RE.findall(text):
        if block.strip():
            parts.append(block.strip())
    text = _THINK_RE.sub("", text)
    unclosed = _UNCLOSED_THINK_RE.search(text)
    if unclosed:
        parts.append(unclosed.group(1).strip())
        text = text[: unclosed.start()]
    if isinstance(reasoning_details, list):
        for item in reasoning_details:
            if isinstance(item, dict):
                piece = str(item.get("text") or "").strip()
                if piece:
                    parts.append(piece)
    return text.strip(), "\n".join(parts)


__all__ = [
    "DEFAULT_PROVIDER",
    "PROVIDERS",
    "ProviderSpec",
    "load_api_key",
    "split_reasoning",
]
