"""event_ref 回填执行：整批计划 + 备份 + 失败回滚（v3 D8）。

与 ``redistill_apply`` 同一套执行纪律：计划被阻断时不碰磁盘；逐文件原子写；
任一文件失败就把所有已写文件恢复到写入前内容。

只改 ``metadata.event_ref``，不碰 content / timestamp / id / summary。
脚本必须离线运行：服务进程在跑时，内存中的 manager 可能用旧快照覆盖回写。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from memory.maintenance.event_ref_backfill import BackfillItem, BackfillPlan


def apply_backfill_plan(
    plan: BackfillPlan,
    *,
    backup_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """把计划写入 weighted JSON；失败回滚并返回未提交。"""
    if plan.blocked:
        return _failure(list(plan.reasons) + ["计划被阻断，未写入"])

    writable = plan.writable
    if not writable:
        return {"committed": True, "updated": 0, "files": 0, "reasons": []}

    grouped: Dict[str, List[BackfillItem]] = {}
    for item in writable:
        grouped.setdefault(item.source.file_path, []).append(item)

    originals: Dict[str, str] = {}
    backup_manifest: Dict[str, str] = {}
    updated = 0
    try:
        for path in sorted(grouped):
            text = Path(path).read_text(encoding="utf-8")
            originals[path] = text
            data = json.loads(text)
            records = data.get("weighted_memories") if isinstance(data, dict) else None
            if not isinstance(records, list):
                raise ValueError(f"{path} 缺少 weighted_memories 列表")
            for item in grouped[path]:
                record = records[item.source.position]
                if not isinstance(record, dict):
                    raise ValueError(f"{path}#{item.source.position} 不是记录对象")
                metadata = record.get("metadata")
                if not isinstance(metadata, dict):
                    raise ValueError(f"{path}#{item.source.position} metadata 不是对象")
                metadata["event_ref"] = dict(item.target)
                updated += 1
            if backup_dir is not None:
                backup_manifest[path] = _write_backup(backup_dir, path, text)
            _safe_json_dump(data, path)
    except Exception as exc:  # noqa: BLE001 - 不留半批
        _restore(originals)
        return _failure([f"写入失败已回滚: {type(exc).__name__}: {exc}"])

    if backup_dir is not None and backup_manifest:
        _safe_json_dump(
            {"originals": dict(sorted(backup_manifest.items()))},
            str(Path(backup_dir) / "manifest.json"),
        )
    return {
        "committed": True,
        "updated": updated,
        "files": len(grouped),
        "reasons": [],
    }


def _safe_json_dump(data: Any, path: str) -> None:
    from core.utils.atomic_io import safe_json_dump

    safe_json_dump(data, path, encoding="utf-8")


def _write_backup(backup_dir: Path, path: str, text: str) -> str:
    target_dir = Path(backup_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(path.encode("utf-8")).hexdigest()[:12]
    backup_path = target_dir / f"{digest}_{Path(path).name}"
    backup_path.write_text(text, encoding="utf-8")
    return str(backup_path)


def _restore(originals: Mapping[str, str]) -> None:
    for path, text in originals.items():
        try:
            Path(path).write_text(text, encoding="utf-8")
        except Exception:  # noqa: BLE001 - 尽力恢复，失败由上层报告
            continue


def _failure(reasons: List[str]) -> Dict[str, Any]:
    return {
        "committed": False,
        "updated": 0,
        "files": 0,
        "reasons": reasons,
    }


__all__ = ["apply_backfill_plan"]
