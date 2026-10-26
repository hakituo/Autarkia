"""空正文记忆的 hydration 分类（v3 C2 / E05 / E06）。

``content`` 为空不等于"原文已失联"：正常 compact 会置空，加载时可用
``event_ref`` 回读。只有确实读不回原文的记录才算 legacy 孤儿。
四类结果互斥，分母是"空正文记忆条数"。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, Mapping, Optional

RECOVERABLE = "recoverable"
EMPTY_EVENT = "empty_event"
EVENT_MISSING = "event_missing"
MISSING_REF = "missing_ref"
READ_FAILED = "read_failed"


def _event_ref(record: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    metadata = record.get("metadata")
    if not isinstance(metadata, dict):
        return None
    ref = metadata.get("event_ref")
    return ref if isinstance(ref, dict) and ref.get("event_id") else None


def classify_empty_memories(
    records: Iterable[Mapping[str, Any]],
    content_loader: Optional[Callable[[Mapping[str, Any]], Optional[str]]],
    *,
    sample_limit: int = 20,
) -> Dict[str, Any]:
    """按"能否回读原文"给空正文记忆分类。"""
    counts: Dict[str, int] = {
        RECOVERABLE: 0,
        EMPTY_EVENT: 0,
        EVENT_MISSING: 0,
        MISSING_REF: 0,
        READ_FAILED: 0,
    }
    samples: Dict[str, list] = {key: [] for key in counts}
    total_empty = 0
    total = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        total += 1
        if str(record.get("content") or "").strip():
            continue
        total_empty += 1
        memory_id = str(record.get("id") or "")
        ref = _event_ref(record)
        if ref is None:
            kind = MISSING_REF
        elif content_loader is None:
            kind = READ_FAILED
        else:
            try:
                loaded = content_loader(ref)
            except Exception:  # noqa: BLE001 - 读取异常单独计类
                kind = READ_FAILED
            else:
                if loaded is None:
                    kind = EVENT_MISSING
                elif not str(loaded).strip():
                    kind = EMPTY_EVENT
                else:
                    kind = RECOVERABLE
        counts[kind] += 1
        if len(samples[kind]) < sample_limit:
            samples[kind].append(memory_id)
    return {
        "denominator": total_empty,
        "memories_total": total,
        "counts": counts,
        "samples": samples,
        "dedupe_key": "记忆 id",
        "note": "空正文 == compact / 失联 / 读取失败 三者需分开，不能一律计为失联",
    }
