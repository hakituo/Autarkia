"""派生笔记库：每个会话一个 JSON，按 segment 整体原子替换（spec §8）。

- ``note_id = hash(source_segment_id + extractor_version + kind + 规范化 text)``，重跑不产生等义重复。
- 同段重写：旧版本整体移入该段的 ``history``，当前版本只留一份（旧版本可追溯，spec §8.3）。
- 写入前校验证据：``source_event_ids`` 必须是该段来源事件的子集，越界的草稿丢弃并计数。
- ``has_segment`` 只认「该提取器版本、且有至少一条当前笔记」，零产出不算完成。
- ``valid_to``：plan 的到期日（草稿 metadata 带来，见 ``plan_due``），其余为空；``valid_from`` 先留空；
  ``visibility`` 先固定 ``tree_local``。
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
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


#: 随梗概落盘的画像信号字段（人物档案门控读取，见 ``core.character.people.signal_gate``）
SIGNAL_FIELDS = ("profile_signal_analyzed", "people_mentions", "role_update_candidates")


#: 随笔记落盘的其它可选字段：plan 的 status（open / done / cancelled，提取器 v9 起）
EXTRA_FIELDS = ("status",)


def _signal_fields(metadata: Any) -> Dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    return {key: metadata[key] for key in SIGNAL_FIELDS + EXTRA_FIELDS if key in metadata}


def _draft_time(draft: Any, key: str, default: Optional[float]) -> Optional[float]:
    metadata = _field(draft, "metadata", None)
    value = metadata.get(key) if isinstance(metadata, dict) else None
    try:
        return float(value) if value else default
    except (TypeError, ValueError):
        return default


class NoteStore:
    """``root`` 缺省为当前梗概目录（``paths.notes_dir``）；过渡期读旧库时传旧目录（只读）。"""

    def __init__(
        self, scope: str, *, perspective_role: Optional[str] = None, root: Path | None = None
    ):
        self.scope = scope
        self.perspective_role = perspective_role or scope
        self.root = root

    def directory(self) -> Path:
        return self.root if self.root is not None else paths.notes_dir(self.scope)

    def path(self, conversation_id: str) -> Path:
        if self.root is None:
            return paths.notes_path(self.scope, conversation_id)
        return self.root / paths.notes_file_name(conversation_id)

    # -- 读 --
    def _load(self, conversation_id: str) -> Dict[str, Any]:
        data = safe_json_load(self.path(conversation_id), default=None)
        if not isinstance(data, dict) or not isinstance(data.get("segments"), dict):
            return {"version": SCHEMA_VERSION, "conversation_id": conversation_id, "segments": {}}
        return data

    def list_conversations(self) -> List[str]:
        """本 scope 下有笔记文件的会话 ID（按文件内记录的原值，不用清洗后的文件名）。"""
        root = self.directory()
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

    def segment_entries(self, conversation_id: str) -> dict[str, dict[str, Any]]:
        """段号 → 段条目（含 ``notes`` / ``source_event_ids`` / ``carry_event_ids``）。"""
        return dict(self._load(conversation_id)["segments"])

    def get_carry(self, conversation_id: str, segment_id: str) -> list[str]:
        """上一段交给下一段接力的往来（事件 ID）；没有就是空列表。"""
        entry = self._load(conversation_id)["segments"].get(segment_id) or {}
        return [str(e) for e in entry.get("carry_event_ids") or []]

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
        carry_event_ids: Iterable[str] = (),
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
                # 这条梗概依据的对话发生的时间（检索输出与「什么时候」类问题用；不等于 valid_*）。
                # 一段多条（按话题分条）时草稿自带各自的时间，优先于整段时间
                "occurred_from": _draft_time(draft, "occurred_from", occurred_from),
                "occurred_to": _draft_time(draft, "occurred_to", occurred_to),
                "valid_from": None,
                "valid_to": _draft_time(draft, "valid_to", None),
                "superseded_by": None,
                "importance": importance,
                **_signal_fields(_field(draft, "metadata", None)),
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
                # 本段覆盖的来源事件：v2 过渡期按它隐藏旧库里同一批事件的梗概
                "source_event_ids": sorted(allowed),
                **({"carry_event_ids": list(carry_event_ids)} if carry_event_ids else {}),
            }
            safe_json_dump(data, self.path(conversation_id))
        return ReplaceResult(written=len(notes), rejected=rejected, duplicate=duplicate)

    def rewrite_texts(self, conversation_id: str, rewrite: Any, *, mark: str = "") -> int:
        """按 ``rewrite(note) -> 新正文或 None`` 原地改当前梗概正文，返回改了几条。

        ``note_id`` 不变（展开原话的编号与向量缓存键都靠它）；``mark`` 记进 ``text_revisions``，
        供确定性后处理（如补日期）留痕与防重复。
        """
        changed = 0
        with _lock:
            data = self._load(conversation_id)
            for entry in data["segments"].values():
                for note in entry.get("notes") or []:
                    text = rewrite(dict(note))
                    if text is None or text == note.get("text"):
                        continue
                    note["text"] = text
                    if mark:
                        note["text_revisions"] = [*note.get("text_revisions", []), mark]
                    changed += 1
            if changed:
                safe_json_dump(data, self.path(conversation_id))
        return changed

    def patch_notes(self, conversation_id: str, patch: Any) -> int:
        """按 ``patch(note) -> 要改的字段 dict 或 None`` 原地改当前梗概的元数据，返回改了几条。

        不碰正文与 ``note_id``（回填 ``valid_to`` 这类确定性字段用）。
        """
        changed = 0
        with _lock:
            data = self._load(conversation_id)
            for entry in data["segments"].values():
                for note in entry.get("notes") or []:
                    fields = patch(dict(note))
                    if not fields:
                        continue
                    fields = {k: v for k, v in fields.items() if k not in {"note_id", "text"}}
                    if any(note.get(k) != v for k, v in fields.items()):
                        note.update(fields)
                        changed += 1
            if changed:
                safe_json_dump(data, self.path(conversation_id))
        return changed

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
            safe_json_dump(data, self.path(conversation_id))
        return True
