"""把纯新增符号移植接到同步流程。

``autoport`` 只算文本，本模块负责按漂移方向读文件、写文件并打印结果。
写操作失败或条件不满足时不改任何文件，交给 ``tasks`` 生成人工任务。
"""

from __future__ import annotations

from pathlib import Path

from scripts.sync.libs import autoport
from scripts.sync.libs.drift import LibDrift
from scripts.sync.libs.manifest import Manifest
from scripts.sync.libs.state import SyncState


def apply(
    manifest: Manifest,
    state: SyncState,
    drifts: list[LibDrift],
    *,
    dry_run: bool,
    allow_reverse: bool,
) -> tuple[list[str], list[str]]:
    """返回（主→库新增, 库→主新增）的说明列表。"""
    forward: list[str] = []
    reverse: list[str] = []
    for drift in drifts:
        for item in drift.files:
            if len(item.mapping.main) != 1:
                continue
            source_rel = item.mapping.main[0]
            if not (source_rel.endswith(".py") and item.mapping.lib.endswith(".py")):
                continue
            spec = item.spec
            main_path = manifest.project_root / source_rel
            lib_path = manifest.repo(spec) / item.mapping.lib
            if item.flag == "to_lib":
                target = _forward(state, spec.name, source_rel, main_path, lib_path, dry_run)
                if target:
                    forward.append(f"{spec.name}: {item.mapping.lib} ← {target}")
            elif item.flag == "to_main" and allow_reverse:
                target = _reverse(state, spec.name, item.mapping.lib, lib_path, main_path, dry_run)
                if target:
                    reverse.append(f"{spec.name}: {source_rel} ← {target}")
    return forward, reverse


def _forward(
    state: SyncState,
    lib: str,
    source_rel: str,
    main_path: Path,
    lib_path: Path,
    dry_run: bool,
) -> str:
    result = autoport.port_additions(
        state.read_base_main(lib, source_rel), _read(main_path), _read(lib_path)
    )
    return _finish(result, lib_path, f"{lib}/{Path(source_rel).name}", "主→库", dry_run)


def _reverse(
    state: SyncState,
    lib: str,
    lib_rel: str,
    lib_path: Path,
    main_path: Path,
    dry_run: bool,
) -> str:
    result = autoport.port_additions(
        state.read_base_lib(lib, lib_rel), _read(lib_path), _read(main_path)
    )
    return _finish(result, main_path, f"{lib}/{Path(lib_rel).name}", "库→主", dry_run)


def _finish(
    result: autoport.PortResult, target: Path, label: str, direction: str, dry_run: bool
) -> str:
    if not result.added:
        if result.reason.startswith(("没有新增", "目标已存在")):
            return ""
        print(f"[组件库] 自动移植跳过 {label}: {result.reason}")
        return ""
    names = ", ".join(result.added)
    if dry_run:
        print(f"[组件库] 自动移植（预演）{direction} {label}: 新增 {names}")
        return names
    try:
        target.write_text(result.text, encoding="utf-8", newline="\n")
    except OSError as exc:
        print(f"[组件库] 自动移植写入失败 {label}: {exc}")
        return ""
    print(f"[组件库] 自动移植 {direction} {label}: 新增 {names}")
    return names


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
