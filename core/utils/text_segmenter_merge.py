"""续接词识别与分段合并：把不自然的断点并回去。

从 ``text_segmenter.py`` 拆出。续接词靠 jieba 词性标注判断，
因此 ``jieba.setLogLevel`` 也在这里设置（门面 import 本模块即生效，与原模块一致）。
"""
from __future__ import annotations

import logging
import re

import jieba
import jieba.posseg as pseg

from core.utils.text_segmenter_rules import (
    CONTINUATION_ADVERBS,
    CONTINUATION_ENDINGS,
    EXPLICIT_SPACE_BOUNDARY_ENDINGS,
    PUNCTUATION_FOR_SPACE_GUARD,
)

jieba.setLogLevel(logging.INFO)


# ==========================================================================
# 续接词识别
# ==========================================================================

def is_continuation_start(text: str) -> bool:
    """使用 jieba 词性标注判断文本是否以续接词开头。

    连词(c)视为续接词；首词以特定副词字根开头也视为续接（如"还有"/v、"再到"/v）。
    跳过前导标点。
    """
    if not text or not text.strip():
        return False

    stripped = text.strip()[:30]
    for word, flag in pseg.cut(stripped):
        if not word.strip():
            continue
        if flag in ("x", "w"):
            continue
        if flag == "c":
            return True
        if any(word.startswith(a) for a in CONTINUATION_ADVERBS):
            return True
        return False

    return False


# ==========================================================================
# 分段合并
# ==========================================================================

def merge_chunks_to_limit(chunks: list[str], max_chunks: int = 7) -> list[str]:
    """合并分段以确保不超过指定数量。

    策略：尽可能按原文的语义边界合并相邻分段，确保最终数量不超过 max_chunks。
    """
    if len(chunks) <= max_chunks:
        return chunks

    result = list(chunks)
    needed_merges = len(result) - max_chunks

    for _ in range(needed_merges):
        min_len = float("inf")
        merge_idx = -1
        for i in range(len(result) - 1):
            combined_len = len(result[i]) + len(result[i + 1])
            if combined_len < min_len:
                min_len = combined_len
                merge_idx = i
        if merge_idx < 0:
            break
        result[merge_idx] = result[merge_idx] + result[merge_idx + 1]
        result.pop(merge_idx + 1)

    return result


def merge_continuation_chunks(
    chunks: list[str], max_merge_len: int = 300, min_split_len: int = 40
) -> list[str]:
    """合并因续接词或未完标点而不自然断开的分段。

    规则：
    1. 如果下一个分段以续接词（jieba 词性标注识别）开头，且前一个分段较短（< min_split_len），
       说明断点不自然，合并到前一个分段
    2. 如果前一个分段以未完标点（如冒号、破折号）结尾，合并下一个分段
    3. 合并后的分段不超过 max_merge_len
    """
    if len(chunks) <= 1:
        return chunks

    result = [chunks[0]]
    for i in range(1, len(chunks)):
        prev = result[-1]
        curr = chunks[i]
        curr_stripped = curr.strip()
        prev_stripped = prev.strip()

        should_merge = False

        if is_continuation_start(curr_stripped):
            prev_ends_with_sent_punct = (
                prev_stripped
                and any(prev_stripped.endswith(ending) for ending in EXPLICIT_SPACE_BOUNDARY_ENDINGS)
            )
            if not prev_ends_with_sent_punct and len(prev_stripped) < min_split_len:
                should_merge = True

        if prev_stripped and any(prev_stripped.endswith(e) for e in CONTINUATION_ENDINGS):
            should_merge = True

        if should_merge and len(prev) + len(curr) <= max_merge_len:
            result[-1] = prev + curr
        else:
            result.append(curr)

    return result


