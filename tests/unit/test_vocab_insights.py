"""词汇学习洞察回归：今日已背 / 词书进度 / 已学单词。"""

from __future__ import annotations

import json

from core.utils.time_utils import get_current_time

from core.tools.study.english import insights
from core.tools.study.english.loader import VocabDataStore


def _build_store(tmp_path, dictionary, progress):
    """构造隔离的 store，避免读取仓库真实词书与全量释义表。"""
    words_path = tmp_path / "Words.json"
    words_path.write_text(json.dumps(dictionary, ensure_ascii=False), encoding="utf-8")
    progress_path = tmp_path / "vocab_progress.json"
    progress_path.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")

    store = VocabDataStore(dictionary_path=str(words_path), progress_path=str(progress_path))
    # 不加载仓库里的真实例句与全量词书，保证测试只依赖入参
    store.sentence_path = None
    store.master_path = str(tmp_path / "no-master.json")
    store._ensure_loaded()
    return store


def _word(word: str) -> dict:
    return {
        "word": word,
        "translations": [{"type": "n.", "translation": f"释义 {word}"}],
    }


def _fixture_progress(now: float, today_start: float) -> dict:
    return {
        # 今天首次学的新词
        "alpha": {
            "interval": 1,
            "reps": 1,
            "next_review": now + 86400,
            "history": [{"timestamp": today_start + 60, "quality": 3}],
        },
        # 已掌握词，今天复习两次，最后一次 Again
        "beta": {
            "interval": 30,
            "reps": 5,
            "next_review": now + 86400,
            "history": [
                {"timestamp": today_start - 3600, "quality": 2},
                {"timestamp": today_start + 120, "quality": 1},
            ],
        },
        # 到期但今天还没复习
        "gamma": {
            "interval": 0,
            "reps": 0,
            "next_review": today_start - 100,
            "history": [],
        },
    }


def test_today_words_split_new_and_review(tmp_path):
    now = get_current_time().timestamp()
    today_start = get_current_time().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    store = _build_store(
        tmp_path,
        [_word("alpha"), _word("beta"), _word("gamma"), _word("delta")],
        _fixture_progress(now, today_start),
    )

    result = insights.get_today_words(store)

    assert result["total"] == 2
    assert result["new_words"] == 1
    assert result["review_words"] == 1
    assert result["review_events"] == 2
    assert result["again_words"] == 1
    assert result["known_words"] == 1
    # 按最后一次评分时间倒序：beta 更晚
    assert [item["word"] for item in result["words"]] == ["beta", "alpha"]
    assert result["words"][0]["last_quality"] == 1
    assert result["words"][1]["status"] == "new"


def test_book_progress_only_counts_current_book(tmp_path):
    now = get_current_time().timestamp()
    today_start = get_current_time().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    progress = _fixture_progress(now, today_start)
    # 不属于当前词书的进度不能算进本书
    progress["outside"] = {
        "interval": 10,
        "reps": 3,
        "next_review": now + 86400,
        "history": [{"timestamp": today_start + 200, "quality": 3}],
    }
    store = _build_store(
        tmp_path,
        [_word("alpha"), _word("beta"), _word("gamma"), _word("delta")],
        progress,
    )

    result = insights.get_book_progress(store)

    assert result["total_words"] == 4
    assert result["learned_words"] == 3
    assert result["remaining_words"] == 1
    assert result["mastered_words"] == 1
    assert result["learning_words"] == 2
    assert result["due_words"] == 1
    assert result["progress_percent"] == 75.0
    assert result["today_new"] == 1
    assert result["today_review"] == 1


def test_learned_words_support_status_filter_and_paging(tmp_path):
    now = get_current_time().timestamp()
    today_start = get_current_time().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    store = _build_store(
        tmp_path,
        [_word("alpha"), _word("beta"), _word("gamma")],
        _fixture_progress(now, today_start),
    )

    page = insights.get_learned_words(store, page=1, page_size=2, status="all")
    assert page["total"] == 3
    assert page["has_more"] is True
    assert len(page["words"]) == 2

    tail = insights.get_learned_words(store, page=2, page_size=2, status="all")
    assert tail["has_more"] is False
    assert len(tail["words"]) == 1

    mastered = insights.get_learned_words(store, status="mastered")
    assert [item["word"] for item in mastered["words"]] == ["beta"]

    due = insights.get_learned_words(store, status="due")
    assert [item["word"] for item in due["words"]] == ["gamma"]
