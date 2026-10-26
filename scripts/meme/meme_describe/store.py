"""descriptions.json 的读写（兼容三种历史格式）。"""

from __future__ import annotations

import json
import os
from typing import Any

from core.utils.logger import get_logger

from .paths import DESCRIPTIONS_PATH, INDEX_DIR
from .prompt import VL_VISION_MODEL

logger = get_logger("meme_describe_store")


def load_existing() -> dict[str, dict[str, Any]]:
    """加载已生成的描述，返回 {相对路径: {caption, tags, text}}。

    兼容三种旧格式：
    - v1: items: [{path, caption(str)}]
    - v2: items: [{path, caption(str), tags, text}]
    - 旧 dict: {rel_path: caption(str)}
    """
    if not DESCRIPTIONS_PATH.is_file():
        return {}
    try:
        with open(DESCRIPTIONS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "items" in data:
            items = data["items"]
        elif isinstance(data, dict):
            items = data
        else:
            return {}
        result: dict[str, dict[str, Any]] = {}
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                p = item.get("path") or item.get("rel_path")
                if not p:
                    continue
                p = str(p)
                cap = item.get("caption") or item.get("description") or ""
                tags = item.get("tags") or []
                text = item.get("text") or item.get("visible_text") or ""
                if cap:
                    result[p] = {
                        "caption": str(cap),
                        "tags": list(tags) if isinstance(tags, list) else [],
                        "text": str(text),
                    }
        elif isinstance(items, dict):
            for k, v in items.items():
                if isinstance(v, str):
                    result[str(k)] = {"caption": v, "tags": [], "text": ""}
                elif isinstance(v, dict):
                    cap = v.get("caption") or v.get("description") or ""
                    if cap:
                        result[str(k)] = {
                            "caption": str(cap),
                            "tags": list(v.get("tags") or []),
                            "text": str(v.get("text") or ""),
                        }
        return result
    except Exception as e:  # noqa: BLE001 - 描述文件读不出来时从头开始，不阻断打标
        logger.warning(f"加载已有描述失败，将从头开始: {e}")
        return {}


def save_descriptions(descs: dict[str, dict[str, Any]]) -> None:
    """保存描述到 JSON，格式 {version, model, count, items: [{path, caption, tags, text}]}。"""
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for path, info in sorted(descs.items()):
        items.append({
            "path": path,
            "caption": info.get("caption", ""),
            "tags": info.get("tags", []),
            "text": info.get("text", ""),
        })
    payload = {
        "version": 2,
        "model": VL_VISION_MODEL,
        "count": len(items),
        "items": items,
    }
    tmp_path = DESCRIPTIONS_PATH.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, DESCRIPTIONS_PATH)
    logger.info(f"已保存 {len(items)} 条描述到 {DESCRIPTIONS_PATH}")
