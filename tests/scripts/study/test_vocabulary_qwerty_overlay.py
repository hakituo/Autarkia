# -*- coding: utf-8 -*-
"""回归测试：Qwerty 开源词书覆盖层的解析与去重。"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from scripts.study.vocabulary.build_qwerty_overlay import parse_translations
from scripts.study.vocabulary.qwerty_overlay import (
    filter_covered,
    load_qwerty_translations,
)


def test_tail_pos_applies_to_all_senses() -> None:
    items = parse_translations(["解雇； 裁员； 歇工期， 停工期 (n.)"])
    assert [(item["type"], item["translation"]) for item in items] == [
        ("n", "解雇"),
        ("n", "裁员"),
        ("n", "歇工期"),
        ("n", "停工期"),
    ]


def test_inline_pos_splits_noun_and_verb() -> None:
    items = parse_translations(["n. 工程；计划；事业vt. 设计；计划；发射"])
    assert [item["translation"] for item in items if item["type"] == "n"] == [
        "工程",
        "计划",
        "事业",
    ]
    assert [item["translation"] for item in items if item["type"] == "vt"] == [
        "设计",
        "发射",
    ]


def test_covered_primary_is_removed_from_extended() -> None:
    primary = [{"type": "n", "translation": "盆地"}, {"type": "n", "translation": "流域"}]
    assert filter_covered([{"type": "n", "translation": "盆地"}], primary) == []
    assert filter_covered([{"type": "n", "translation": "流域"}], primary) == []


def test_uncovered_sense_is_kept() -> None:
    kept = filter_covered(
        [{"type": "n", "translation": "脸盆"}],
        [{"type": "n", "translation": "盆地"}],
    )
    assert [item["translation"] for item in kept] == ["脸盆"]


def test_invalid_overlay_structure_is_rejected(tmp_path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text(
        json.dumps({"version": 2, "words": {}}, ensure_ascii=False),
        encoding="utf-8",
    )
    try:
        load_qwerty_translations(path)
    except ValueError:
        pass
    else:
        raise AssertionError("无效结构应抛出 ValueError")
