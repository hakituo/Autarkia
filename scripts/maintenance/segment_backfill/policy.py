"""回填策略：回填哪些 scope、每段用哪个模型。

- 只做人设里的角色：``perspective_for_scope`` 认得出人设的 scope 才回填；认不出的历史
  scope（如 chiba / kafka / rushuang 这类人设库里已没有的）一律跳过，不按中性模板硬做。
- 模型：默认全走 DeepSeek。MiniMax 余额于 2026-10-27 用尽（402 insufficient balance），
  aveline 剩余段改走 DeepSeek；ling 的 2026 年 1–2 月早期聊天原本走 MiniMax，现已全部回填完，
  规则保留但无待处理段。DeepSeek 按角色分 key（``model_routes``）；MiniMax 不分 key。
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from memory.nightly.model_routes import (
    deepseek_key_alias,
    deepseek_route,
    minimax_route,
)

ROOT_DIR = Path(__file__).resolve().parents[3]

MINIMAX, DEEPSEEK = "minimax", "deepseek"
_TZ = ZoneInfo("Asia/Shanghai")
#: (scope, 起, 止)：落在区间内的段用 MiniMax；止为 None 表示不限
#: 2026-10-27：MiniMax 余额用尽，aveline 规则移除，剩余段改走 DeepSeek。
MINIMAX_RULES = (
    (
        "ling",
        datetime(2026, 1, 1, tzinfo=_TZ).timestamp(),
        datetime(2026, 3, 1, tzinfo=_TZ).timestamp(),
    ),
)


def persona_scopes() -> list[str]:
    """有聊天数据、且人设库认得出的 scope。"""
    from memory.nightly.perspective import perspective_for_scope

    base = ROOT_DIR / "companion_data"
    scopes = []
    for directory in sorted(base.glob("*_data")):
        scope = directory.name[: -len("_data")]
        if (directory / "chat_history").exists() and perspective_for_scope(scope):
            scopes.append(scope)
    return scopes


def provider_for(scope: str, started_at: float) -> str:
    for rule_scope, start, end in MINIMAX_RULES:
        if scope != rule_scope:
            continue
        if (start is None or started_at >= start) and (end is None or started_at < end):
            return MINIMAX
    return DEEPSEEK


def model_route_for(scope: str, provider: str) -> str:
    """该段实际调用的路由：MiniMax 订阅 key，或该角色自己的 DeepSeek key。"""
    return minimax_route() if provider == MINIMAX else deepseek_route(scope)


def fallback_route_for(scope: str) -> str:
    """422 内容审核降级：用同一角色的 DeepSeek key，不串到别的角色账户。"""
    return deepseek_route(scope)


def key_alias_for(scope: str, provider: str) -> str:
    """统计与预览用：DeepSeek 的 key 别名；MiniMax 返回空（订阅 key 不分角色）。"""
    return "" if provider == MINIMAX else deepseek_key_alias(scope)


__all__ = [
    "DEEPSEEK",
    "MINIMAX",
    "fallback_route_for",
    "key_alias_for",
    "model_route_for",
    "persona_scopes",
    "provider_for",
]
