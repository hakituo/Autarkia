"""词汇学习洞察层：今日已背单词、当前词书进度、已学单词列表。

分工：quiz 负责「今天要背哪些词」，stats 负责宏观统计与完成态，
本模块负责用户视角的「我今天背了什么、这本书背到哪了」。
数据全部来自 ``progress`` 的 history 与当前词书，不额外落盘。
"""

from __future__ import annotations

import datetime
import os
from typing import Any, Dict, List, Optional

from core.utils.time_utils import get_current_time, ts_to_str

from core.utils.logger import get_logger

from .fsrs_scheduler import event_is_lapse
from .loader import MASTER_FILE

logger = get_logger("VocabInsights")

# 与 stats.get_stats 的「已掌握」口径保持一致：间隔超过 21 天
MASTERED_INTERVAL_DAYS = 21
_MAX_PAGE_SIZE = 200


def _review_events(data: Any) -> List[Dict[str, Any]]:
    """抽取带有效时间戳与评分的复习事件，按时间升序；旧格式条目直接跳过。"""
    events: List[Dict[str, Any]] = []
    if not isinstance(data, dict):
        return events
    history = data.get("history")
    if not isinstance(history, list):
        return events
    for entry in history:
        if not isinstance(entry, dict):
            continue
        try:
            timestamp = float(entry.get("timestamp", 0) or 0)
        except (TypeError, ValueError):
            continue
        if timestamp <= 0 or entry.get("quality") is None:
            continue
        try:
            quality = int(entry.get("quality"))
        except (TypeError, ValueError):
            continue
        events.append({**entry, "timestamp": timestamp, "quality": quality})
    events.sort(key=lambda item: item["timestamp"])
    return events


def _translation_text(info: Optional[Dict[str, Any]]) -> str:
    """把词书中的 translations 拼成一行展示文案。"""
    if not isinstance(info, dict):
        return ""
    parts: List[str] = []
    for item in info.get("translations") or []:
        if not isinstance(item, dict):
            continue
        translation = str(item.get("translation") or "").strip()
        if not translation:
            continue
        pos = str(item.get("type") or "").strip()
        parts.append(f"{pos}. {translation}" if pos else translation)
    return "; ".join(parts)


def _word_status(data: Dict[str, Any], now: float) -> str:
    """单词掌握状态：mastered / learning / due。"""
    try:
        interval = float(data.get("interval", 0) or 0)
    except (TypeError, ValueError):
        interval = 0.0
    if interval > MASTERED_INTERVAL_DAYS:
        return "mastered"
    due_ts = data.get("fsrs_due") or data.get("next_review", 0)
    try:
        due_ts = float(due_ts or 0)
    except (TypeError, ValueError):
        due_ts = 0.0
    if due_ts and due_ts <= now:
        return "due"
    return "learning"


def _day_window(day: datetime.datetime) -> tuple[float, float]:
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.timestamp(), (start + datetime.timedelta(days=1)).timestamp()


