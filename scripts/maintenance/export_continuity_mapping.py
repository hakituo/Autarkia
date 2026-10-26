#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导出 conversation → continuity 映射清单，供 spec §13-1 人工确认。

只读 chat_history 每个文件的首行（同一文件会话 ID 相同），不读正文。
默认写 ``output/evaluation/continuity_mapping.json``：
    venv_cpu\\Scripts\\python.exe scripts\\maintenance\\export_continuity_mapping.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, List

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.utils.data.data_paths import get_companion_data_dir  # noqa: E402
from core.utils.time.time_utils import now_iso  # noqa: E402
from memory.audit.report import discover_scope_dirs  # noqa: E402
from memory.topology.identity import continuity_mapping  # noqa: E402


def _first_conversation_id(path: Path) -> str:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                raw = line.strip()
                if not raw:
                    continue
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    return str(payload.get("conversation_id") or "").strip()
                return ""
    except (OSError, ValueError):
        return ""
    return ""


def collect_conversation_ids(chat_dirs: Iterable[Path]) -> List[str]:
    found: set[str] = set()
    for chat_dir in chat_dirs:
        if not chat_dir.exists():
            continue
        for path in sorted(chat_dir.rglob("*.jsonl")):
            conversation_id = _first_conversation_id(path)
            if not conversation_id:
                conversation_id = path.stem
            if conversation_id:
                found.add(conversation_id)
    return sorted(found)


def _print_summary(mapping: Dict[str, List[str]]) -> None:
    multi = {key: values for key, values in mapping.items() if len(values) > 1}
    print(f"[continuity] 分组={len(mapping)} 会话={sum(len(v) for v in mapping.values())}")
    for key, values in multi.items():
        print(f"  合并 {key}: {len(values)} 个会话")
    print(f"  多会话连续性组={len(multi)}（其余为单会话隔离）")


def main() -> int:
    parser = argparse.ArgumentParser(description="导出 continuity 映射清单")
    parser.add_argument("--data-root", default="", help="companion_data 根目录，默认自动解析")
    parser.add_argument("--out", default="", help="输出路径（默认 output/evaluation/）")
    args = parser.parse_args()

    data_root = Path(args.data_root) if args.data_root else Path(get_companion_data_dir())
    scope_dirs = discover_scope_dirs(data_root)
    conversation_ids = collect_conversation_ids(scope_dirs.values())
    mapping = continuity_mapping(conversation_ids)

    payload = {
        "generated_at": now_iso(),
        "data_root": str(data_root),
        "scope_count": len(scope_dirs),
        "conversation_count": len(conversation_ids),
        "groups": mapping,
        "note": "默认策略：同角色私聊共享 continuity；群聊 / peer / circle 各自隔离。确认前不要改语义。",
    }
    out_path = (
        Path(args.out)
        if args.out
        else Path("output") / "evaluation" / "continuity_mapping.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _print_summary(mapping)
    print(f"[报告] {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
