"""夜间蒸馏的模型路由：DeepSeek 按角色分 key，MiniMax 走订阅 key。

DeepSeek 的前缀缓存按 API key 隔离。同一角色的提示词前缀逐字节固定，再把该角色固定到
``DEEPSEEK_API_KEY_<Alias>``（路由写成 ``cloud:deepseek:<alias>:<model>``），不同角色的
缓存互不挤占，命中率才稳定。没有专属 key 的角色（ye / tt / lin）用默认 key，前缀仍然
按角色固定，只是与其他默认 key 角色共享账户配额。

MiniMax Token Plan 是订阅制、不按量计费，也不分角色 key，统一走 ``plan`` 别名。
"""

from __future__ import annotations

from core.services.dual_role.personas import resolve_role_id

DEEPSEEK_MODEL = "deepseek-v4-flash"
MINIMAX_MODEL = "MiniMax-M3"

#: scope → DEEPSEEK_API_KEY_<Alias>；未列出的角色用默认 DEEPSEEK_API_KEY
DEEPSEEK_KEY_ALIASES = {
    "aveline": "aveline",
    "ling": "ling",
    "rushuang": "rushuang",
    "yeye": "yeye",
}


def deepseek_key_alias(scope: str) -> str:
    """该角色使用的 DeepSeek key 别名；没有专属 key 时返回空串（默认 key）。"""
    role_id = resolve_role_id(scope)
    return DEEPSEEK_KEY_ALIASES.get(role_id, "")


def deepseek_route(scope: str, model: str = DEEPSEEK_MODEL) -> str:
    alias = deepseek_key_alias(scope)
    model = str(model or DEEPSEEK_MODEL).strip()
    return f"cloud:deepseek:{alias}:{model}" if alias else f"cloud:deepseek:{model}"


def minimax_route(model: str = MINIMAX_MODEL) -> str:
    return f"cloud:minimax:plan:{str(model or MINIMAX_MODEL).strip()}"


def fallback_route_for_scope(scope: str) -> str:
    """422 内容审核降级型号：用同一角色自己的 DeepSeek key。"""
    return deepseek_route(scope)


__all__ = [
    "DEEPSEEK_KEY_ALIASES",
    "DEEPSEEK_MODEL",
    "MINIMAX_MODEL",
    "deepseek_key_alias",
    "deepseek_route",
    "fallback_route_for_scope",
    "minimax_route",
]
