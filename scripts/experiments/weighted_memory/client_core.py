"""离线实验：OpenAI 兼容客户端（缓存 / 预算 / 用量统计）。"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from .client_providers import (
    DEFAULT_PROVIDER,
    PROVIDERS,
    load_api_key,
    split_reasoning,
)
from .sensitivity_fallback import call_sensitive_fallback, is_sensitive_rejection


class BudgetExceeded(RuntimeError):
    """调用次数或 token 预算耗尽。"""


@dataclass
class LLMResult:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_seconds: float
    cached: bool = False
    reasoning: str = ""

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class OpenAICompatClient:
    def __init__(
        self,
        *,
        cache_path: Path,
        provider: str = DEFAULT_PROVIDER,
        model: str = "",
        base_url: str = "",
        temperature: float = 0.0,
        max_calls: int = 250,
        max_total_tokens: int = 1_200_000,
        timeout: float = 90.0,
        api_key: Optional[str] = None,
    ) -> None:
        spec = PROVIDERS.get(provider)
        if spec is None:
            raise ValueError(f"未知 provider={provider}，可选：{sorted(PROVIDERS)}")
        self.provider = spec.name
        self.base_url = base_url or spec.base_url
        self.model = model or spec.default_model
        self.json_mode = spec.json_mode
        self.reasoning_split = spec.reasoning_split
        self.temperature = temperature
        self.max_calls = max_calls
        self.max_total_tokens = max_total_tokens
        self.timeout = timeout
        self._api_key = api_key if api_key is not None else load_api_key(spec.env_key)
        self.cache_path = Path(cache_path)
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._load_cache()
        self.calls = 0
        self.cached_calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.cached_prompt_tokens = 0
        self.cached_completion_tokens = 0
        self.failures = 0

    # ---- 缓存 -----------------------------------------------------------
    def _load_cache(self) -> None:
        if not self.cache_path.exists():
            return
        for line in self.cache_path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except Exception:  # noqa: BLE001
                continue
            key = str(item.get("key") or "")
            if key:
                self._cache[key] = item

    def _append_cache(self, item: Dict[str, Any]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    def _cache_key(
        self, system: str, user: str, *, max_tokens: int, json_mode: bool
    ) -> str:
        blob = json.dumps(
            {
                "provider": self.provider,
                "base_url": self.base_url,
                "model": self.model,
                "temperature": self.temperature,
                "max_tokens": max_tokens,
                "json_mode": json_mode,
                "system": system,
                "user": user,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    # ---- 调用 -----------------------------------------------------------
    def chat(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 400,
        json_mode: Optional[bool] = None,
    ) -> LLMResult:
        effective_json = self.json_mode if json_mode is None else json_mode
        key = self._cache_key(
            system, user, max_tokens=max_tokens, json_mode=effective_json
        )
        cached = self._cache.get(key)
        if cached:
            self.cached_calls += 1
            self.cached_prompt_tokens += int(cached.get("prompt_tokens") or 0)
            self.cached_completion_tokens += int(cached.get("completion_tokens") or 0)
            return LLMResult(
                text=str(cached.get("text") or ""),
                model=str(cached.get("model") or self.model),
                prompt_tokens=int(cached.get("prompt_tokens") or 0),
                completion_tokens=int(cached.get("completion_tokens") or 0),
                latency_seconds=0.0,
                cached=True,
            )

        if self.calls >= self.max_calls:
            raise BudgetExceeded(f"调用次数达到上限 {self.max_calls}")
        if self.prompt_tokens + self.completion_tokens >= self.max_total_tokens:
            raise BudgetExceeded(f"token 用量达到上限 {self.max_total_tokens}")
        if not self._api_key:
            raise RuntimeError(f"未找到 {self.provider} 的 API Key（环境或项目 .env）")

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
            "max_tokens": max_tokens,
        }
        if effective_json:
            payload["response_format"] = {"type": "json_object"}
        if self.reasoning_split:
            payload["reasoning_split"] = True

        started = time.time()
        last_error: Optional[Exception] = None
        #: 内容审核拒绝是确定性的，退避重试没有意义，直接转降级通道
        rejected = ""
        for attempt in range(3):
            try:
                response = httpx.post(
                    self.base_url,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=payload,
                    timeout=self.timeout,
                )
                if is_sensitive_rejection(response.status_code, response.text[:500]):
                    rejected = response.text[:500]
                    break
                if response.status_code in (429, 500, 502, 503, 504):
                    raise RuntimeError(f"HTTP {response.status_code}")
                response.raise_for_status()
                data = response.json()
                base_resp = data.get("base_resp") or {}
                status_code = int(base_resp.get("status_code") or 0)
                if status_code != 0:
                    raise RuntimeError(
                        f"provider status {status_code}: {base_resp.get('status_msg')}"
                    )
                choice = (data.get("choices") or [{}])[0]
                message = choice.get("message") or {}
                text, reasoning = split_reasoning(
                    str(message.get("content") or ""),
                    message.get("reasoning_details"),
                )
                usage = data.get("usage") or {}
                result = LLMResult(
                    text=text,
                    model=str(data.get("model") or self.model),
                    prompt_tokens=int(usage.get("prompt_tokens") or 0),
                    completion_tokens=int(usage.get("completion_tokens") or 0),
                    latency_seconds=round(time.time() - started, 3),
                    reasoning=reasoning,
                )
                self.calls += 1
                self.prompt_tokens += result.prompt_tokens
                self.completion_tokens += result.completion_tokens
                self._append_cache(
                    {
                        "key": key,
                        "provider": self.provider,
                        "model": result.model,
                        "prompt_tokens": result.prompt_tokens,
                        "completion_tokens": result.completion_tokens,
                        "text": result.text,
                        "created_at": time.time(),
                    }
                )
                self._cache[key] = {
                    "text": result.text,
                    "model": result.model,
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                }
                return result
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
        if rejected:
            return self._complete_by_fallback(key, system, user, max_tokens, rejected)
        self.failures += 1
        raise RuntimeError(
            f"{self.provider} 调用失败: {type(last_error).__name__}: {last_error}"
        )

    def _complete_by_fallback(
        self, key: str, system: str, user: str, max_tokens: int, rejected: str
    ) -> LLMResult:
        """审核拒绝后改由 DeepSeek 补跑；仍拿不到正文就在本次运行内记空占位。

        补跑失败可能只是网络抖动或限流：空占位只放进内存缓存、不写缓存文件，
        本次运行不会反复撞墙，下次重跑仍会重试。
        """
        hit = call_sensitive_fallback(
            system, user, max_tokens=max_tokens, temperature=self.temperature
        )
        item: Dict[str, Any] = {
            "key": key,
            "provider": "deepseek-fallback" if hit else self.provider,
            "model": str(hit["model"]) if hit else self.model,
            "prompt_tokens": int(hit["prompt_tokens"]) if hit else 0,
            "completion_tokens": int(hit["completion_tokens"]) if hit else 0,
            "text": str(hit["text"]) if hit else "",
            "created_at": time.time(),
            "content_rejected": not hit,
            "rejected_body": rejected[:200],
        }
        if hit:
            item["fallback_chain"] = hit["attempts"]
            self.calls += 1
            self.prompt_tokens += item["prompt_tokens"]
            self.completion_tokens += item["completion_tokens"]
            self._append_cache(item)
        self._cache[key] = item
        return LLMResult(
            text=item["text"],
            model=item["model"],
            prompt_tokens=item["prompt_tokens"],
            completion_tokens=item["completion_tokens"],
            latency_seconds=0.0,
        )

    def usage(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "temperature": self.temperature,
            "json_mode": self.json_mode,
            "calls": self.calls,
            "cached_calls": self.cached_calls,
            "failures": self.failures,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cached_prompt_tokens": self.cached_prompt_tokens,
            "cached_completion_tokens": self.cached_completion_tokens,
            "total_tokens": (
                self.prompt_tokens
                + self.completion_tokens
                + self.cached_prompt_tokens
                + self.cached_completion_tokens
            ),
            "max_calls": self.max_calls,
            "max_total_tokens": self.max_total_tokens,
        }


__all__ = ["BudgetExceeded", "LLMResult", "OpenAICompatClient"]
