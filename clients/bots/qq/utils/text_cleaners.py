"""QQ 消息文本清洗：统一入口 [clean_qq_text] 与配套规则。

规则分两层：

- **通用规则**（时间戳剥离、句尾尾随标点清理、渠道标注剥离、工具标记剥离）实现在
  `core.utils.text_segmenter` / `core.utils.data.chat_channel` / `core.llm.openai_compat.dsml_parser`，
  安卓端用同一份规则的 Kotlin 实现，本模块直接复用；
- **QQ 特有规则**（markdown / think 剥离、开头动作描写、emoji 前置句号、省略号与空白口径）
  只在本模块实现。

历史背景（2026-10-16 合并）：原先这是两条独立链路——emoji 过滤链在
`clients/bots/qq/emoji_filter.py`（emoji 前置句号 + 省略号删除 + 空白规范化），
文本剥离链在本模块（markdown / think / 时间戳 / 尾随标点）。调用方各自按需串联，
容易漏项、口径也容易漂移。现在合并为单点真源：出站与落库场景统一走 [clean_qq_text]，
emoji 白名单数据源拆到 `emoji_allowlist.py`。
"""

from __future__ import annotations

import re

from clients.bots.qq.utils.emoji_allowlist import (
    EMOJI_ALLOWLIST_ENABLED,
    _allowed_emoji_cache,
    _collect_allowed_emojis_from_persona,
    _extract_emojis_from_text,
    _is_emoji_char,
    clear_allowed_emoji_cache,
    get_allowed_emojis,
)
from core.utils.text_segmenter import (
    AI_TIMESTAMP_PATTERN as _AI_TS_PATTERN,
)
from core.utils.text_segmenter import (
    TRAILING_PUNCT_CHARS as _TRAILING_PUNCT_CHARS,
)
from core.utils.text_segmenter import (
    strip_ai_timestamp,
)
from core.utils.text_segmenter import (
    strip_trailing_punctuation as _strip_trailing_periods_for_qq,
)
# 渠道标注「（来自QQ）」是系统给历史消息加的，模型自己复述出来要剥掉。
# 与时间戳剥离同属「所有端都需要的通用规则」，实现在 core，这里直接复用。
from core.utils.data.chat_channel import (
    strip_model_channel_marks,
)
# 残留的工具调用标记（DSML token 及漂移形态）同为所有端通用规则，实现在 core，
# 这里直接复用：模型偶尔把内部工具调用 token 当正文吐出来，输出侧统一兜底。
from core.llm.openai_compat.dsml_parser import (
    strip_tool_mark_residue,
)

__all__ = [
    # 统一入口
    "clean_qq_text",
    # 通用规则（兼容旧导入路径）
    "_AI_TS_PATTERN",
    "_TRAILING_PUNCT_CHARS",
    "strip_ai_timestamp",
    "strip_model_channel_marks",
    "strip_tool_mark_residue",
    # markdown / think / 动作描写
    "_strip_action_descriptions",
    "_strip_markdown_for_qq",
    "_strip_think_for_qq",
    "_strip_trailing_periods_for_qq",
    # emoji 白名单（数据源在 emoji_allowlist.py，这里 re-export 保持旧导入路径可用）
    "EMOJI_ALLOWLIST_ENABLED",
    "_allowed_emoji_cache",
    "_collect_allowed_emojis_from_persona",
    "_extract_emojis_from_text",
    "_is_emoji_char",
    "clear_allowed_emoji_cache",
    "get_allowed_emojis",
]


def _remove_period_before_emoji(text: str) -> str:
    """删除紧邻 emoji 之前的中英文句号，保留原有空格。

    只处理句号 `。` / `.`：省略号 `…` 是情绪表达的一部分，不再删除
    （旧实现会连省略号一起吃掉，属于过度清洗）。
    """
    result: list[str] = []
    for ch in text:
        if _is_emoji_char(ch):
            trailing_spaces: list[str] = []
            while result and result[-1].isspace():
                trailing_spaces.append(result.pop())
            if result and result[-1] in {"。", "."}:
                result.pop()
            result.extend(reversed(trailing_spaces))
        result.append(ch)
    return "".join(result)


def _filter_emoji_by_allowlist(text: str, profile_filename: str) -> str:
    """按人设白名单过滤 emoji；白名单未启用（或人设加载失败）时原样返回。

    白名单启用时仅保留人设声明过的 emoji；`\\ufe0f`（emoji 变体选择符）只在
    它修饰的 emoji 被保留时才跟着保留。
    """
    allowed = get_allowed_emojis(profile_filename)
    if allowed is None:
        return text

    result: list[str] = []
    previous_emoji_kept = False
    for ch in text:
        if _is_emoji_char(ch):
            previous_emoji_kept = ch in allowed
            if previous_emoji_kept:
                result.append(ch)
        elif ch == "\ufe0f":
            if previous_emoji_kept:
                result.append(ch)
        else:
            previous_emoji_kept = False
            result.append(ch)
    return "".join(result)


def _normalize_whitespace(text: str, preserve_paragraphs: bool) -> str:
    """统一空白。

    - 默认（QQ 发送口径）：把 2 个以上的空白（含空行）压成一个空格，保持单行紧凑。
    - `preserve_paragraphs=True`（历史落库口径）：保留空行结构，只压掉行内多余空白与
      3 个以上连续换行。模型是按**空行**给自己的回复分句的，压平后它回看历史时只能看到
      一整行空格分隔的文本，反过来强化了"用空格分句"的写法——那正是客户端断句被切碎的
      上游诱因，所以历史侧必须留结构。
    """
    if not preserve_paragraphs:
        return re.sub(r"\s{2,}", " ", text).strip()
    cleaned = re.sub(r"[^\S\n]{2,}", " ", text)  # 2+ 非换行空白 → 单空格
    cleaned = re.sub(r"[^\S\n]*\n[^\S\n]*", "\n", cleaned)  # 行首尾空白
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)  # 3+ 换行 → 一个空行
    return cleaned.strip()


