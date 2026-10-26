"""回填脚本的直连调度器：把 nightly 调度器接口接到 OpenAI 兼容 API（MiniMax / DeepSeek）。

路由支持 ``cloud:deepseek:<key_alias>:<model>``：DeepSeek 按角色分 key，前缀缓存互不挤占；
MiniMax 走订阅 key，不分角色。统计调用、token、前缀缓存命中，并单独记录最近一次请求，
供抽样脚本逐段核对。密钥只以 ``provider:alias`` 形式出现在统计里，不落任何 key 正文。
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

from core.utils.logger import get_module_logger

ROOT_DIR = Path(__file__).resolve().parents[3]
logger = get_module_logger(__name__, "nightly_processor.log")

PROVIDERS = {
    "minimax": (
        "https://api.minimaxi.com/v1/chat/completions",
        "MINIMAX_PLAN_API_KEY",
        "MiniMax-M3",
    ),
    "deepseek": (
        "https://api.deepseek.com/chat/completions",
        "DEEPSEEK_API_KEY",
        "deepseek-v4-flash",
    ),
}
_THINK = re.compile(r"<think(?:ing)?>.*?</think(?:ing)?>", re.DOTALL | re.IGNORECASE)
#: 额度用尽而不是临时限流的响应特征（MiniMax plan 常见：余额不足 / 额度到期）
_QUOTA_HINTS = re.compile(
    r"insufficient|quota|balance|余额|额度|欠费|plan\s*(?:expired|limit)|usage\s*limit",
    re.IGNORECASE,
)


def parse_route(model_hint: str, default_provider: str) -> tuple[str, str, str]:
    """把 ``cloud:provider[:alias]:model`` 拆成 (provider, alias, model)。"""
    raw = str(model_hint or "").strip()
    provider = default_provider
    alias = ""
    model = PROVIDERS[default_provider][2]
    if raw.startswith("cloud:"):
        parts = raw.split(":")
        name = parts[1].strip().lower() if len(parts) > 1 else ""
        if name in PROVIDERS:
            provider = name
            if len(parts) >= 4:
                alias = parts[2].strip().lower()
                model = ":".join(parts[3:]).strip() or model
            elif len(parts) == 3:
                model = parts[2].strip() or model
    elif raw:
        parts = raw.split(":")
        if len(parts) >= 2 and parts[0].strip().lower() in PROVIDERS:
            provider = parts[0].strip().lower()
            if len(parts) >= 3:
                alias = parts[1].strip().lower()
                model = ":".join(parts[2:]).strip() or model
            else:
                model = parts[1].strip() or model
        else:
            model = raw
    if provider == "minimax" and "minimax" not in model.lower():
        model = PROVIDERS["minimax"][2]
    return provider, alias, model


def resolve_key(provider: str, alias: str) -> str:
    """按 provider/alias 取密钥：DeepSeek 别名大小写不敏感，缺失时退回默认 key。"""
    if provider == "minimax":
        return str(os.getenv(PROVIDERS["minimax"][1]) or "")
    default_key = str(os.getenv("DEEPSEEK_API_KEY") or "")
    if not alias or alias == "default":
        return default_key
    target = f"DEEPSEEK_API_KEY_{alias}".upper()
    for name, value in os.environ.items():
        if name.upper() == target and value:
            return str(value)
    return default_key


class DirectScheduler:
    """把调度器接口直连 OpenAI 兼容 API；按 model_hint 选择供应商、key 与型号。"""

    def __init__(self, provider: str, *, quota_fallback: str = "") -> None:
        from dotenv import load_dotenv

        load_dotenv(ROOT_DIR / ".env")
        self.provider = provider
        #: MiniMax 额度用尽后改走该路由（通常是同角色的 DeepSeek key）；空表示不降级
        self.quota_fallback = str(quota_fallback or "").strip()
        self.quota_exhausted = False
        self.usage = {
            "calls": 0,
            "prompt": 0,
            "cached": 0,
            "completion": 0,
            "fallback": 0,
            "quota_switch": 0,
            "errors": 0,
            "by_key": {},
            "last": {},
        }

    def _route(self, model_hint: str) -> tuple[str, str, str, str, str]:
        if self.quota_exhausted and self.quota_fallback:
            name, alias, model = parse_route(self.quota_fallback, "deepseek")
        else:
            name, alias, model = parse_route(model_hint, self.provider)
        url, _env_key, _default_model = PROVIDERS[name]
        return name, alias, url, resolve_key(name, alias), model

    def _switch_quota_fallback(self, name: str, detail: str) -> bool:
        """MiniMax 额度用尽时切到配置的 DeepSeek 路由；不记录响应正文。"""
        if name != "minimax" or self.quota_exhausted or not self.quota_fallback:
            return False
        if not _QUOTA_HINTS.search(str(detail or "")):
            return False
        self.quota_exhausted = True
        self.usage["quota_switch"] += 1
        _name, alias, model = parse_route(self.quota_fallback, "deepseek")
        logger.warning(
            "MiniMax 额度已用尽，后续调用改走 deepseek:%s:%s", alias or "default", model
        )
        return True

    def _bucket(self, name: str, alias: str) -> dict:
        label = f"{name}:{alias or 'default'}"
        return self.usage["by_key"].setdefault(
            label, {"calls": 0, "prompt": 0, "cached": 0, "completion": 0}
        )

    async def submit_llm_task(self, prompt, **kwargs):
        import httpx

        model_hint = kwargs.get("model_hint", "")
        for attempt in range(4):
            name, alias, url, key, model = self._route(model_hint)
            payload = {
                "model": model,
                "messages": prompt,
                "max_tokens": int(kwargs.get("max_tokens") or 4096),
                "temperature": float(kwargs.get("temperature") or 0.2),
            }
            if name == "minimax":
                payload["reasoning_split"] = True
            if name != self.provider:
                self.usage["fallback"] += 1
            try:
                async with httpx.AsyncClient(timeout=300) as client:
                    response = await client.post(
                        url, headers={"Authorization": f"Bearer {key}"}, json=payload
                    )
            except Exception:  # noqa: BLE001 - 网络抖动退避重试
                await asyncio.sleep(3 * (attempt + 1))
                continue
            body = response.text[:500]
            if response.status_code in (402, 403, 429) and self._switch_quota_fallback(
                name, body
            ):
                continue
            if response.status_code == 422:
                yield {
                    "error": "sensitive",
                    "non_retryable": True,
                    "details": {"status": 422, "body": response.text[:300]},
                }
                return
            if response.status_code in (429, 500, 502, 503, 504):
                await asyncio.sleep(5 * (attempt + 1))
                continue
            if response.status_code != 200:
                break
            try:
                data = response.json()
            except Exception:  # noqa: BLE001 - 上游返回非 JSON，按失败处理
                break
            base_resp = data.get("base_resp") or {}
            code = base_resp.get("status_code") if isinstance(base_resp, dict) else None
            provider_error = data.get("error")
            if code not in (0, None) or provider_error:
                detail = (
                    f"{code} {base_resp.get('status_msg') or ''} {provider_error or ''}"
                ).strip()
                if self._switch_quota_fallback(name, detail):
                    continue
                self.usage["errors"] += 1
                yield {
                    "error": "provider",
                    "non_retryable": True,
                    "details": {"status": 200, "body": detail[:300]},
                }
                return
            usage = data.get("usage") or {}
            prompt_tokens = int(usage.get("prompt_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or 0)
            # 前缀缓存命中：DeepSeek 用 prompt_cache_hit_tokens，OpenAI 兼容口径在 details 里
            details = usage.get("prompt_tokens_details") or {}
            cached_tokens = int(
                usage.get("prompt_cache_hit_tokens")
                or details.get("cached_tokens")
                or usage.get("cached_tokens")
                or 0
            )
            self.usage["calls"] += 1
            self.usage["prompt"] += prompt_tokens
            self.usage["completion"] += completion_tokens
            self.usage["cached"] += cached_tokens
            bucket = self._bucket(name, alias)
            bucket["calls"] += 1
            bucket["prompt"] += prompt_tokens
            bucket["completion"] += completion_tokens
            bucket["cached"] += cached_tokens
            self.usage["last"] = {
                "provider": name,
                "alias": alias or "default",
                "model": model,
                "prompt": prompt_tokens,
                "cached": cached_tokens,
                "completion": completion_tokens,
            }
            message = ((data.get("choices") or [{}])[0].get("message")) or {}
            yield _THINK.sub("", str(message.get("content") or "")).strip()
            return
        self.usage["errors"] += 1
        yield ""


__all__ = ["PROVIDERS", "DirectScheduler", "parse_route", "resolve_key"]