# 汉字与「非汉字词字符」之间的空格是**排版间距**（中英文/公式混排惯例），不是"人工分泡"的分隔符。
# 不先粘掉它们，`还有你昨天睡 4 小时 51 分` 会被切成
# ["还有你昨天睡", "4", "小时", "51", "分"]，`加个乙基就不是 DMT 了` 会切成 3 条。
#
# 字符类不能只写 ASCII：希腊字母 β/χ/θ、上下标 ²、数学运算符 ∑ 都属于"一段文字/公式的一部分"，
# 但不在 [0-9A-Za-z] 里。漏掉它们时 `再往旁边是回归的 β 和 SE` 会被判成人工空格分泡，
# 切成 ["再往旁边是回归的", "β", "和SE"]，β 单独占一条气泡（2026-10-19 截图回归）。
# 区间含义：ASCII → 拉丁扩展 → 希腊 → 西里尔 → 拉丁附加 → 上下标 → 数字形式 → 数学运算符。
# 与安卓 `TextSegmentRules.CJK_ASCII_SPACE_REGEX` 必须逐字一致（verify_text_segmenter_parity.py 比对）。
_CJK_ASCII_SPACE_RE = re.compile(
    r"(?<=[\u4e00-\u9fff])[ \t]+"
    r"(?=[0-9A-Za-z\u00c0-\u024f\u0370-\u03ff\u0400-\u04ff"
    r"\u1e00-\u1eff\u2070-\u209f\u2150-\u218f\u2200-\u22ff])"
    r"|(?<=[0-9A-Za-z\u00c0-\u024f\u0370-\u03ff\u0400-\u04ff"
    r"\u1e00-\u1eff\u2070-\u209f\u2150-\u218f\u2200-\u22ff])[ \t]+"
    r"(?=[\u4e00-\u9fff])"
)


def glue_cjk_ascii_spaces(text: str) -> str:
    """粘掉汉字与「非汉字词字符」之间的空格（中英文/公式混排的排版间距，不是分泡符）。

    只处理**紧邻**汉字与拉丁字母、数字、希腊字母、数学符号等的空格；
    纯汉字之间的空格原样保留——后者才是"人工分泡"。
    """
    return _CJK_ASCII_SPACE_RE.sub("", str(text or ""))


def looks_like_manual_space_split(text: str) -> bool:
    """判断一段无标点文本是否像"人工用空格分泡泡"的短语串。

    判据前先把"汉字↔非汉字词字符"之间的排版空格粘掉（见 [glue_cjk_ascii_spaces]），
    否则中文里夹着英文缩写、数字或公式符号的正常句子会被误判成分泡串。
    """
    normalized = str(text or "").strip()
    if not normalized or "\n" in normalized:
        return False
    if any(ch in PUNCTUATION_FOR_SPACE_GUARD for ch in normalized):
        return False

    glued = glue_cjk_ascii_spaces(normalized)
    parts = [part.strip() for part in re.split(r"\s+", glued) if part.strip()]
    if len(parts) < 3:
        return False

    cjk_chars = re.findall(r"[\u4e00-\u9fff]", glued)
    if len(cjk_chars) < max(6, len(glued.replace(" ", "")) // 3):
        return False

    if any(len(part) > 12 for part in parts):
        return False

    avg_len = sum(len(part) for part in parts) / max(1, len(parts))
    return avg_len <= 8


def merge_space_chunks_to_limit(chunks: list[str], max_chunks: int = 6) -> list[str]:
    """按空格重新合并短语块，避免纯空格断句生成过多气泡。"""
    cleaned = [str(chunk or "").strip() for chunk in chunks if str(chunk or "").strip()]
    if len(cleaned) <= max_chunks:
        return cleaned

    result = list(cleaned)
    while len(result) > max_chunks:
        min_len = float("inf")
        merge_idx = -1
        for i in range(len(result) - 1):
            combined_len = len(result[i]) + len(result[i + 1])
            if combined_len < min_len:
                min_len = combined_len
                merge_idx = i
        if merge_idx < 0:
            break
        result[merge_idx] = f"{result[merge_idx]} {result[merge_idx + 1]}".strip()
        result.pop(merge_idx + 1)
    return result
