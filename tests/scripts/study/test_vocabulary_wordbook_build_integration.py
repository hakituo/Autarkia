# -*- coding: utf-8 -*-
"""构建级回归：真实走临时 ECDICT CSV -> build_wordbooks。"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.study.vocabulary.wordbook_builder import build_wordbooks


ECDICT_FIELDS = [
    "word",
    "phonetic",
    "definition",
    "translation",
    "pos",
    "collins",
    "oxford",
    "tag",
    "bnc",
    "frq",
    "exchange",
    "detail",
    "audio",
]


def _write_fixture(path: Path) -> None:
    rows = [
        {
            "word": "perspective",
            "phonetic": "pə'spektiv",
            "translation": "n. 远景\nn. 透视；透视法\nn. 观点；视角",
            "pos": "n:100",
            "tag": "cet4",
            "bnc": "3000",
            "frq": "2500",
        },
        {
            "word": "unrankedfixture",
            "phonetic": "",
            "translation": "n. 原始第一义\nn. 原始第二义",
            "pos": "n:100",
            "tag": "cet4",
            "bnc": "0",
            "frq": "0",
        },
        {
            "word": "basin",
            "phonetic": "'beisn",
            "translation": "n. 盆, 盆地",
            "pos": "n:100",
            "tag": "cet4",
            "bnc": "4000",
            "frq": "6000",
        },
        {
            "word": "layoff",
            "phonetic": "'leiɒf",
            "translation": "n. 临时解雇, 操作停止",
            "pos": "n:100",
            "tag": "cet6",
            "bnc": "40000",
            "frq": "7000",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ECDICT_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _find(entries: list[dict], word: str) -> dict:
    return next(entry for entry in entries if entry["word"] == word)


def test_wordbook_build_is_deterministic_and_applies_ranking(tmp_path: Path) -> None:
    ecdict = tmp_path / "ecdict.csv"
    words_dir = tmp_path / "Words"
    sentence_dir = tmp_path / "Sentence"
    progress = tmp_path / "missing_progress.json"
    overrides = tmp_path / "missing_overrides.json"
    _write_fixture(ecdict)

    kwargs = {
        "ecdict_path": ecdict,
        "words_dir": words_dir,
        "sentence_dir": sentence_dir,
        "overrides_path": overrides,
        "progress_path": progress,
        "qwerty_overlay_path": tmp_path / "missing_qwerty_overlay.json",
    }
    first_books, first_report = build_wordbooks(**kwargs)
    second_books, second_report = build_wordbooks(**kwargs)

    # 整个构建结果和 report 都必须可重复，而不是只验证单个排序函数。
    assert json.dumps(first_books, ensure_ascii=False, sort_keys=True) == json.dumps(
        second_books, ensure_ascii=False, sort_keys=True
    )
    assert first_report == second_report

    master = first_books["CET-全量.json"]
    perspective = _find(master, "perspective")
    assert [item["translation"] for item in perspective["translations"]] == [
        "观点；视角",
        "透视；透视法",
        "远景",
    ]

    # 没有 ranking 数据的词仍严格保留 source dictionary order。
    unranked = _find(master, "unrankedfixture")
    assert [item["translation"] for item in unranked["translations"]] == [
        "原始第一义",
        "原始第二义",
    ]


def test_qwerty_overlay_is_primary_and_keeps_ecdict_extended(tmp_path: Path) -> None:
    ecdict = tmp_path / "ecdict.csv"
    words_dir = tmp_path / "Words"
    sentence_dir = tmp_path / "Sentence"
    overlay = tmp_path / "qwerty_overlay.json"
    overrides = tmp_path / "overrides.json"
    _write_fixture(ecdict)
    overlay.write_text(
        json.dumps(
            {
                "version": 1,
                "words": {
                    "basin": [
                        {"type": "n", "translation": "盆地"},
                        {"type": "n", "translation": "流域"},
                    ],
                    "layoff": [
                        {"type": "n", "translation": "解雇"},
                        {"type": "n", "translation": "裁员"},
                    ],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    books, _ = build_wordbooks(
        ecdict_path=ecdict,
        words_dir=words_dir,
        sentence_dir=sentence_dir,
        overrides_path=tmp_path / "missing_overrides.json",
        progress_path=tmp_path / "missing_progress.json",
        qwerty_overlay_path=overlay,
    )
    master = books["CET-全量.json"]

    basin = _find(master, "basin")
    assert [item["translation"] for item in basin["translations"]] == ["盆地", "流域"]
    assert "盆" in [
        item["translation"] for item in basin.get("extended_translations") or []
    ]

    layoff = _find(master, "layoff")
    assert [item["translation"] for item in layoff["translations"]] == ["解雇", "裁员"]
    assert "操作停止" in [
        item["translation"] for item in layoff.get("extended_translations") or []
    ]

    # 人工 override 仍然高于开源词书覆盖层。
    overrides.write_text(
        json.dumps(
            {
                "version": 1,
                "words": {
                    "basin": {
                        "collapse_source_translations": True,
                        "primary_translations": [{"type": "n", "translation": "水域"}],
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    override_books, _ = build_wordbooks(
        ecdict_path=ecdict,
        words_dir=words_dir,
        sentence_dir=sentence_dir,
        overrides_path=overrides,
        progress_path=tmp_path / "missing_progress.json",
        qwerty_overlay_path=overlay,
    )
    override_basin = _find(override_books["CET-全量.json"], "basin")
    assert [item["translation"] for item in override_basin["translations"]] == ["水域"]
    assert "流域" in [
        item["translation"] for item in override_basin.get("extended_translations") or []
    ]
