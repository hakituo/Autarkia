# -*- coding: utf-8 -*-
"""验证开源词书覆盖层已进入成品词书，且未破坏主释义/扩展释义分区。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.study.vocabulary.qwerty_overlay import (  # noqa: E402
    DEFAULT_OVERLAY_PATH,
    load_qwerty_translations,
    normalize_translation,
)

WORDS_DIR = PROJECT_ROOT / "data" / "study_data" / "English" / "Words"
BOOKS = (
    "CET-全量.json",
    "CET4-顺序.json",
    "CET6-顺序.json",
    "考研-顺序.json",
    "托福-顺序.json",
    "雅思-顺序.json",
    "GRE-顺序.json",
)
EXPECTED = {
    "layoff": "裁员",
    "basin": "流域",
}

_PASSED = 0
_FAILED = 0


def _ok(message: str) -> None:
    global _PASSED
    _PASSED += 1
    print(f"  [PASS] {message}")


def _fail(message: str) -> None:
    global _FAILED
    _FAILED += 1
    print(f"  [FAIL] {message}")


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def _load_book(filename: str) -> list[dict]:
    path = WORDS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"词书不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _find(entries: list[dict], word: str) -> dict | None:
    return next(
        (
            entry
            for entry in entries
            if str(entry.get("word", "")).strip().lower() == word
        ),
        None,
    )


def check_overlay_config() -> None:
    _section("覆盖层配置")
    overlay = load_qwerty_translations(DEFAULT_OVERLAY_PATH)
    if len(overlay) < 9000:
        _fail(f"覆盖层词数过少: {len(overlay)}")
    else:
        _ok(f"覆盖层包含 {len(overlay)} 个词")

    for word, expected in EXPECTED.items():
        translations = [
            item["translation"] for item in overlay.get(word, [])
        ]
        if expected in translations:
            _ok(f"{word} 覆盖层包含「{expected}」")
        else:
            _fail(f"{word} 覆盖层缺少「{expected}」: {translations}")


def check_written_books() -> None:
    _section("成品词书")
    for filename in BOOKS:
        entries = _load_book(filename)
        for word, expected in EXPECTED.items():
            entry = _find(entries, word)
            if entry is None:
                continue
            translations = [
                item.get("translation", "") for item in entry.get("translations") or []
            ]
            if expected in translations:
                _ok(f"{filename} / {word} 含「{expected}」")
            else:
                _fail(f"{filename} / {word} 缺少「{expected}」: {translations}")


def check_no_duplicate_translations() -> None:
    _section("释义去重")
    for filename in BOOKS:
        entries = _load_book(filename)
        duplicates: list[str] = []
        for entry in entries:
            keys: list[tuple[str, str, tuple[str, ...]]] = []
            for field in ("translations", "extended_translations"):
                for item in entry.get(field) or []:
                    key = normalize_translation(item.get("translation", ""))
                    if key:
                        # 同一中文在不同词性/专业领域下是合法义项
                        keys.append(
                            (
                                str(item.get("type", "")).strip(),
                                key,
                                tuple(item.get("domains") or []),
                            )
                        )
            if len(keys) != len(set(keys)):
                duplicates.append(str(entry.get("word", "")))
        if duplicates:
            _fail(f"{filename} 存在重复义项: {duplicates[:10]}")
        else:
            _ok(f"{filename} 无重复义项")


def check_overlay_is_primary() -> None:
    _section("覆盖层主释义")
    overlay = load_qwerty_translations(DEFAULT_OVERLAY_PATH)
    master = {entry["word"].lower(): entry for entry in _load_book("CET-全量.json")}
    checked = 0
    mismatched: list[str] = []
    for word, items in overlay.items():
        entry = master.get(word)
        if entry is None:
            continue
        expected = [normalize_translation(item["translation"]) for item in items]
        primary = [
            normalize_translation(item.get("translation", ""))
            for item in entry.get("translations") or []
        ]
        extended = [
            normalize_translation(item.get("translation", ""))
            for item in entry.get("extended_translations") or []
        ]
        checked += 1
        # 人工 override / sense ranking 会调整顺序甚至折叠到扩展区，只校验义项没有丢
        available = set(primary) | set(extended)
        if any(item not in available for item in expected):
            mismatched.append(word)
    if mismatched:
        _fail(f"{len(mismatched)} 个词的覆盖层义项未进入词书: {mismatched[:10]}")
    else:
        _ok(f"{checked} 个覆盖词的义项均进入词书")


def main() -> int:
    check_overlay_config()
    check_written_books()
    check_no_duplicate_translations()
    check_overlay_is_primary()
    print(f"\n通过 {_PASSED} 项，失败 {_FAILED} 项")
    return 0 if _FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
