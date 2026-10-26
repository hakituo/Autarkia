"""记忆蒸馏的角色视角：认出这段记忆属于谁的对话，并按那个人设写梗概。

记忆是角色自己的，蒸馏出来的梗概要用第一人称写，而不是「用户表示……助手回复……」
这种旁观者纪要。身份只从这段记忆自己的归属里认：

1. 会话 ID 自己写了角色（``shared__scope__ling``、``private_xx__persona__yeye``）
   —— 这就是「和谁的对话」，认到名字直接取该人设；
2. 认到名字但人设库里没有这个角色（``__scope__chiba`` 这类历史 scope）
   —— 回中立模板，不借别人的口吻；
3. 会话 ID 没写角色（早期 ``private_123456789``）—— 退到记忆落盘目录
   ``<scope>_data``，再退到规范化后的 ``storage_scope``。

最后一级 ``storage_scope`` 兜底是**有意保留**的（2026-10-25 裁定，见
``.trae/specs/weighted_memory_v3_spec.md`` §0.2 D2）：管理器初始化时已按
落盘目录算出 scope，前三级都认不出时它是唯一还能用的归属信号；移除会让这批
历史会话集体退回默认角色目录（跨角色串味）。因此实现与文档统一描述为
"四级解析、storage_scope 为末级兜底"，不再写成"已移除兜底"。

夜间任务是并发跑多个 scope，没有「当前对话/当前人设」这回事，所以不能读
活跃 persona：那会把 A 的记忆写成 B 的口吻。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from core.services.dual_role.personas import get_persona, resolve_role_id
from core.utils.config_accessor import get_user_display_name
from core.utils.data_paths import get_memories_dir_for_conversation
from core.utils.data.scope_registry import matched_persona_scope
from core.utils.logger import get_module_logger

logger = get_module_logger(__name__, "nightly_processor.log")

Perspective = Dict[str, str]
_CONVERSATION_MARKERS = ("__scope__", "__persona__", "__circle__")
_USER_ROLES = frozenset({"user", "human"})
_ASSISTANT_ROLES = frozenset({"assistant", "ai", "bot"})


def resolve_distillation_perspective(manager: Any) -> Perspective:
    """解析这条记忆的归属角色视角；认不出角色时返回空字典。"""
    conversation_id = str(getattr(manager, "user_id", "") or "").strip().lower()
    if conversation_id:
        declared = _declared_scope(conversation_id)
        if declared:
            return _perspective_from_scope(declared)
        strict = matched_persona_scope(conversation_id)
        if strict:
            return _perspective_from_scope(strict)
        directory_scope = _memory_directory_scope(conversation_id)
        if directory_scope:
            return _perspective_from_scope(directory_scope)
    return _perspective_from_scope(str(getattr(manager, "storage_scope", "") or ""))


def perspective_for_scope(scope: str) -> Perspective:
    """按记忆 scope 直接取视角（按段提取时 scope 已由输入管线认定）；认不出返回空字典。"""
    return _perspective_from_scope(str(scope or "").strip().lower())


def _declared_scope(conversation_id: str) -> str:
    """取会话 ID 里显式写出的角色 scope（``__scope__x`` / ``__persona__x``）。"""
    for marker in _CONVERSATION_MARKERS:
        if marker in conversation_id:
            return conversation_id.rsplit(marker, 1)[-1].strip("_").split("__", 1)[0]
    return ""


def _memory_directory_scope(conversation_id: str) -> str:
    """由记忆落盘目录名 ``<scope>_data`` 反推 scope。"""
    try:
        memory_dir = Path(get_memories_dir_for_conversation(conversation_id))
    except Exception as exc:
        logger.debug("解析记忆目录 scope 失败: %s", exc)
        return ""
    owner_dir = memory_dir.name
    if not owner_dir.endswith("_data"):
        owner_dir = memory_dir.parent.name
    if not owner_dir.endswith("_data"):
        return ""
    return owner_dir[: -len("_data")]


def _perspective_from_scope(scope: str) -> Perspective:
    role_id = resolve_role_id(scope) if scope else ""
    profile = get_persona(role_id) if role_id else None
    if profile is None:
        return {}
    return {
        "role_id": role_id,
        "role_name": profile.cn_name,
        "user_name": _resolve_user_name(),
        "role_profile": _build_profile_line(profile),
    }


def _resolve_user_name() -> str:
    try:
        return get_user_display_name()
    except Exception as exc:
        logger.warning("读取用户显示名失败，蒸馏视角退回中性称呼: %s", exc)
        return "用户"


def _build_profile_line(profile: Any) -> str:
    """把画像拼成一句给模型看的自述，缺字段时退回默认描述。"""
    parts: List[str] = []
    personality = str(getattr(profile, "personality", "") or "").strip()
    if personality:
        parts.append(f"你的性格是{personality}")
    style = str(getattr(profile, "speaking_style", "") or "").strip()
    if style:
        parts.append(f"你说话是{style}")
    return "".join(parts) or "你按自己平时的语气说话。"


def speaker_label(role: str, perspective: Perspective) -> str:
    """把记忆里的 user/assistant 换成具体人名，方便模型写第一人称。"""
    raw = str(role or "").strip()
    if not perspective:
        return raw or "unknown"
    lowered = raw.lower()
    if lowered in _USER_ROLES:
        return perspective["user_name"]
    if lowered in _ASSISTANT_ROLES:
        return perspective["role_name"]
    return raw or "unknown"


def format_speaker_item(
    role: str,
    content: str,
    perspective: Perspective,
) -> str:
    """单条蒸馏的【说话者】+ 正文。"""
    return f"【说话者】{speaker_label(role, perspective)}\n{content}"


def build_single_distillation_prompt(
    content: str,
    perspective: Perspective,
) -> List[Dict[str, str]]:
    """单条蒸馏 prompt：system 随 scope 固定，user 只放动态内容。"""
    from core.agents.chat_agent_components.persona_system.prompt.service_prompts import (
        MEMORY_DISTILLATION_PERSONA_SYSTEM_PROMPT,
        MEMORY_DISTILLATION_SYSTEM_PROMPT,
        MEMORY_DISTILLATION_USER_TEMPLATE,
    )

    system = (
        MEMORY_DISTILLATION_PERSONA_SYSTEM_PROMPT.format(**perspective)
        if perspective
        else MEMORY_DISTILLATION_SYSTEM_PROMPT
    )
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": MEMORY_DISTILLATION_USER_TEMPLATE.format(content=content),
        },
    ]


def build_batch_distillation_prompt(
    messages: List[Dict[str, Any]],
    perspective: Perspective,
) -> List[Dict[str, str]]:
    """批量蒸馏 prompt：system 跨批一致，user 带编号条目。"""
    from core.agents.chat_agent_components.persona_system.prompt.service_prompts import (
        MEMORY_DISTILLATION_BATCH_SYSTEM_PROMPT,
        MEMORY_DISTILLATION_BATCH_USER_TEMPLATE,
        MEMORY_DISTILLATION_PERSONA_BATCH_SYSTEM_PROMPT,
    )

    items = "\n\n".join(
        f"【条目{index}】\n"
        + format_speaker_item(
            str(message.get("role") or ""),
            str(message.get("content") or "").strip(),
            perspective,
        )
        for index, message in enumerate(messages, start=1)
    )
    system = (
        MEMORY_DISTILLATION_PERSONA_BATCH_SYSTEM_PROMPT.format(**perspective)
        if perspective
        else MEMORY_DISTILLATION_BATCH_SYSTEM_PROMPT
    )
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": MEMORY_DISTILLATION_BATCH_USER_TEMPLATE.format(
                count=len(messages),
                items=items,
            ),
        },
    ]
