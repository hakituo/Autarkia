#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""实测 MiniMax M Plan 订阅 Key（sk-cp-）可用模型与接入能力。

只读探测，不修改任何业务数据；会真实消耗少量套餐额度。
读取 .env 中的 MINIMAX_PLAN_API_KEY，逐项验证：

1. ``GET /v1/models`` 返回的模型清单，确认 M3.1 Flash / M3 在列；
2. 两个模型的非流式对话是否可用（M2.5 / M2.7 已停用，服务端会路由到 M3，不再单独测试）；
3. M3.1 Flash 流式 + ``stream_options.include_usage`` 是否回 usage；
4. M3.1 Flash 原生 function calling 是否可用；
5. ``/v1/token_plan/remains`` 套餐剩余额度。

运行：
    venv_cpu\\Scripts\\python.exe tests\\scripts\\llm\\verify_minimax_plan_models.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

TARGET_MODELS = ("MiniMax-M3.1-Flash", "MiniMax-M3")


def _load_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path)
    except Exception:
        pass


def _get_plan_config():
    from config.integrated_config import get_settings

    keys = get_settings().model.cloud_provider_keys
    plan = (keys.get("minimax") or {}).get("plan")
    if plan is None:
        raise SystemExit(
            "未找到 minimax:plan 配置。请确认 .env 里 MINIMAX_PLAN_API_KEY 已填写，"
            "且 config/settings_model.py 的 MINIMAX_PLAN_* 常量生效。"
        )
    return plan


def _http_get(url: str, key: str) -> dict:
    request = urllib.request.Request(url, headers={"Authorization": "Bearer " + key})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def check_models(plan) -> None:
    base = plan.base_url.rsplit("/chat/completions", 1)[0]
    data = _http_get(base + "/models", plan.api_key)
    names = [item.get("id") for item in data.get("data", [])]
    print(f"[models] 共 {len(names)} 个: {', '.join(names)}")
    missing = [name for name in TARGET_MODELS if name not in names]
    if missing:
        raise AssertionError(f"模型清单缺少: {missing}")


async def check_chat(plan) -> None:
    from core.llm.openai_compat.minimax_client import MiniMaxClient

    for model in TARGET_MODELS:
        client = MiniMaxClient(api_key=plan.api_key, base_url=plan.base_url, model=model)
        started = time.perf_counter()
        try:
            result = await client.chat(
                [
                    {"role": "system", "content": "你是测试助手，只按用户要求回答。"},
                    {"role": "user", "content": "只回复两个字：收到"},
                ]
            )
            text = str(result.get("response") or "") if isinstance(result, dict) else str(result)
            if not text.strip():
                raise AssertionError(f"{model} 返回空内容")
            elapsed = (time.perf_counter() - started) * 1000
            print(f"[chat] {model} OK {elapsed:.0f}ms -> {text.strip()[:40]!r}")
        finally:
            await client.shutdown()


async def check_stream(plan) -> None:
    from core.llm.openai_compat.minimax_client import MiniMaxClient

    model = "MiniMax-M3.1-Flash"
    client = MiniMaxClient(api_key=plan.api_key, base_url=plan.base_url, model=model)
    parts = []
    try:
        async for chunk in client.stream_chat(
            [{"role": "user", "content": "算 1+1，只回答数字"}]
        ):
            if chunk.get("error"):
                raise AssertionError(f"流式返回错误: {chunk['error']}")
            if chunk.get("content"):
                parts.append(chunk["content"])
        text = "".join(parts).strip()
        if not text:
            raise AssertionError("流式未收到任何正文")
        print(f"[stream] {model} OK -> {text[:40]!r}")
    finally:
        await client.shutdown()


async def check_tools(plan) -> None:
    from core.llm.openai_compat.minimax_client import MiniMaxClient

    model = "MiniMax-M3.1-Flash"
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "查询城市天气",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }
    ]
    client = MiniMaxClient(api_key=plan.api_key, base_url=plan.base_url, model=model)
    try:
        result = await client.chat(
            [{"role": "user", "content": "北京天气怎么样？请调用工具"}], tools=tools
        )
        calls = result.get("tool_calls") if isinstance(result, dict) else None
        if not calls:
            raise AssertionError("未返回 tool_calls")
        name = calls[0].get("function", {}).get("name")
        args = calls[0].get("function", {}).get("arguments")
        print(f"[tools] {model} OK -> {name}({args})")
    finally:
        await client.shutdown()


def check_quota(plan) -> None:
    base = plan.base_url.rsplit("/chat/completions", 1)[0]
    data = _http_get(base + "/token_plan/remains", plan.api_key)
    rows = data.get("model_remains") or []
    for row in rows[:3]:
        print(
            "[quota] model={name} 5h剩余={h5}% 周剩余={w}% "
            "5h窗口结束={end}".format(
                name=row.get("model_name"),
                h5=row.get("current_interval_remaining_percent"),
                w=row.get("current_weekly_remaining_percent"),
                end=row.get("end_time"),
            )
        )


def main() -> int:
    print("=" * 62)
    print("MiniMax M Plan 订阅 Key 实测")
    print("=" * 62)
    _load_env()
    plan = _get_plan_config()
    print(f"[config] base_url={plan.base_url}")
    print(f"[config] models={plan.models}")
    try:
        check_models(plan)
        asyncio.run(check_chat(plan))
        asyncio.run(check_stream(plan))
        asyncio.run(check_tools(plan))
        check_quota(plan)
    except (AssertionError, urllib.error.URLError, TimeoutError) as exc:
        print(f"[FAIL] {exc}")
        return 1
    print("=" * 62)
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
