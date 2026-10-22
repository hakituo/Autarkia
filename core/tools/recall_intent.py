# -*- coding: utf-8 -*-
"""回忆提问的意图判定（search_memory / search_chat_history 共用）。

背景：用户问「你还记得这个吗」时只是在**确认**角色记不记得，并没有索取
内容。若工具照常把命中的原始记忆/聊天记录回传给模型，模型容易把材料当
台词，回复「记得，你当时……」整条背出来。

因此工具层在返回前先判定意图：

- 确认型（只问记不记得）：工具仍然检索（用于确认记忆确实存在，防止瞎说
  记得），但只回传存在性信号与一句行为约束，不带任何正文；
- 内容型（问「是什么/后来怎样/讲讲经过」等）：正常返回正文。

判定刻意保守：只有「回忆线索 + 确认句式 + 不含任何索取细节的疑问词」三者
同时成立才收敛，宁可多给内容（模型本来就该会答），也不能误杀真问题。
"""
from __future__ import annotations

# 回忆线索：句子必须落在「回忆往事」的语义里才可能触发收敛
_RECALL_CUES = (
    "还记得",
    "记不记得",
    "还记不记得",
    "忘没忘",
    "没忘",
    "有没有印象",
    "有印象",
    "想得起",
    "想得起来",
    "能想起",
    "记得",
)

# 强确认线索：这些说法本身就是确认语气，不依赖句尾助词
_STRONG_CONFIRM_CUES = (
    "还记得",
    "记不记得",
    "还记不记得",
    "忘没忘",
    "有没有印象",
    "有印象吗",
    "没忘吧",
)

# 句尾确认助词（先剥掉标点/空白再看末字）
_CONFIRM_ENDINGS = frozenset("吗么吧不")

# 索取细节的词：命中任意一个即判定为内容型，绝不收敛
_DETAIL_TOKENS = (
    "什么",
    "怎么",
    "怎样",
    "咋",
    "为什么",
    "为啥",
    "为何",
    "啥",
    "哪里",
    "哪儿",
    "哪个",
    "哪些",
    "谁",
    "几",
    "多少",
    "多久",
    "几点",
    "几号",
    "哪天",
    "如何",
    "咋样",
    "后来",
    "结局",
    "原因",
    "内容",
    "细节",
    "经过",
    "详情",
    "具体",
    "讲讲",
    "说说",
    "讲一下",
    "说一下",
    "讲下",
    "说下",
    "描述",
    "讲讲看",
)

_TRAILING_PUNCT = "。.,!?！？~～… \t\r\n"


def is_confirmation_only_recall(message: str) -> bool:
    """判断用户这句话是否只是「确认你记不记得」，而非索取往事内容。

    保守三条件：有回忆线索、无索取细节词、句式是确认（强线索或句尾助词）。
    """
    text = (message or "").strip()
    if not text:
        return False

    if not any(cue in text for cue in _RECALL_CUES):
        return False

    if any(token in text for token in _DETAIL_TOKENS):
        return False

    if any(cue in text for cue in _STRONG_CONFIRM_CUES):
        return True

    return text.rstrip(_TRAILING_PUNCT)[-1:] in _CONFIRM_ENDINGS


def build_confirmation_reply(*, memory_count: int, chat_count: int) -> str:
    """构造确认型提问的工具返回：只给数量与行为约束，不含任何记忆正文。"""
    total = memory_count + chat_count
    return (
        f"已核对：找到 {total} 条相关过往记录（记忆 {memory_count} 条、"
        f"聊天 {chat_count} 条），内容已隐藏。\n"
        "对方这句话只是在确认你记不记得，并没有问具体内容。"
        "用自己的话简短承认记得即可（例如「嗯，记得，怎么了？」），"
        "不要说出任何记录里的细节，等对方继续问。"
    )


# 内容型返回的统一后缀：材料是背景不是台词，避免逐字照念
CONTENT_USAGE_NOTE = "（以上是给你回忆用的背景材料，不是台词；用自己的话讲，不要照念原文。）"
