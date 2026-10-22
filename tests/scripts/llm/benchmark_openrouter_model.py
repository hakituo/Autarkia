#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenRouter 模型测速：TTFT + 生成吞吐（tokens/s）

通过 OpenRouter 流式接口（stream_options.include_usage）对指定模型发起多轮
相同请求，统计：
1. TTFT（首 token 时延，ms）：从发请求到收到第一个「正文」分片；
   推理模型另记首个推理分片时延，便于区分「思考耗时」与「解码耗时」
2. 生成吞吐（tokens/s）：usage.completion_tokens / 生成耗时（扣除正文 TTFT）
3. 端到端吞吐（tokens/s）：usage.completion_tokens / 整轮耗时
4. 每轮 usage（prompt/completion tokens）与响应摘要

注意：推理模型（如 MiniMax M3 系）先输出 reasoning 再输出正文，若 max_tokens
预算被思考吃满会出现「有 usage 无正文」，脚本会将该轮标记为仅推理并剔除统计。

用法（在项目根目录用 venv_core 运行）：
    venv_core\\Scripts\\python.exe tests\\scripts\\llm\\benchmark_openrouter_model.py
    venv_core\\Scripts\\python.exe tests\\scripts\\llm\\benchmark_openrouter_model.py ^
        --model minimax/minimax-m3.1-flash:free --rounds 3 --max-tokens 2048

依赖：.env 中 OPENROUTER_API_KEY；模型有地区限制时配 OPENROUTER_PROXY_URL
（或复用 TELEGRAM_PROXY_URL）。免费共享池限流时会自动退避重试。

退出码：0=至少一轮拿到正文；非0=全部失败。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Optional

# 引入项目根目录与 .env
ROOT = Path(__file__).resolve().parents[3]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(ROOT, ".env"), override=True)

import aiohttp  # noqa: E402

BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "minimax/minimax-m3.1-flash:free"
DEFAULT_PROMPT = "请用大约 300 字介绍：什么是分布式系统？并举一个生活中的例子说明它解决了什么问题。"
SYSTEM_PROMPT = "你是一位简洁的技术助手，请直接输出正文，不要输出思考过程。"
RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_RETRIES = 3


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return float(sorted_vals[f])
    return float(sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f))


async def run_once(
    session: aiohttp.ClientSession,
    model: str,
    api_key: str,
    prompt: str,
    max_tokens: int,
    proxy: Optional[str],
) -> dict[str, Any]:
    """单轮流式请求，返回 TTFT / 耗时 / usage / 正文与推理摘要。"""
    payload = {
        "model": model,
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": 0.3,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    t_start = time.perf_counter()
    ttft_ms: Optional[float] = None  # 首个正文分片
    ttft_reason_ms: Optional[float] = None  # 首个推理分片
    content_parts: list[str] = []
    reason_parts: list[str] = []
    usage: dict[str, Any] = {}

    async with session.post(BASE_URL, json=payload, headers=headers, proxy=proxy) as resp:
        if resp.status != 200:
            body = (await resp.text())[:300]
            raise RuntimeError(f"HTTP {resp.status}: {body}")
        async for raw in resp.content:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            if chunk.get("usage"):
                usage = chunk["usage"]
                continue  # usage 块不带可计内容
            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}
                reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
                content = delta.get("content") or ""
                if reasoning:
                    if ttft_reason_ms is None:
                        ttft_reason_ms = (time.perf_counter() - t_start) * 1000
                    reason_parts.append(str(reasoning))
                if content:
                    if ttft_ms is None:
                        ttft_ms = (time.perf_counter() - t_start) * 1000
                    content_parts.append(str(content))

    total_ms = (time.perf_counter() - t_start) * 1000
    completion_tokens = int(usage.get("completion_tokens") or 0)
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    reasoning_tokens = int(
        ((usage.get("completion_tokens_details") or {}).get("reasoning_tokens")) or 0
    )
    text = "".join(content_parts).strip()
    has_content = bool(text)
    if has_content and ttft_ms is not None:
        gen_ms = max(total_ms - ttft_ms, 0.0)
        tps_gen = completion_tokens / (gen_ms / 1000) if gen_ms > 0 else 0.0
    else:
        gen_ms = 0.0
        tps_gen = 0.0
    return {
        "ok": has_content,
        "ttft_ms": ttft_ms,
        "ttft_reason_ms": ttft_reason_ms,
        "total_ms": total_ms,
        "gen_ms": gen_ms,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "reasoning_tokens": reasoning_tokens,
        "tps_gen": tps_gen,
        "tps_e2e": (completion_tokens / (total_ms / 1000)) if total_ms > 0 else 0.0,
        "text": text,
        "reasoning_len": len("".join(reason_parts)),
    }


