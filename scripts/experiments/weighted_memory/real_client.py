"""真实集实验的调用层：内容审核 / 额度降级客户端 + 并发预热与按轮退避。

先用 ``Recorder`` 走一遍收集全部请求，再并发调用同一份缓存；串行阶段全部命中缓存，
结果与串行执行一致、可断点续跑。
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .client_core import LLMResult
from .llm_client import OpenAICompatClient

MAX_ROUNDS = 6


class PrefetchIncomplete(RuntimeError):
    """预热阶段仍有请求失败；不进入串行阶段，避免半途崩溃。"""


class ModerationTolerantClient(OpenAICompatClient):
    """供应商内容审核拒绝（HTTP 422）是确定性的：不重试，记为空产物并计数。

    拒绝记录落在旁挂文件里，重跑时直接返回空结果，不再打到供应商。
    """

    def __init__(self, *, rejected_path: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.rejected_path = Path(rejected_path)
        self._rejected: set[str] = set()
        if self.rejected_path.exists():
            self._rejected = set(self.rejected_path.read_text(encoding="utf-8").split())
        self._reject_lock = threading.Lock()
        self.rejections = 0
        self.fallbacks = 0
        #: 主供应商额度用完时置真：缓存未命中的请求直接走 DeepSeek，不再打主供应商
        self.deepseek_for_missing = False

    def chat(
        self, system: str, user: str, *, max_tokens: int = 400, json_mode: Any = None
    ) -> LLMResult:
        effective_json = self.json_mode if json_mode is None else json_mode
        key = self._cache_key(system, user, max_tokens=max_tokens, json_mode=effective_json)
        if self.deepseek_for_missing and key not in self._cache and key not in self._rejected:
            # 复用 client_core 的降级通道：结果按原 key 落缓存，并打 deepseek-fallback 标记
            result = self._complete_by_fallback(
                key, system, user, max_tokens, "primary_quota_exhausted"
            )
            entry = self._cache.get(key) or {}
            with self._reject_lock:
                if entry.get("content_rejected"):
                    self.rejections += 1
                else:
                    self.fallbacks += 1
            return result
        if key not in self._rejected:
            try:
                result = super().chat(system, user, max_tokens=max_tokens, json_mode=json_mode)
                # client_core 遇 422 会改由 DeepSeek 补跑并在缓存条目上打标：计数以便报告混模比例
                entry = self._cache.get(key) or {}
                with self._reject_lock:
                    if entry.get("content_rejected"):
                        self.rejections += 1
                    elif entry.get("provider") == "deepseek-fallback":
                        self.fallbacks += 1
                return result
            except RuntimeError as exc:
                if "422" not in str(exc):
                    raise
                with self._reject_lock:
                    if key not in self._rejected:
                        self._rejected.add(key)
                        with open(self.rejected_path, "a", encoding="utf-8") as handle:
                            handle.write(key + "\n")
        with self._reject_lock:
            self.rejections += 1
        return LLMResult(
            text="", model=self.model, prompt_tokens=0, completion_tokens=0, latency_seconds=0.0
        )


class Recorder:
    """只记录 prompt 不调用；返回空文本，供第一遍收集全部请求。"""

    def __init__(self, model: str, temperature: float) -> None:
        self.model, self.temperature = model, temperature
        self.requests: list[tuple] = []

    def chat(
        self, system: str, user: str, *, max_tokens: int = 400, json_mode: Any = None
    ) -> LLMResult:
        self.requests.append((system, user, max_tokens, json_mode))
        return LLMResult(
            text="",
            model=self.model,
            prompt_tokens=0,
            completion_tokens=0,
            latency_seconds=0.0,
            cached=True,
        )

    def usage(self) -> dict[str, Any]:
        return {"calls": 0, "cached_calls": 0, "prompt_tokens": 0, "completion_tokens": 0}


def prefetch(
    client: OpenAICompatClient, job: Callable[[Any], Any], workers: int, label: str
) -> dict[str, Any]:
    recorder = Recorder(client.model, client.temperature)
    job(recorder)
    pending = list({json.dumps(r, ensure_ascii=False): r for r in recorder.requests}.values())
    lock = threading.Lock()
    original = client._append_cache

    def locked_append(item: dict[str, Any]) -> None:
        with lock:
            original(item)

    client._append_cache = locked_append  # type: ignore[method-assign]
    failures: list[str] = []
    failed: list[tuple] = []
    started = time.time()

    def call(request: tuple) -> None:
        system, user, max_tokens, json_mode = request
        try:
            client.chat(system, user, max_tokens=max_tokens, json_mode=json_mode)
        except Exception as exc:  # noqa: BLE001 - 失败的按轮退避重试
            failures.append(str(exc)[:200])
            failed.append(request)

    batch = pending
    for round_no in range(MAX_ROUNDS):
        failed.clear()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for index, _ in enumerate(pool.map(call, batch), start=1):
                if index % 100 == 0:
                    print(
                        f"  [{label}] 第{round_no + 1}轮 {index}/{len(batch)} "
                        f"失败 {len(failed)} {round(time.time() - started)}s",
                        flush=True,
                    )
        if not failed:
            break
        batch = list(failed)
        wait = 60 * (round_no + 1)
        print(f"  [{label}] 第{round_no + 1}轮剩 {len(batch)} 条失败，{wait}s 后重试", flush=True)
        time.sleep(wait)
    client._append_cache = original  # type: ignore[method-assign]
    if failed:
        raise PrefetchIncomplete(
            f"{label}: {len(failed)} 条仍失败（限流或额度），已完成的在缓存里，稍后重跑即可续"
        )
    wall = round(time.time() - started, 1)
    print(f"[{label}] 请求 {len(pending)} 失败 {len(failures)} 用时 {wall}s", flush=True)
    return {
        "requests": len(pending),
        "failures": len(failures),
        "wall_seconds": wall,
        "failure_samples": failures[:5],
    }


__all__ = ["MAX_ROUNDS", "ModerationTolerantClient", "PrefetchIncomplete", "Recorder", "prefetch"]
