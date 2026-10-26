"""对比主仓与组件库，判断哪一侧领先。

四种状态：

- ``baseline``：还没有基线（第一次运行），只记录不判定；
- ``to_lib``：主仓改了，组件库没改；
- ``to_main``：组件库改了，主仓没改（反向助推）；
- ``conflict``：两侧都改了，需要人工/agent 合并；
- ``in_sync``：与基线一致。
"""

from __future__ import annotations

from dataclasses import dataclass

from scripts.sync.libs.manifest import LibSpec, Manifest, Mapping
from scripts.sync.libs.state import FileRecord, SyncState, file_hash


@dataclass
class FileDrift:
    spec: LibSpec
    mapping: Mapping
    flag: str
    lib_hash: str
    main_hashes: dict[str, str]
    record: FileRecord | None

    @property
    def base_lib(self) -> str:
        return self.record.lib if self.record else ""

    @property
    def base_main(self) -> dict[str, str]:
        return self.record.main if self.record else {}

    @property
    def main_changed(self) -> bool:
        return self.flag in {"to_lib", "conflict"}

    @property
    def lib_changed(self) -> bool:
        return self.flag in {"to_main", "conflict"}


@dataclass
class LibDrift:
    spec: LibSpec
    files: list[FileDrift]

    def counts(self) -> dict[str, int]:
        result = {"to_lib": 0, "to_main": 0, "conflict": 0, "baseline": 0}
        for item in self.files:
            result[item.flag] = result.get(item.flag, 0) + 1
        return result

    @property
    def pending(self) -> bool:
        return any(item.flag in {"to_lib", "to_main", "conflict"} for item in self.files)

    def files_with(self, *flags: str) -> list[FileDrift]:
        return [item for item in self.files if item.flag in flags]


def compute_drift(manifest: Manifest, state: SyncState) -> list[LibDrift]:
    """逐个组件库计算文件级漂移。"""
    result: list[LibDrift] = []
    for spec in manifest.libs:
        repo = manifest.repo(spec)
        files: list[FileDrift] = []
        for mapping in spec.mappings:
            lib_path = repo / mapping.lib
            lib_hash = file_hash(lib_path)
            main_hashes = {
                source: file_hash(manifest.project_root / source) for source in mapping.main
            }
            record = state.get(spec.name, mapping.lib)
            files.append(
                FileDrift(
                    spec=spec,
                    mapping=mapping,
                    flag=_flag(record, main_hashes, lib_hash),
                    lib_hash=lib_hash,
                    main_hashes=main_hashes,
                    record=record,
                )
            )
        result.append(LibDrift(spec=spec, files=files))
    return result


def _flag(record: FileRecord | None, main_hashes: dict[str, str], lib_hash: str) -> str:
    if record is None:
        return "baseline"
    main_changed = any(
        main_hashes.get(path, "") != record.main.get(path, "") for path in main_hashes
    )
    lib_changed = lib_hash != record.lib
    if main_changed and lib_changed:
        return "conflict"
    if main_changed:
        return "to_lib"
    if lib_changed:
        return "to_main"
    return "in_sync"


def touched_names(manifest: Manifest, changed_main: list[str]) -> list[str]:
    return list(manifest.main_to_libs(changed_main).keys())


def describe(drifts: list[LibDrift]) -> list[str]:
    """生成人类可读的漂移摘要。"""
    lines: list[str] = []
    for drift in drifts:
        counts = drift.counts()
        if not drift.pending and not counts.get("baseline"):
            continue
        parts = [f"主→库={counts.get('to_lib', 0)}", f"库→主={counts.get('to_main', 0)}"]
        if counts.get("conflict"):
            parts.append(f"冲突={counts['conflict']}")
        if counts.get("baseline"):
            parts.append(f"未建基线={counts['baseline']}")
        lines.append(f"{drift.spec.name}: " + "，".join(parts))
    return lines
