# -*- coding: utf-8 -*-
"""聊天记录的「渠道」判定与当前渠道上下文。

同一个 conversation_id 里可能混着多个渠道产生的记录：从 QQ 导出后导入的历史、
QQ bot 的实时对话、App 的实时对话、Obsidian 等。这些记录进模型上下文时要标出
「与当前渠道不同」的那些，否则模型分不清「这条是 QQ 上说的」还是「刚刚在 App
里说的」。

本模块只做两件事：

1. ``resolve_event_channel`` —— 判定单条 chat_history 事件的来源渠道；
2. ``set_current_platform`` / ``current_channel_name`` —— 用 ContextVar 携带
   「本轮请求是在哪个渠道发起的」，与 ``message_branch`` 同一套路，避免把 platform
   逐层透传穿过 stream_chat → context → assembler → 工具执行。
"""

from __future__ import annotations

import re
from contextvars import ContextVar, Token
from typing import Any, Mapping, Optional, Sequence

#: 判定不出来源时的默认渠道：Android / HTTP 路径从不写 platform。
CHANNEL_APP = "app"

#: 车道名里带 QQ 的（如「Ling / QQ对话」「QQ群聊」）一律归 QQ。
#: 车道名由 ``core.utils.data.conversation_labels`` 决定。
_QQ_LANE_RE = re.compile(r"QQ", re.IGNORECASE)

#: 已追加的来源后缀，如「（来自QQ）」。重复 sanitize 时先剥掉再补，保持幂等。
_SOURCE_SUFFIX_RE = re.compile(r"（来自[^（）\n]{1,12}）\s*$")

_DISPLAY_NAMES = {
    CHANNEL_APP: "App",
    "qq": "QQ",
    "qq_official": "QQ",
    "telegram": "Telegram",
    "obsidian": "Obsidian",
}

# 模型自己复述渠道标注时的形态（见 strip_model_channel_marks）：
# 1) 括号包裹：「（来自QQ）」「(来自App)」「（来自 手机）」，句首/句中/句尾都算；
#    只认紧贴「来自」开头的括号，且不跨行、长度受限，避免误删动作描写。
_MODEL_CHANNEL_PAREN_RE = re.compile(r"[（(]\s*来自\s*[^（）()\n]{1,12}?\s*[）)]")

# 2) 句尾裸写：「来自QQ」「来自手机」。渠道名走白名单（与 _DISPLAY_NAMES 同步），
#    且要求后面紧跟空白/句读/结尾，因此「来自QQ音乐」不会命中。
_CHANNEL_LABELS = sorted(
    set(_DISPLAY_NAMES.values()) | {"手机", "手机端", "微信"},
    key=len,
    reverse=True,
)
_MODEL_CHANNEL_BARE_RE = re.compile(
    r"(^|[\s，,。;；!！?？])来自(?:%s)(?=[\s，,。;；!！?？]|$)"
    % "|".join(re.escape(label) for label in _CHANNEL_LABELS),
    re.IGNORECASE,
)


def normalize_platform(value: Any) -> str:
    """把任意 platform 取值归一化为小写字符串；None / 空串 → ``CHANNEL_APP``。"""
    text = str(value or "").strip().lower()
    return text or CHANNEL_APP


