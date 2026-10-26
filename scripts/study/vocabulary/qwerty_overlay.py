"""开源词书 Qwerty Learner 的释义覆盖层。

Qwerty Learner（https://github.com/RealKai42/qwerty-learner）提供 CET4/CET6/
考研/托福/雅思/GRE 六套开源词书。``build_qwerty_overlay.py`` 离线解析后只保留
当前全量词书里存在的词头，写入 ``config/study/vocabulary_qwerty_translations.json``。
构建时以这份策划过的释义作为主释义，ECDICT 的义项退到「更多/专业释义」。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OVERLAY_PATH = (
    PROJECT_ROOT / "config" / "study" / "vocabulary_qwerty_translations.json"
)

MAX_TRANSLATION_ITEMS = 8

_NORMALIZE_RE = re.compile(r"[\s，,；;、。．.()（）\[\]【】'’\-…]")


def normalize_translation(text: Any) -> str:
    return _NORMALIZE_RE.sub("", str(text or "").strip().lower())


def load_qwerty_translations(
    path: Path = DEFAULT_OVERLAY_PATH,
) -> dict[str, list[dict[str, str]]]:
    """读取 Qwerty 释义覆盖层；结构无效时直接报错。"""
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("version") != 1 or not isinstance(payload.get("words"), dict):
        raise ValueError(f"Qwerty 释义覆盖层结构无效: {path}")
    result: dict[str, list[dict[str, str]]] = {}
    for word, items in payload["words"].items():
        key = str(word or "").strip().lower()
        if not key or not isinstance(items, list):
            continue
        cleaned = [
            {
                "type": str(item.get("type", "")).strip(),
                "translation": str(item.get("translation", "")).strip(),
            }
            for item in items
            if isinstance(item, dict) and str(item.get("translation", "")).strip()
        ]
        if cleaned:
            result[key] = cleaned[:MAX_TRANSLATION_ITEMS]
    return result


def filter_covered(
    items: Iterable[dict[str, Any]],
    primary: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """去掉已被主释义覆盖的义项（双向包含判断），用于折叠区去重。"""
    primary_keys = [
        normalize_translation(item.get("translation", "")) for item in primary
    ]
    primary_keys = [key for key in primary_keys if key]
    result: list[dict[str, Any]] = []
    for item in items:
        key = normalize_translation(item.get("translation", ""))
        if not key:
            continue
        if any(
            key == value
            or (len(key) >= 2 and len(value) >= 2 and (key in value or value in key))
            for value in primary_keys
        ):
            continue
        result.append(dict(item))
    return result
