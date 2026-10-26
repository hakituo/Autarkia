"""派生笔记库：每个会话一个 JSON，按 segment 整体原子替换（spec §8）。

- ``note_id = hash(source_segment_id + extractor_version + kind + 规范化 text)``，重跑不产生等义重复。
- 同段重写：旧版本整体移入该段的 ``history``，当前版本只留一份（旧版本可追溯，spec §8.3）。
- 写入前校验证据：``source_event_ids`` 必须是该段来源事件的子集，越界的草稿丢弃并计数。
- ``has_segment`` 只认「该提取器版本、且有至少一条当前笔记」，零产出不算完成。
- ``valid_*`` 先留空（F6 再填）；``visibility`` 先固定 ``tree_local``。
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from core.utils.atomic_io import safe_json_dump, safe_json_load

from . import paths

SCHEMA_VERSION = 1
VISIBILITY_TREE_LOCAL = "tree_local"
_lock = threading.RLock()


@dataclass(frozen=True)
class ReplaceResult:
    written: int = 0
    rejected: int = 0  # 证据越界 / 缺字段而被丢弃的草稿数
    duplicate: int = 0  # 与同批已有笔记等义而合并的草稿数


def _norm_text(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def make_note_id(segment_id: str, extractor_version: str, kind: str, text: str) -> str:
    raw = "\x1f".join([str(segment_id), str(extractor_version), str(kind), _norm_text(text)])
    return "note_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _field(draft: Any, name: str, default: Any = None) -> Any:
    if isinstance(draft, dict):
        return draft.get(name, default)
    return getattr(draft, name, default)


class NoteStore:
    def __init__(self, scope: str, *, perspective_role: Optional[str] = None):
        self.scope = scope
        self.perspective_role = perspective_role or scope

    # -- 读 --
    def _load(self, conversation_id: str) -> Dict[str, Any]:
        data = safe_json_load(paths.notes_path(self.scope, conversation_id), default=None)
        if not isinstance(data, dict) or not isinstance(data.get("segments"), dict):
            return {"version": SCHEMA_VERSION, "conversation_id": conversation_id, "segments": {}}
        return data

    def list_conversations(self) -> List[str]:
        """本 scope 下有笔记文件的会话 ID（按文件内记录的原值，不用清洗后的文件名）。"""
        root = paths.notes_dir(self.scope)
        if not root.exists():
            return []
        found: List[str] = []
        for file_path in sorted(root.glob("*.json")):
            data = safe_json_load(file_path, default=None)
            if isinstance(data, dict) and data.get("conversation_id"):
                found.append(str(data["conversation_id"]))
        return found

    def has_segment(self, conversation_id: str, segment_id: str, extractor_version: str) -> bool:
        entry = self._load(conversation_id)["segments"].get(segment_id)
        return bool(
            entry and entry.get("extractor_version") == extractor_version and entry.get("notes")
        )

    def list_notes(self, conversation_id: str) -> List[Dict[str, Any]]:
        notes: List[Dict[str, Any]] = []
        for entry in self._load(conversation_id)["segments"].values():
            notes.extend(dict(n) for n in entry.get("notes") or [])
        return notes

    def segment_history(self, conversation_id: str, segment_id: str) -> List[Dict[str, Any]]:
        entry = self._load(conversation_id)["segments"].get(segment_id) or {}
        return [dict(h) for h in entry.get("history") or []]

    # -- 写 --
    def replace_segment(
        self,
        conversation_id: str,
        segment_id: str,
        extractor_version: str,
        drafts: Iterable[Any],
        *,
        segment_source_event_ids: Iterable[str],
        occurred_from: Optional[float] = None,
        occurred_to: Optional[float] = None,
    ) -> ReplaceResult:
        """用 ``drafts`` 整体替换该段当前笔记；证据校验以 ``segment_source_event_ids`` 为准。"""
        allowed = {str(e) for e in segment_source_event_ids}
        now = time.time()
        notes: Dict[str, Dict[str, Any]] = {}
        rejected = duplicate = 0
        for draft in drafts:
            kind = str(_field(draft, "kind", "") or "")
            text = _norm_text(_field(draft, "text", ""))
            evidence = tuple(str(e) for e in (_field(draft, "source_event_ids", ()) or ()))
            if not kind or not text or not evidence or not set(evidence) <= allowed:
                rejected += 1
                continue
            try:
                importance = float(_field(draft, "importance", 0.5))
            except (TypeError, ValueError):
                importance = 0.5
            note_id = make_note_id(segment_id, extractor_version, kind, text)
            if note_id in notes:
                duplicate += 1
                continue
            notes[note_id] = {
                "note_id": note_id,
                "scope": self.scope,
                "perspective_role": self.perspective_role,
                "conversation_id": conversation_id,
                "visibility": VISIBILITY_TREE_LOCAL,
                "kind": kind,
                "text": text,
                "source_event_ids": list(evidence),
                "source_segment_id": segment_id,
                "extractor_version": extractor_version,
                "recorded_from": now,
                # 这段对话本身发生的时间（检索输出与「什么时候」类问题用；不等于 valid_*）
                "occurred_from": occurred_from,
                "occurred_to": occurred_to,
                "valid_from": None,
                "valid_to": None,
                "superseded_by": None,
                "importance": importance,
            }
        with _lock:
            data = self._load(conversation_id)
            old = data["segments"].get(segment_id)
            history = list((old or {}).get("history") or [])
            if old and old.get("notes"):
                history.append(
                    {
                        "extractor_version": old.get("extractor_version"),
                        "replaced_at": now,
                        "notes": old["notes"],
                    }
                )
            data["segments"][segment_id] = {
                "extractor_version": extractor_version,
                "recorded_at": now,
                "notes": list(notes.values()),
                "history": history,
            }
            safe_json_dump(data, paths.notes_path(self.scope, conversation_id))
        return ReplaceResult(written=len(notes), rejected=rejected, duplicate=duplicate)

    def drop_segment(self, conversation_id: str, segment_id: str) -> bool:
        """迟到事件让段失效：当前笔记移入 history（可追溯），段不再算已完成。"""
        with _lock:
            data = self._load(conversation_id)
            entry = data["segments"].get(segment_id)
            if not entry:
                return False
            if entry.get("notes"):
                entry.setdefault("history", []).append(
                    {
                        "extractor_version": entry.get("extractor_version"),
                        "replaced_at": time.time(),
                        "notes": entry["notes"],
                        "dropped": True,
                    }
                )
            entry["notes"] = []
            safe_json_dump(data, paths.notes_path(self.scope, conversation_id))
        return True