def resolve_event_channel(event: Mapping[str, Any]) -> str:
    """判定一条 chat_history 事件的来源渠道。

    判据按可靠性排序，三条缺一不可（已按存量事件逐条核对过覆盖面）：

    1. ``platform``（顶层或 ``metadata`` 内）非空 —— 最权威：历史导入器与 QQ bot
       实时链路都写它；
    2. ``imported`` / ``source_kind`` 非空 —— 导入器写死的导入标记。pairs 导入器
       只写 ``imported`` 不写 platform，只靠第 1 条会漏掉一万多条；
    3. ``readable_title`` 车道名含 QQ —— 兜底覆盖 QQ bot 早期写入的无 platform
       记录（``readable_title`` 在存量事件里 100% 非空，形如「Ling / QQ对话」）。

    三条都不命中即视为 App：App 实时写入的 metadata 里 ``platform`` 是空串。
    """
    metadata = event.get("metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}

    platform = str(
        event.get("platform") or metadata.get("platform") or ""
    ).strip().lower()
    if platform:
        return platform

    imported = event.get("imported") or metadata.get("imported")
    source_kind = str(
        event.get("source_kind") or metadata.get("source_kind") or ""
    ).strip()
    if imported or source_kind:
        return "qq"

    if _QQ_LANE_RE.search(str(event.get("readable_title") or "")):
        return "qq"

    return CHANNEL_APP


def channel_display_name(channel: str) -> str:
    """渠道的展示名，用于「（来自QQ）」「当前渠道：QQ」这类标注。"""
    key = normalize_platform(channel)
    return _DISPLAY_NAMES.get(key, key.capitalize())


def strip_source_suffix(text: str) -> str:
    """剥掉正文末尾已存在的「（来自X）」，保证重复 sanitize 不叠加。"""
    return _SOURCE_SUFFIX_RE.sub("", str(text or "")).rstrip()


def source_suffix(event: Mapping[str, Any], current_channel: Optional[str]) -> str:
    """该事件相对当前渠道应追加的来源后缀；同渠道时返回空串。

    与当前渠道一致就不标 —— App 上看 App 历史保持零噪音，这也是「平时都是 App
    上的就不需要标记」的落点。
    """
    channel = resolve_event_channel(event)
    if channel == normalize_platform(current_channel):
        return ""
    return f"（来自{channel_display_name(channel)}）"


def strip_model_channel_marks(text: str) -> str:
    """剥离模型自己复述出来的渠道标注。

    「（来自QQ）」这类后缀是系统给**历史消息**加的，模型不该自己写出来。
    实际观察里模型会模仿出三种形态，都要剥：

    - 全角括号「（来自QQ）」/ 半角「(来自App)」，可能出现在句首、句中或句尾；
    - 句尾裸写「来自QQ」「来自手机」。

    与 ``strip_source_suffix`` 的分工：后者只处理我们自己追加的全角结尾后缀
    （历史清洗幂等用），这里面向模型输出，形态更宽，但只认「来自 + 渠道」
    这一固定结构且长度受限，不会误伤正文里的「这首歌来自QQ音乐」。
    """
    original = str(text or "")
    cleaned = _MODEL_CHANNEL_PAREN_RE.sub("", original)
    cleaned = _MODEL_CHANNEL_BARE_RE.sub(r"\1", cleaned)
    if cleaned == original:
        return original
    # 剥掉后可能留下多余空白与叠在一起的标点（"晚安。来自App。" → "晚安。。"）
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"([，,。;；!！?？])\1+", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]+([，,。;；!！?？])", r"\1", cleaned)
    return cleaned.strip()


def cross_channel_labels(
    events: Sequence[Mapping[str, Any]],
    current_channel: Optional[str] = None,
) -> list[str]:
    """事件序列里出现的、与当前渠道不同的渠道展示名（去重、按首次出现排序）。"""
    current = normalize_platform(current_channel)
    labels: list[str] = []
    for event in events or ():
        if not isinstance(event, Mapping):
            continue
        channel = resolve_event_channel(event)
        if channel == current:
            continue
        label = channel_display_name(channel)
        if label not in labels:
            labels.append(label)
    return labels


_current_platform: ContextVar[str] = ContextVar("xiaoyou_current_platform", default="")


def set_current_platform(value: Any) -> Token:
    """绑定本轮请求的渠道；由 ``ChatAgent.stream_chat`` 在生成前设置。"""
    return _current_platform.set(normalize_platform(value))


def reset_current_platform(token: Token) -> None:
    _current_platform.reset(token)


def get_current_platform() -> str:
    """读取本轮请求的渠道；未绑定时回落到 App。"""
    return normalize_platform(_current_platform.get())


def current_channel_name() -> str:
    """本轮请求渠道的展示名，供 prompt 注入「当前渠道：X」。"""
    return channel_display_name(get_current_platform())
