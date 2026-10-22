#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证「决策模型引擎」的接入与精编 state 有效。

静态部分（默认执行，不需要网络）：
  1. 精编 state 远小于线上 9k 字符的上下文 dump；
  2. state 不含原始冷却秒数（算术应由代码判断，不该丢给模型比较）；
  3. content_planner 的决策链路确实挂了影子钩子；
  4. 三个配置项已在 Settings 中声明。

实时部分（``--live``，需要 OPENROUTER_API_KEY + 代理）：
  对同一段 state 真实调用 Luna Decisions 与 Microsoft-Decision-1，
  打印 noul / 重判间隔 / 置信度 / 输入 token / 实际花费，确认协议可用。

用法：
    venv_cpu\\Scripts\\python.exe tests\\scripts\\active_care\\verify_decision_model_engine.py
    venv_cpu\\Scripts\\python.exe tests\\scripts\\active_care\\verify_decision_model_engine.py --live
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.llm.decisions import (  # noqa: E402
    MODEL_LUNA_DECISIONS,
    MODEL_MS_DECISION_1,
    resolve_decisions_client,
)
from core.services.active_care.decision.engine import (  # noqa: E402
    build_compact_state,
    build_questions,
)

# 线上真实决策调用实测约 9,103 字符 / 4,368 prompt token
LIVE_PROMPT_CHARS = 9103
STATE_CHAR_BUDGET = 1500

FAILURES: list[str] = []


def _check(condition: bool, label: str, detail: str = "") -> None:
    mark = "OK  " if condition else "FAIL"
    print(f"  [{mark}] {label}{('  ' + detail) if detail else ''}")
    if not condition:
        FAILURES.append(label)


def _sample_ctx() -> dict:
    return {
        "now": "2026-10-13 15:00",
        "tod": "工作日下午",
        "chosen_action": "user_health_reminder",
        "time_since_last_interaction": "2小时",
        "elapsed_seconds": 7080,
        "time_since_last_proactive_send": "40分钟",
        "elapsed_since_last_proactive_seconds": 2400,
        "quiet_mode_active": False,
        "sleep_session": False,
        "sleep_status_desc": "用户醒着",
        "priority_focus": {"portrait_priority": ["这周要交报告"]},
        "user_activity": {"process": "workbuddyai.exe", "busy": False},
        "recent_history_summary": ["assistant: 早安", "user: 下午三点提醒我吃药"],
    }


def verify_compact_state() -> str:
    """验证精编 state 的体量与内容约束。"""
    print("[1] 精编 state")
    state = build_compact_state(
        _sample_ctx(),
        persona_name="Aveline",
        extra_facts={"到期提醒": "用户要求的三点吃药提醒已到期"},
    )
    _check(len(state) <= STATE_CHAR_BUDGET, "state 在预算内", f"{len(state)} 字符")
    ratio = LIVE_PROMPT_CHARS / max(len(state), 1)
    _check(ratio >= 5, "相对线上 prompt 显著压缩", f"{ratio:.1f}×")
    _check("2400" not in state and "7080" not in state, "不含原始冷却秒数")
    _check("下午三点提醒我吃药" in state, "保留了用户原话")
    _check("已到期" in state, "保留了到期提醒事实")
    return state


def verify_wiring() -> None:
    """验证 content_planner 决策链路挂了影子钩子。"""
    print("[2] 决策链路接线")
    source = (
        PROJECT_ROOT / "core/services/active_care/decision/content_planner.py"
    ).read_text(encoding="utf-8")
    _check("maybe_run_decision_shadow" in source, "content_planner 调用影子钩子")
    _check("llm_ctx=llm_ctx" in source, "影子钩子传入线上 llm_ctx")


def verify_config() -> None:
    """验证三个配置项已在 Settings 中声明。"""
    print("[3] 配置声明")
    source = (PROJECT_ROOT / "config/settings_life.py").read_text(encoding="utf-8")
    for key in (
        "active_care_decision_shadow_enabled",
        "active_care_decision_shadow_models",
        "active_care_decision_send_threshold",
    ):
        _check(key in source, f"{key} 已声明")


async def verify_live(state: str) -> None:
    """真实调用两个决策模型，确认协议可用并打印成本。"""
    print("[4] 实时调用（--live）")
    client = resolve_decisions_client()
    if not client.api_key:
        _check(False, "OPENROUTER_API_KEY 已配置")
        return
    questions = build_questions()
    for model in (MODEL_LUNA_DECISIONS, MODEL_MS_DECISION_1):
        result = await client.decide(model=model, state=state, questions=questions)
        if result is None:
            _check(False, f"{model} 返回结果")
            continue
        noul = result.noul("worth_contacting")
        _check(noul is not None, f"{model} 返回 noul", f"noul={noul}")
        _check(result.output_tokens == 0, f"{model} 输出 token 为 0（输出免费）")
        print(
            f"        model={result.model} retry={result.choice('retry_bucket')} "
            f"in={result.input_tokens} cost=${result.cost_usd:.8f} "
            f"latency={result.latency_ms:.0f}ms"
        )
    await client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="验证决策模型引擎接入")
    parser.add_argument("--live", action="store_true", help="额外做一次真实 API 调用")
    args = parser.parse_args()

    state = verify_compact_state()
    verify_wiring()
    verify_config()
    if args.live:
        asyncio.run(verify_live(state))

    print()
    if FAILURES:
        print(f"验证未通过：{len(FAILURES)} 项失败")
        for item in FAILURES:
            print(f"  - {item}")
        return 1
    print("验证通过：决策模型引擎接入与精编 state 均符合预期 ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
