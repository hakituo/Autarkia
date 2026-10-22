"""复习分组：limit=每组数量，完成一组后自然推进到下一组。"""
from __future__ import annotations

import os
import time

from core.tools.study.english import daily_word_log as daily_module
from core.tools.study.english import quiz
from core.tools.study.english.daily_word_log import DailyWordLogManager


class _FakeStore:
    """只提供 quiz.get_daily_words 需要的最小接口，避免加载真实词书。"""

    def __init__(self, words):
        self.dictionary = [
            {"word": word, "translations": [{"type": "n.", "translation": word}]}
            for word in words
        ]
        self.progress = {}

    def _ensure_loaded(self):
        return None

    def get_word_info(self, word):
        for entry in self.dictionary:
            if entry["word"] == word:
                return entry
        return None

    def get_sentence_info(self, word):
        return None


def _mark_reviewed(store, word: str) -> None:
    """模拟完成评分：写入今天的评分事件，当天不再待复习。"""
    data = store.progress.setdefault(
        word, {"reps": 0, "interval": 0, "next_review": 0, "history": []}
    )
    data["history"].append({"timestamp": time.time(), "quality": 4})
    data["next_review"] = time.time() + 86400


def _prepare_daily(tmp_path, monkeypatch, words):
    manager = DailyWordLogManager(base_dir=os.path.join(tmp_path, "daily"))
    manager._get_today_str = lambda: "2026/08/31"
    path = manager._date_to_path("2026/08/28")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        file.write("# 每日单词\n" + "\n".join(words) + "\n")
    monkeypatch.setattr(daily_module, "_instance", manager)
    return _FakeStore(words)


def test_review_batches_advance_after_each_group(tmp_path, monkeypatch):
    words = ["w1", "w2", "w3", "w4", "w5", "w6"]
    store = _prepare_daily(tmp_path, monkeypatch, words)

    first = [item["word"] for item in quiz.get_daily_words(store, limit=2)]
    assert first == ["w1", "w2"]
    for word in first:
        _mark_reviewed(store, word)

    second = [item["word"] for item in quiz.get_daily_words(store, limit=2)]
    assert second == ["w3", "w4"]
    for word in second:
        _mark_reviewed(store, word)

    rest = [item["word"] for item in quiz.get_daily_words(store, limit=0)]
    assert rest == ["w5", "w6"]


def test_group_limit_does_not_change_full_queue(tmp_path, monkeypatch):
    words = ["w1", "w2", "w3"]
    store = _prepare_daily(tmp_path, monkeypatch, words)

    assert len(quiz.get_daily_words(store, limit=1)) == 1
    # 只分组、不评分：队列本身不变，仍能取到全部
    assert [item["word"] for item in quiz.get_daily_words(store, limit=0)] == words