def get_today_words(store, date_str: str = "") -> Dict[str, Any]:
    """返回指定日期（默认今天）实际背过的单词明细。

    每个词的 status 按「今天之前是否已有评分事件」判定 new / review；
    同一词当天被 Again 重排多次只占一条，reviews 记录评分次数，
    last_quality 取当天最后一次评分。
    """
    store._ensure_loaded()
    day = get_current_time()
    if date_str:
        try:
            parsed = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            # 用配置时区重建，避免 naive datetime 按服务器本地时区解释
            day = day.replace(
                year=parsed.year,
                month=parsed.month,
                day=parsed.day,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
        except ValueError:
            logger.warning("today-words 日期格式非法，回退到今天: %s", date_str)
    start, end = _day_window(day)

    words: List[Dict[str, Any]] = []
    for word, data in store.progress.items():
        events = _review_events(data)
        today_events = [e for e in events if start <= e["timestamp"] < end]
        if not today_events:
            continue
        info = store.get_word_info(word)
        last_event = today_events[-1]
        is_new = len(today_events) == len(events)
        words.append(
            {
                "word": word,
                "translation": _translation_text(info),
                "status": "new" if is_new else "review",
                "reviews": len(today_events),
                "last_quality": int(last_event["quality"]),
                "again_count": sum(
                    1 for event in today_events if event_is_lapse(event)
                ),
                "last_review_ts": last_event["timestamp"],
                "last_review_at": ts_to_str(last_event["timestamp"], "%H:%M"),
            }
        )

    words.sort(key=lambda item: item["last_review_ts"], reverse=True)
    again_words = sum(1 for item in words if int(item["last_quality"]) <= 1)
    return {
        "date": day.strftime("%Y-%m-%d"),
        "total": len(words),
        "new_words": sum(1 for item in words if item["status"] == "new"),
        "review_words": sum(1 for item in words if item["status"] == "review"),
        "review_events": sum(int(item["reviews"]) for item in words),
        "again_words": again_words,
        "known_words": len(words) - again_words,
        "words": words,
    }


def get_book_progress(store) -> Dict[str, Any]:
    """当前词书的完成度：已学 / 未学 / 掌握 / 待复习。

    ``progress`` 是按单词全局记录的，可能包含其它词书或手动记录的词；
    这里只统计当前词书里出现过的词，避免把别的书算进本书进度。
    """
    store._ensure_loaded()
    now = get_current_time().timestamp()

    book_words = {
        str(entry.get("word") or "").strip().lower()
        for entry in store.dictionary
        if isinstance(entry, dict) and str(entry.get("word") or "").strip()
    }
    total = len(book_words)
    learned = mastered = due = 0
    for word, data in store.progress.items():
        if str(word or "").strip().lower() not in book_words:
            continue
        learned += 1
        status = _word_status(data, now)
        if status == "mastered":
            mastered += 1
        if status == "due":
            due += 1

    today = get_today_words(store)
    today_new = today_review = 0
    for item in today["words"]:
        key = str(item.get("word") or "").strip().lower()
        if key not in book_words:
            continue
        if item["status"] == "new":
            today_new += 1
        else:
            today_review += 1

    percent = round(learned * 100.0 / total, 1) if total else 0.0
    return {
        "current_dictionary": os.path.basename(store.dictionary_path),
        "total_words": total,
        "learned_words": learned,
        "remaining_words": max(0, total - learned),
        "mastered_words": mastered,
        "learning_words": max(0, learned - mastered),
        "due_words": due,
        "progress_percent": percent,
        "today_new": today_new,
        "today_review": today_review,
        "available_word_files": _list_word_files(store),
    }


def _list_word_files(store) -> List[str]:
    """可用词书文件名（排除全量释义总表）。"""
    from .stats import LEVEL_ORDER

    try:
        if not os.path.exists(store.words_dir):
            return []
        files = [
            name
            for name in os.listdir(store.words_dir)
            if name.endswith(".json") and name != MASTER_FILE
        ]
    except OSError as exc:
        logger.warning("读取词书列表失败: %s", exc)
        return []
    return [name for name in LEVEL_ORDER if name in files] + sorted(
        name for name in files if name not in LEVEL_ORDER
    )


def get_learned_words(
    store,
    page: int = 1,
    page_size: int = 20,
    status: str = "all",
    scope: str = "book",
) -> Dict[str, Any]:
    """分页返回已学单词，支持按掌握状态过滤。

    Args:
        page: 页码，从 1 开始。
        page_size: 每页数量，最大 200。
        status: all / mastered / learning / due。
        scope: book（只含当前词书）或 all（全部进度）。
    """
    store._ensure_loaded()
    now = get_current_time().timestamp()
    page = max(1, int(page or 1))
    page_size = max(1, min(_MAX_PAGE_SIZE, int(page_size or 20)))
    status = str(status or "all").strip().lower()
    scope = str(scope or "book").strip().lower()

    # scope=book 时先建一次索引，避免对每个已学词线性扫描整本词书
    book_entries: Optional[Dict[str, Dict[str, Any]]] = None
    if scope != "all":
        book_entries = {}
        for entry in store.dictionary:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("word") or "").strip().lower()
            if key:
                book_entries.setdefault(key, entry)

    items: List[Dict[str, Any]] = []
    for word, data in store.progress.items():
        key = str(word or "").strip().lower()
        if book_entries is not None and key not in book_entries:
            continue
        state = _word_status(data, now)
        if status in {"mastered", "learning", "due"} and state != status:
            continue
        events = _review_events(data)
        last_ts = events[-1]["timestamp"] if events else 0.0
        info = (
            book_entries.get(key)
            if book_entries is not None
            else store.get_word_info(word)
        )
        items.append(
            {
                "word": word,
                "translation": _translation_text(info),
                "status": state,
                "reps": int(data.get("reps", 0) or 0),
                "interval_days": int(float(data.get("interval", 0) or 0)),
                "last_review_ts": last_ts,
                "last_review_at": ts_to_str(last_ts, "%Y-%m-%d") if last_ts else "",
            }
        )

    items.sort(key=lambda item: item["last_review_ts"], reverse=True)
    total = len(items)
    offset = (page - 1) * page_size
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_more": offset + page_size < total,
        "words": items[offset : offset + page_size],
    }
