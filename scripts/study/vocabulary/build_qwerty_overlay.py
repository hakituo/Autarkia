"""把开源词书 Qwerty Learner 的释义整理成词书覆盖层。

数据源：https://github.com/RealKai42/qwerty-learner
只保留当前全量词书已有的词头，输出
``config/study/vocabulary_qwerty_translations.json``。运行时构建只读该配置，
不依赖原始词库文件，也不联网。

用法：
    python scripts/study/vocabulary/build_qwerty_overlay.py --write
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_QWERTY_DIR = PROJECT_ROOT / "external" / "qwerty-learner" / "dicts"
DEFAULT_MASTER_PATH = (
    PROJECT_ROOT / "data" / "study_data" / "English" / "Words" / "CET-全量.json"
)
DEFAULT_OUTPUT_PATH = (
    PROJECT_ROOT / "config" / "study" / "vocabulary_qwerty_translations.json"
)

SOURCES: tuple[tuple[str, str], ...] = (
    ("CET4", "CET4_T.json"),
    ("CET6", "CET6_T.json"),
    ("考研", "KaoYan_2024.json"),
    ("托福", "TOEFL_3_T.json"),
    ("雅思", "IELTS_3_T.json"),
    ("GRE", "GRE_3_T.json"),
)

MAX_ITEMS_PER_WORD = 8

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
LATIN_RUN_RE = re.compile(r"[A-Za-z]{3,}")
POS_RE = re.compile(
    r"(?<![A-Za-z])(vt|vi|v|adj|adv|ad|prep|conj|pron|art|num|int|abbr|aux|n|a)\.\s*",
    re.IGNORECASE,
)
TAIL_POS_RE = re.compile(
    r"[(（]\s*(vt|vi|v|adj|adv|ad|n|a)\.?\s*[)）]\s*$", re.IGNORECASE
)
SENSE_SPLIT_RE = re.compile(r"[；;，,]")
NORMALIZE_RE = re.compile(r"[\s，,；;、。．.()（）\[\]【】'’\-…]")


def _normalize(text: str) -> str:
    return NORMALIZE_RE.sub("", str(text or "").strip().lower())


def _normalize_pos(value: str) -> str:
    pos = value.strip().lower()
    return {"a": "adj", "ad": "adv"}.get(pos, pos)


def _clean_sense(value: str) -> str:
    item = str(value or "").strip()
    item = re.sub(r"\[[^\]]*\]?", "", item)
    item = re.sub(r"<[^>]*>", "", item)
    item = re.sub(r"[(（][^()（）]*[)）]", "", item)
    item = re.sub(r"[(（][^)）]*$", "", item)
    item = re.sub(r"[^)）]*[)）]$", "", item)
    item = item.strip(" .。:：,，；;、()（）[]【】")
    if not item or not CJK_RE.search(item) or LATIN_RUN_RE.search(item):
        return ""
    return item


def _split_segments(text: str) -> list[tuple[str, str]]:
    """按词性标记切段；没有标记时整段作为一个无词性片段。"""
    tail = TAIL_POS_RE.search(text)
    default_pos = _normalize_pos(tail.group(1)) if tail else ""
    if tail:
        text = text[: tail.start()]

    matches = list(POS_RE.finditer(text))
    if not matches:
        return [(default_pos, text)]

    segments: list[tuple[str, str]] = []
    first = matches[0]
    prefix = text[: first.start()].strip()
    if prefix:
        segments.append((default_pos, prefix))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        segments.append((_normalize_pos(match.group(1)), text[match.end() : end]))
    return segments


def parse_translations(texts: list[str]) -> list[dict[str, str]]:
    """把 Qwerty 的 ``trans`` 数组解析成 ``[{type, translation}]``。"""
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for text in texts:
        for pos, segment in _split_segments(str(text)):
            for part in SENSE_SPLIT_RE.split(segment):
                sense = _clean_sense(part)
                key = _normalize(sense)
                if not key or key in seen:
                    continue
                seen.add(key)
                result.append({"type": pos, "translation": sense})
                if len(result) >= MAX_ITEMS_PER_WORD:
                    return result
    return result


def load_qwerty_words(
    qwerty_dir: Path = DEFAULT_QWERTY_DIR,
) -> dict[str, list[dict[str, str]]]:
    merged: dict[str, dict[str, dict[str, str]]] = {}
    for _book, filename in SOURCES:
        path = qwerty_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Qwerty 词库不存在: {path}")
        for entry in json.loads(path.read_text(encoding="utf-8")):
            word = str(entry.get("name", "")).strip().lower()
            if not word:
                continue
            items = parse_translations([str(t) for t in entry.get("trans") or []])
            if not items:
                continue
            bucket = merged.setdefault(word, {})
            for item in items:
                key = _normalize(item["translation"])
                if not key:
                    continue
                if key in bucket:
                    # 同义词条在不同词书里可能只有其中一本标了词性，优先补全词性
                    if not bucket[key]["type"] and item["type"]:
                        bucket[key]["type"] = item["type"]
                    continue
                if len(bucket) < MAX_ITEMS_PER_WORD:
                    bucket[key] = item
    return {word: list(items.values()) for word, items in merged.items()}


def build_overlay(
    master_path: Path = DEFAULT_MASTER_PATH,
    qwerty_dir: Path = DEFAULT_QWERTY_DIR,
) -> tuple[dict[str, list[dict[str, str]]], dict[str, int]]:
    master = json.loads(master_path.read_text(encoding="utf-8"))
    master_words = {
        str(entry.get("word", "")).strip().lower()
        for entry in master
        if str(entry.get("word", "")).strip()
    }
    qwerty = load_qwerty_words(qwerty_dir)
    overlay = {
        word: items for word, items in qwerty.items() if word in master_words
    }
    report = {
        "master_words": len(master_words),
        "qwerty_words": len(qwerty),
        "overlay_words": len(overlay),
        "overlay_items": sum(len(items) for items in overlay.values()),
    }
    return overlay, report


def write_overlay(path: Path, overlay: dict[str, list[dict[str, str]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "source": {
            "name": "Qwerty Learner 开源词书",
            "license": "GPL-3.0（项目代码）；词库由社区整理",
            "url": "https://github.com/RealKai42/qwerty-learner",
            "note": "CET4/CET6/考研/托福/雅思/GRE 六套词书合并去重；每词最多 8 条。",
        },
        "words": dict(sorted(overlay.items())),
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成 Qwerty 词书释义覆盖层")
    parser.add_argument("--qwerty-dir", type=Path, default=DEFAULT_QWERTY_DIR)
    parser.add_argument("--master", type=Path, default=DEFAULT_MASTER_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--write", action="store_true", help="确认写入配置")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    overlay, report = build_overlay(args.master, args.qwerty_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    for word in ("layoff", "basin"):
        print(word, "->", overlay.get(word))
    if not args.write:
        print("未指定 --write，未写入配置。")
        return 0
    write_overlay(args.output, overlay)
    print(f"已写入: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
