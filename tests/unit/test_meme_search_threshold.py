"""表情包语义检索阈值与候选过滤的回归测试。

背景：阈值原为 0.25 且带「阈值 70% 兜底」，0.5x 的无关匹配（如"抱胸"撞
"抱住蹭蹭"）也会发图；top-K 加权随机还可能挑到明显更差的候选。
"""
from __future__ import annotations

import random

import numpy as np
import pytest

from clients.bots.qq import meme_search as ms


def _setup_index(monkeypatch, tmp_path, vectors, paths):
    for rel in paths:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"png")
    monkeypatch.setattr(ms, "MEMES_ROOT", tmp_path)
    monkeypatch.setattr(ms, "_loaded", True)
    monkeypatch.setattr(ms, "_vectors", np.asarray(vectors, dtype=np.float32))
    monkeypatch.setattr(ms, "_paths", list(paths))
    monkeypatch.setattr(ms, "_backend", ("onnx", None, None))
    monkeypatch.setattr(ms, "_encode_query", lambda _text: np.array([1.0, 0.0], dtype=np.float32))


def test_low_similarity_returns_none(monkeypatch, tmp_path):
    """低于阈值直接不发，不再走 70% 兜底发勉强沾边的图。"""
    _setup_index(monkeypatch, tmp_path, [[0.5, 0.866], [0.3, 0.954]], ["a.png", "b.png"])

    assert ms.pick_meme_by_semantic("抱住蹭蹭") is None


def test_similarity_above_threshold_is_chosen(monkeypatch, tmp_path):
    _setup_index(monkeypatch, tmp_path, [[0.9, 0.436]], ["a.png"])

    chosen = ms.pick_meme_by_semantic("开心大笑")

    assert chosen == tmp_path / "a.png"


def test_random_pick_stays_near_best_candidate(monkeypatch, tmp_path):
    """0.9 与 0.7 都过阈值，但 0.7 超出相对差距，不应进入随机池。"""
    _setup_index(
        monkeypatch, tmp_path, [[0.9, 0.436], [0.7, 0.714]], ["a.png", "b.png"]
    )
    seen: list[list[tuple[float, str]]] = []

    def fake_choices(population, weights, k):
        seen.append(list(population))
        return [population[0]]

    monkeypatch.setattr(random, "choices", fake_choices)

    chosen = ms.pick_meme_by_semantic("开心大笑")

    assert chosen == tmp_path / "a.png"
    assert len(seen) == 1
    assert [rel for _, rel in seen[0]] == ["a.png"]
    assert seen[0][0][0] == pytest.approx(0.9)


def test_excluded_best_falls_back_to_next_eligible(monkeypatch, tmp_path):
    """LRU 传绝对路径时也要能匹配索引里的相对路径。"""
    _setup_index(monkeypatch, tmp_path, [[0.9, 0.436], [0.8, 0.6]], ["a.png", "b.png"])

    chosen = ms.pick_meme_by_semantic(
        "开心大笑", exclude_paths={str(tmp_path / "a.png")}
    )

    assert chosen == tmp_path / "b.png"