def _fmt_ms(v: Optional[float]) -> str:
    return f"{v:7.0f}" if v is not None else "      -"


async def benchmark(model: str, rounds: int, warmup: int, max_tokens: int, prompt: str) -> int:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        print("[FAIL] .env 中未配置 OPENROUTER_API_KEY")
        return 1

    proxy = os.getenv("OPENROUTER_PROXY_URL") or os.getenv("TELEGRAM_PROXY_URL") or None
    print(f"[OK] 模型: {model}  rounds={rounds} (warmup={warmup})  max_tokens={max_tokens}")
    print(f"[OK] 代理: {proxy or '无（直连）'}")

    timeout = aiohttp.ClientTimeout(total=240, connect=15, sock_connect=15, sock_read=180)
    results: list[dict[str, Any]] = []

    async with aiohttp.ClientSession(timeout=timeout) as session:
        for i in range(-warmup, rounds):
            label = "warmup" if i < 0 else f"[{i + 1}/{rounds}]"
            print(f"  {label} 请求中…", flush=True)
            attempt = 0
            r: Optional[dict[str, Any]] = None
            while True:
                attempt += 1
                try:
                    r = await run_once(session, model, api_key, prompt, max_tokens, proxy)
                    break
                except Exception as e:  # noqa: BLE001
                    msg = str(e)
                    retryable = any(str(s) in msg for s in RETRY_STATUS) or "Timeout" in msg
                    if retryable and attempt <= MAX_RETRIES:
                        wait = 5 * attempt
                        print(f"  {label} 上游限流/抖动（{msg[:80]}…），{wait}s 后重试 {attempt}/{MAX_RETRIES}")
                        await asyncio.sleep(wait)
                        continue
                    print(f"  {label} FAIL: {msg[:200]}")
                    r = None
                    break
            if r is None:
                if i < 0:
                    return 1  # 预热就失败，直接退出
                continue
            if i < 0:
                print(f"  {label} 完成（不计入统计）正文ttft={_fmt_ms(r['ttft_ms'])}ms")
                continue
            if not r["ok"]:
                print(
                    f"  {label} 仅推理无正文（reasoning {r['reasoning_len']} 字符，"
                    f"completion={r['completion_tokens']} tok 打满预算），剔除统计"
                )
                continue
            results.append(r)
            print(
                f"  {label} 正文TTFT={_fmt_ms(r['ttft_ms'])}ms  "
                f"推理首片={_fmt_ms(r['ttft_reason_ms'])}ms  "
                f"总耗时={r['total_ms']:7.0f}ms  completion={r['completion_tokens']:>4} tok  "
                f"吞吐={r['tps_gen']:6.1f} tok/s (端到端 {r['tps_e2e']:.1f})"
            )

    if not results:
        print("\n[FAIL] 没有有效轮次（全部仅推理或失败）")
        return 1

    ttfts = [r["ttft_ms"] for r in results]
    tps_gen = [r["tps_gen"] for r in results]
    tps_e2e = [r["tps_e2e"] for r in results]
    totals = [r["total_ms"] for r in results]

    print("\n" + "=" * 76)
    print(f"汇总（{len(results)} 轮有效，模型 {model}）")
    print(
        f"  正文 TTFT     avg={statistics.mean(ttfts):7.0f}ms  p50={_percentile(ttfts, 50):7.0f}ms  "
        f"min={min(ttfts):7.0f}ms  max={max(ttfts):7.0f}ms"
    )
    print(
        f"  生成吞吐      avg={statistics.mean(tps_gen):7.1f} tok/s  p50={_percentile(tps_gen, 50):7.1f} tok/s  "
        f"max={max(tps_gen):7.1f} tok/s"
    )
    print(f"  端到端吞吐    avg={statistics.mean(tps_e2e):7.1f} tok/s")
    print(f"  整轮耗时      avg={statistics.mean(totals):7.0f}ms")
    sample = max(results, key=lambda r: len(r["text"]))
    print(f"  响应示例（最长一轮 {len(sample['text'])} 字）：{sample['text'][:120]}…")
    print("=" * 76)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenRouter 模型测速：TTFT + tokens/s")
    parser.add_argument("--model", default=os.getenv("XIAOYOU_BENCHMARK_MODEL", DEFAULT_MODEL))
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1, help="预热轮数（不计入统计，默认 1）")
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    args = parser.parse_args()

    rounds = max(1, args.rounds)
    warmup = max(0, args.warmup)
    return asyncio.run(benchmark(args.model, rounds, warmup, args.max_tokens, args.prompt))


if __name__ == "__main__":
    sys.exit(main())