def _strip_markdown_for_qq(text: str) -> str:
    """去除 QQ 消息中的 Markdown 格式标记。

    不在 [clean_qq_text] 里无条件执行：QQ 的 markdown 剥离有"CQ 码不剥"的条件
    （见 `transport.send_message`），断句侧则作为 `preprocess` 注入。
    """
    text = str(text or "")
    # 先处理三反引号代码块（可能跨行），再处理单反引号
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`([^`]+)`', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'\*(.+?)\*', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'__(.+?)__', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'_(.+?)_', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'~~(.+?)~~', r'\1', text, flags=re.DOTALL)
    return text.strip()


# 部分模型把推理写成段落而不是标签，例如：
# > **Thinking Process:** ... 或 思考过程：...
# 这类内容对用户没有意义，发送前需要连同其后的分隔线一起去掉。
# 只在行首（允许 "> " 引用前缀和 ** 加粗）识别推理段，
# 避免把正文里出现的"思考过程"当作推理块整段删掉。
_THINKING_BLOCK_RE = re.compile(
    r"^[ \t]*(?:>[ \t]*)?(?:\*\*)?(?:Thinking Process|思考过程)[ \t]*[:：]?[ \t]*(?:\*\*)?"
    r".*?(?=\n[ \t]*\n|\Z)",
    re.DOTALL | re.IGNORECASE | re.MULTILINE,
)

# 推理块之后常残留一条 Markdown 分隔线（---）
_LEADING_SEPARATOR_RE = re.compile(r"^(?:[ \t]*-{3,}[ \t]*(?:\r?\n)?)+")


def _strip_think_for_qq(text: str) -> str:
    """去除 QQ 消息中的思考过程（<think>、[THINK_STORE:...] 与 Thinking Process 段落）。"""
    text = str(text or "")
    # 兼容 <think>、<think/> 以及 </think/> 这类自闭合写法
    text = re.sub(r'<think[^>]*>.*?</think\s*/?>', '', text, flags=re.DOTALL)
    text = re.sub(r'\[THINK_STORE:[^\]]*\]', '', text)
    text = _THINKING_BLOCK_RE.sub('', text).strip()
    text = _LEADING_SEPARATOR_RE.sub('', text)
    return text.strip()


def _strip_action_descriptions(text: str) -> str:
    """去除文本开头的动作描写（圆括号包裹的内容），保留句子中间的括号内容。"""
    text = str(text or "")
    text = re.sub(r'^[（(][^）)]{1,80}[）)]\s*', '', text)
    return text.strip()


def clean_qq_text(
    text: str,
    profile_filename: str = "",
    *,
    preserve_paragraphs: bool = False,
    collapse_whitespace: bool = True,
) -> str:
    """QQ 文本统一清洗入口（发送、历史落库、存量清洗共用同一条链）。

    固定顺序（每一步都幂等，重复调用不会二次损伤文本）：

    1. 推理块剥离：`<think>` / `[THINK_STORE:...]` / `Thinking Process` 段落
    2. 时间戳剥离：模型模仿历史格式输出的 `[09-11 23:40]`
    3. 渠道标注剥离：模型复述的「（来自QQ）」「来自App」
    4. 工具调用标记残留剥离：DSML token 及其漂移形态
    5. emoji 前紧邻句号删除：`知道了。🖤` -> `知道了🖤`
    6. emoji 白名单过滤（[EMOJI_ALLOWLIST_ENABLED] 关闭时全部保留）
    7. 空白规范化（`collapse_whitespace=False` 时跳过）

    **省略号一律保留**：中文 `…` / `……` 与英文 `...` / `....` 都不删，句首、
    句中、句尾任意位置都算（旧实现用一条全局正则把省略号全部删掉，句首的
    `……嗯，我知道了` 会变成 `嗯，我知道了`，属于过度清洗）。

    不在这里做的事（都有额外条件，留在各自调用点）：

    - markdown 剥离：`_strip_markdown_for_qq` 由断句预处理与 transport 按
      「消息里有没有 CQ 码」条件调用；
    - 句尾尾随标点清理：core 的 `strip_trailing_punctuation`，同样带 CQ 码条件；
    - 反应延迟标签 `[DELAY:2s]`：必须在气泡发送前由
      `extract_leading_reaction_delay` 提取，过早剥离会让延迟失效。

    Args:
        text: 待清洗文本。
        profile_filename: 人设文件名，用于 emoji 白名单查询（白名单关闭时不生效）。
        preserve_paragraphs: 历史落库口径——保留空行结构。模型按空行分句，
            压平后它回看历史只能看到一整行空格分隔的文本，会反过来强化
            "用空格分句"的写法，而那正是客户端断句被切碎的上游诱因。
        collapse_whitespace: 是否执行空白规范化。transport 最终防线传 False：
            命令回复等旁路文本可能带多行结构，不该在最后一步被压平。
    """
    cleaned = _strip_think_for_qq(text)
    cleaned = strip_ai_timestamp(cleaned)
    cleaned = strip_model_channel_marks(cleaned)
    cleaned = strip_tool_mark_residue(cleaned)
    if not cleaned:
        return cleaned

    cleaned = _remove_period_before_emoji(cleaned)
    cleaned = _filter_emoji_by_allowlist(cleaned, profile_filename)
    if collapse_whitespace:
        cleaned = _normalize_whitespace(cleaned, preserve_paragraphs)
    return cleaned
