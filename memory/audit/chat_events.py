"""扫描原始聊天事件并规范化为 v3 视图（只读）。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from memory.topology.events import NormalizedEvent, normalize_event


@dataclass
class ScannedEvent:
    raw: Dict[str, object]
    normalized: NormalizedEvent
    relative_path: str


@dataclass
class ScopeScan:
    scope: str
    chat_dir: str
    files: int = 0
    lines: int = 0
    malformed_lines: int = 0
    events: List[ScannedEvent] = field(default_factory=list)

    def failed(self) -> bool:
        return self.files == 0


def iter_jsonl(path: Path) -> Iterator[Tuple[int, Optional[Dict[str, object]]]]:
    """逐行产出 ``(行号, payload)``；坏行 payload 为 ``None``。"""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                raw = line.strip()
                if not raw:
                    continue
                try:
                    payload = json.loads(raw)
                except Exception:
                    yield number, None
                    continue
                yield number, payload if isinstance(payload, dict) else None
    except OSError:
        return


def scan_scope(
    scope: str,
    chat_dir: Path,
    *,
    perspective_role: str = "",
) -> ScopeScan:
    """扫描一个 scope 的 chat_history（含分线子目录）。"""
    scan = ScopeScan(scope=scope, chat_dir=str(chat_dir))
    if not chat_dir.exists():
        return scan
    for path in sorted(chat_dir.rglob("*.jsonl")):
        scan.files += 1
        relative = path.relative_to(chat_dir).as_posix()
        for _number, payload in iter_jsonl(path):
            scan.lines += 1
            if payload is None:
                scan.malformed_lines += 1
                continue
            normalized = normalize_event(
                payload,
                storage_scope=str(payload.get("storage_scope") or scope),
                perspective_role=perspective_role or scope,
                recorded_at=float(payload.get("timestamp") or 0.0),
            )
            scan.events.append(
                ScannedEvent(raw=payload, normalized=normalized, relative_path=relative)
            )
    return scan
