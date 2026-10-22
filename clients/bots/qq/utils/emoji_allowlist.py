"""QQ emoji 白名单数据源：从人设配置解析"允许使用哪些 emoji"，并做进程内缓存。

本模块只提供**数据**（某角色允许的 emoji 集合），过滤动作在
`clients/bots/qq/utils/text_cleaners.py` 的统一清洗入口 `clean_qq_text` 里执行。

emoji 判定范围表是「所有聊天端通用」的能力，真源在 `core.utils.text_segmenter`
的 `is_emoji_char`（安卓端对应 `utils/text/EmojiRanges.kt`），本模块只做角色白名单
的收集与缓存，不重复维护范围表。

白名单当前默认关闭（见 [EMOJI_ALLOWLIST_ENABLED]），开启后 `clean_qq_text` 才会
按本模块解析出的集合过滤 emoji。
"""

from __future__ import annotations

from typing import Optional

from core.utils.text_segmenter import is_emoji_char as _is_emoji_char

__all__ = [
    "EMOJI_ALLOWLIST_ENABLED",
    "_allowed_emoji_cache",
    "_collect_allowed_emojis_from_persona",
    "_extract_emojis_from_text",
    "clear_allowed_emoji_cache",
    "get_allowed_emojis",
]


# 功能实现保留，但当前全局不启用 emoji 白名单过滤。
EMOJI_ALLOWLIST_ENABLED = False

# 允许的 emoji 缓存：profile_filename -> set(emoji字符)；None 表示人设加载失败
_allowed_emoji_cache: dict[str, Optional[set[str]]] = {}


def _extract_emojis_from_text(text: str) -> set[str]:
    """从文本中提取所有 emoji 字符。"""
    return {ch for ch in str(text or "") if _is_emoji_char(ch)}


def _collect_allowed_emojis_from_persona(persona_data: dict) -> set[str]:
    """从角色配置数据中递归收集允许使用的 emoji。"""
    collected: set[str] = set()
    if not isinstance(persona_data, dict):
        return collected

    scan_fields = [
        ("language_style", "tone_examples"),
        ("language_style", "keywords"),
        ("persona_enhance", "language_markers"),
        ("persona_enhance", "visual_instructions"),
    ]

    def _scan_value(value: object) -> None:
        if isinstance(value, str):
            collected.update(_extract_emojis_from_text(value))
        elif isinstance(value, list):
            for item in value:
                _scan_value(item)
        elif isinstance(value, dict):
            for nested_value in value.values():
                _scan_value(nested_value)

    for path in scan_fields:
        current: object = persona_data
        for key in path:
            if isinstance(current, dict):
                current = current.get(key)
            else:
                current = None
                break
        _scan_value(current)

    system_prompt_template = str(persona_data.get("system_prompt_template") or "")
    if system_prompt_template:
        collected.update(_extract_emojis_from_text(system_prompt_template))

    interaction = persona_data.get("interaction_logic")
    if isinstance(interaction, dict):
        interaction_template = str(interaction.get("system_prompt_template") or "")
        if interaction_template:
            collected.update(_extract_emojis_from_text(interaction_template))

    return collected


def get_allowed_emojis(profile_filename: str) -> Optional[set[str]]:
    """获取指定角色允许使用的 emoji 集合。

    返回值语义：
    - ``None``：白名单未启用，或人设未成功加载；不做 emoji 过滤。
    - ``set()``：白名单启用且人设没有声明允许项；过滤全部 emoji。
    """
    if not EMOJI_ALLOWLIST_ENABLED:
        return None

    cache_key = str(profile_filename or "").strip()
    if cache_key in _allowed_emoji_cache:
        return _allowed_emoji_cache[cache_key]

    allowed: set[str] = set()
    persona_loaded = False

    try:
        from core.character.managers.persona_manager import get_persona_manager

        persona_manager = get_persona_manager()
        persona_data = (
            persona_manager.get_persona_by_filename(cache_key)
            if cache_key
            else persona_manager.get_current_persona()
        )
        if isinstance(persona_data, dict) and persona_data:
            persona_loaded = True
            allowed = _collect_allowed_emojis_from_persona(persona_data)
            extends = str(persona_data.get("extends") or "").strip()
            if extends:
                parent_data = persona_manager.get_persona_by_filename(extends)
                if isinstance(parent_data, dict) and parent_data:
                    allowed |= _collect_allowed_emojis_from_persona(parent_data)
    except Exception:
        persona_loaded = False

    resolved = allowed if persona_loaded else None
    _allowed_emoji_cache[cache_key] = resolved
    return resolved


def clear_allowed_emoji_cache() -> None:
    """清除允许 emoji 缓存。"""
    _allowed_emoji_cache.clear()
