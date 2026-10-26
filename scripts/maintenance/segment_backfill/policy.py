"""回填策略：回填哪些 scope、每段用哪个模型、哪些段不生成梗概。

- 只做人设里的角色：``perspective_for_scope`` 认得出人设的 scope 才回填；认不出的历史
  scope（如 chiba / kafka / rushuang 这类人设库里已没有的）一律跳过，不按中性模板硬做。
- 模型：aveline 全部用 MiniMax；ling 的 2026 年 1–2 月早期聊天也用 MiniMax；其余一律 DeepSeek。
  DeepSeek 按角色分 key（``model_routes``），MiniMax 走订阅 key、不分角色。
- lin / ling 人设为未成年：段内含露骨性内容的不生成梗概，只计数。
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
MINIMAX_RULES = (
    ("aveline", None, None),
    (
        "ling",
        datetime(2026, 1, 1, tzinfo=_TZ).timestamp(),
        datetime(2026, 3, 1, tzinfo=_TZ).timestamp(),
    ),
)
MINOR_PERSONA_SCOPES = frozenset({"lin", "ling"})
_EXPLICIT = re.compile(
    "鸡巴|撸管|撸|逼|屁眼|射了|射精|BM|贞操锁|奶子|抠逼|色色|文爱|阳痿|精液|NTR|发情|屌|"
    "雌堕|母狗|飞机杯|乳头|某生理词|阴蒂|阴唇|插马眼|前列腺|足交|口交|肏|操你|骚"
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


def explicit_content(events) -> bool:
    """段内是否出现露骨性内容（抽样时可选跳过，避免上游 422 干扰缓存测量）。"""
    return any(_EXPLICIT.search(str(event.get("content") or "")) for event in events)


def excluded(scope: str, events) -> bool:
    """未成年人设的段含露骨性内容时不生成梗概。"""
    return scope in MINOR_PERSONA_SCOPES and explicit_content(events)


__all__ = [
    "DEEPSEEK",
    "MINIMAX",
    "excluded",
    "explicit_content",
    "fallback_route_for",
    "key_alias_for",
    "model_route_for",
    "persona_scopes",
    "provider_for",
]
