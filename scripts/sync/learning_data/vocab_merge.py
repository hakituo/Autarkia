"""背单词进度与每日生词文件的并集合并。

两个系统在两次同步之间各自背单词时，``vocab_progress.json`` 都会变化。
它是一份 ``{单词: 调度状态}`` 的映射，整文件按 mtime 取胜会直接丢掉另一
端新学的词和复习历史（2026-10-25 实测：Linux 侧 10-23～10-24 的进度没有
任何一条出现在 Windows 的进度里，新词因此被重新当成「从未学过」）。

因此改为按单词取并集：

- 同一单词保留「最近一次复习」的那份调度字段（reps / interval / fsrs_*）；
- ``history`` 按 ``(timestamp, quality, source)`` 去重后合并，两端的复习
  事件都保留，避免「今日已背」与记忆曲线统计少算一边；
- 任一侧解析失败（JSON 损坏 / 非 UTF-8）时返回 ``None``，调用方不落盘，
  保留两端原文件；合并结果会同时写回双方，拿能读的一侧去覆盖损坏文件
  会让还能人工抢救的内容直接消失。

每日生词日志（``daily/YYYY/MM/DD.txt``，格式 ``单词[ 次数]``）同样按单词
取并集：同一单词取较大的次数（与 ``UnfamiliarWordBook`` 去重时的「取较大
值」一致，且对已合并结果再合并一次不变），空占位文件绝不会覆盖另一端的
实际记录。
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

#: 取不到 history 时用来判断新旧的时间字段。只认「末次复习」，
#: 不能拿 next_review / fsrs_due 当复习时间：到期日越远不代表刚复习过。
_RECENCY_FIELD = "fsrs_last_review"


def union_vocab_progress(left: bytes, right: bytes) -> Optional[bytes]:
    """合并两份 ``vocab_progress.json``；任一侧解析不了时返回 ``None``。"""
    left_data = _load_progress(left)
    right_data = _load_progress(right)
    if left_data is None or right_data is None:
        # 合并结果会写回两端，用「能读的一侧」覆盖损坏文件会丢掉可人工抢救的内容
        return None

    merged: Dict[str, Any] = {}
    for word in sorted(set(left_data) | set(right_data)):
        mine = left_data.get(word)
        theirs = right_data.get(word)
        if mine is None:
            merged[word] = theirs
        elif theirs is None:
            merged[word] = mine
        else:
            merged[word] = _merge_word_entry(mine, theirs)
    return _dump_progress(merged)


def union_word_list(left: bytes, right: bytes) -> Optional[bytes]:
    """合并两份生词日志（``单词[ 次数]`` 每行一条），按单词取较大次数。

    任一侧不是合法 UTF-8 时返回 ``None``：用替换字符解码会把单词键改坏，
    且结果会覆盖原文件，宁可跳过本次合并。
    """
    entries: Dict[str, Tuple[str, int]] = {}
    for raw in (left, right):
        for line in _iter_lines(raw):
            if line is None:
                return None
            parsed = _parse_word_line(line)
            if parsed is None:
                continue
            word, count = parsed
            key = word.lower()
            current = entries.get(key)
            if current is None:
                entries[key] = (word, count)
                continue
            best = _better_word_entry(current, (word, count))
            entries[key] = best
    if not entries:
        return b""
    lines: List[str] = []
    for key in sorted(entries):
        word, count = entries[key]
        lines.append(f"{word} {count}" if count > 0 else word)
    return ("\n".join(lines) + "\n").encode("utf-8")


def _better_word_entry(
    current: Tuple[str, int], candidate: Tuple[str, int]
) -> Tuple[str, int]:
    """同词取较大次数；次数相同时取字典序更小的写法，保证结果与顺序无关。"""
    if candidate[1] > current[1]:
        return candidate
    if candidate[1] < current[1]:
        return current
    return min(current, candidate)


def _merge_word_entry(mine: Any, theirs: Any) -> Any:
    """合并同一个单词的两份调度状态。"""
    if not isinstance(mine, dict) or not isinstance(theirs, dict):
        # 结构异常时只做确定性选择，不尝试解释未知格式
        return mine if _canonical(mine) >= _canonical(theirs) else theirs

    latest = mine if _entry_rank(mine) >= _entry_rank(theirs) else theirs
    merged = dict(latest)
    history = _union_history(mine.get("history"), theirs.get("history"))
    if history:
        merged["history"] = history
    return merged


def _entry_rank(entry: dict) -> Tuple[float, int, str]:
    """调度状态的新旧排序键：末次复习时间 > history 条数 > 规范化内容。"""
    history = entry.get("history")
    items = history if isinstance(history, list) else []
    stamps = [_item_timestamp(item) for item in items]
    latest = max(stamps) if stamps else 0.0
    if latest <= 0:
        value = entry.get(_RECENCY_FIELD)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            latest = float(value)
    return latest, len(items), _canonical(entry)


def _union_history(left: Any, right: Any) -> List[dict]:
    """history 并集：同一复习事件只保留一条，按时间升序排列。"""
    winners: Dict[Tuple[Any, ...], dict] = {}
    for side in (left, right):
        if not isinstance(side, list):
            continue
        for item in side:
            if not isinstance(item, dict):
                continue
            key = _history_identity(item)
            current = winners.get(key)
            # 同一身份的记录可能夹带不同附加字段，按规范化内容取较大者，
            # 保证保留哪一条与输入顺序无关
            if current is None or _canonical(item) > _canonical(current):
                winners[key] = item
    if not winners:
        return []
    return [
        item
        for _, item in sorted(
            (_history_order(item), item) for item in winners.values()
        )
    ]


def _history_identity(item: dict) -> Tuple[Any, ...]:
    """一次复习的身份：时间 + 评分 + 来源；缺时间时退回整条内容。"""
    timestamp = _item_timestamp(item)
    if timestamp <= 0:
        return ("raw", _canonical(item))
    return (timestamp, item.get("quality"), str(item.get("source") or ""))


def _history_order(item: dict) -> Tuple[float, str]:
    return _item_timestamp(item), _canonical(item)


def _item_timestamp(item: dict) -> float:
    value = item.get("timestamp")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return 0.0


def _load_progress(raw: bytes) -> Optional[Dict[str, Any]]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _dump_progress(payload: Dict[str, Any]) -> bytes:
    """统一排序与换行，保证两端合并结果字节一致、对已合并结果幂等。"""
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    return (text + "\n").encode("utf-8")


def _canonical(payload: Any) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(payload)


def _iter_lines(raw: bytes) -> Iterable[Optional[str]]:
    """按行产出文本；解码失败时产出 ``None``（调用方据此跳过本次合并）。"""
    if not raw:
        return []
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return [None]
    return [line.strip() for line in text.splitlines() if line.strip()]


def _parse_word_line(line: str) -> Optional[Tuple[str, int]]:
    """解析 ``单词`` / ``单词 次数`` / 注释；与 UnfamiliarWordBook 口径一致。"""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    parts = stripped.rsplit(None, 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0], int(parts[1])
    return parts[0], 0
