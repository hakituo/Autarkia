"""文本类文件的并集合并：保留信息量更大的一份。

月度蒸馏记忆（``core/character/configs/extra/<年>/<月>/distilled_profile.md``）
两端各自生成，整文件「谁新用谁」会把另一端的成果冲掉；而两端都是同一批记忆的
LLM 蒸馏，内容高度重叠，直接拼接又会让文件无限膨胀。这里按「非空优先、
信息量大的优先」取一份：

- 一侧为空（或只有空白）时取另一侧，绝不让空壳覆盖实质内容；
- 两侧都有内容时取字符数更多的一份（信息量更大）；
- 长度相同时取字典序较大的一份，因此结果与合并顺序无关、对已合并结果幂等。
"""

from __future__ import annotations

from typing import Tuple


def union_text_richer(left: bytes, right: bytes) -> bytes:
    """返回信息量更大的一份；两侧都为空时返回其中一侧（内容等价于空）。"""
    if not left.strip():
        return right
    if not right.strip():
        return left
    return left if _rank(left) >= _rank(right) else right


def _rank(payload: bytes) -> Tuple[int, bytes]:
    """排序键：先比有效字符数，再比原始字节，保证可交换且幂等。"""
    return (len(payload.strip()), payload)
