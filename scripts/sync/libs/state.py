"""组件库同步基线。

记录「上一次双方一致时」的文件哈希，并保留当时的文件内容：

- 哈希用来判断是哪一边先动的手（主仓动了 / 组件库动了 / 两边都动了）；
- 内容快照用来在生成移植任务时给出真正的 before/after diff。

状态文件默认放在 Windows 分区的 ``.sync-state`` 下，双系统共用同一份基线。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from scripts.sync.libs.manifest import LibSpec, Manifest, Mapping

SCHEMA_VERSION = 1


def file_hash(path: Path) -> str:
    """返回文件内容哈希；文件不存在返回空串。

    文本文件先统一 CRLF/CR 为 LF：双系统（Windows 检出 CRLF、Linux 检出 LF）
    共用同一份基线，不能因为换行符不同就误判成「文件被改了」。
    """
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if b"\0" not in data:
        data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


@dataclass
class FileRecord:
    """一个组件库文件的同步基线。"""

    main: dict[str, str] = field(default_factory=dict)
    lib: str = ""
    synced_at: str = ""

    def to_dict(self) -> dict:
        return {"main": dict(self.main), "lib": self.lib, "synced_at": self.synced_at}

    @classmethod
    def from_dict(cls, raw: dict) -> FileRecord:
        return cls(
            main={str(key): str(value) for key, value in (raw.get("main") or {}).items()},
            lib=str(raw.get("lib", "")),
            synced_at=str(raw.get("synced_at", "")),
        )


class SyncState:
    """读写 ``.sync-state/state.json`` 与 base 快照。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "state.json"
        self.data: dict = {"schema": SCHEMA_VERSION, "files": {}, "heads": {}, "versions": {}}

    def load(self) -> SyncState:
        if not self.path.exists():
            return self
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self
        if int(raw.get("schema", 0)) == SCHEMA_VERSION:
            self.data = raw
            self.data.setdefault("files", {})
            self.data.setdefault("heads", {})
            self.data.setdefault("versions", {})
        return self

    def save(self) -> None:
        self.data["schema"] = SCHEMA_VERSION
        self.data["updated_at"] = _now()
        _atomic_write(self.path, json.dumps(self.data, ensure_ascii=False, indent=2) + "\n")

    def get(self, lib: str, lib_file: str) -> FileRecord | None:
        raw = self.data.get("files", {}).get(lib, {}).get(lib_file)
        return FileRecord.from_dict(raw) if isinstance(raw, dict) else None

    def set(self, lib: str, lib_file: str, record: FileRecord) -> None:
        self.data.setdefault("files", {}).setdefault(lib, {})[lib_file] = record.to_dict()

    def head(self, lib: str) -> str:
        return str(self.data.get("heads", {}).get(lib, ""))

    def set_head(self, lib: str, head: str) -> None:
        self.data.setdefault("heads", {})[lib] = head

    def version(self, lib: str) -> str:
        return str(self.data.get("versions", {}).get(lib, ""))

    def set_version(self, lib: str, version: str) -> None:
        self.data.setdefault("versions", {})[lib] = version

    # ---- base 快照 -------------------------------------------------

    def base_lib_path(self, lib: str, lib_file: str) -> Path:
        return self.root / "base" / lib / "lib" / lib_file

    def base_main_path(self, lib: str, main_file: str) -> Path:
        return self.root / "base" / lib / "main" / main_file

    def read_base_lib(self, lib: str, lib_file: str) -> str:
        return _read_text(self.base_lib_path(lib, lib_file))

    def read_base_main(self, lib: str, main_file: str) -> str:
        return _read_text(self.base_main_path(lib, main_file))

    def record_mapping(
        self,
        spec: LibSpec,
        mapping: Mapping,
        lib_repo: Path,
        project_root: Path,
    ) -> None:
        """把当前文件内容记录为新基线。"""
        lib_path = lib_repo / mapping.lib
        main_hashes: dict[str, str] = {}
        for main_file in mapping.main:
            source = project_root / main_file
            main_hashes[main_file] = file_hash(source)
            if source.is_file():
                _copy(source, self.base_main_path(spec.name, main_file))
        if lib_path.is_file():
            _copy(lib_path, self.base_lib_path(spec.name, mapping.lib))
        self.set(
            spec.name,
            mapping.lib,
            FileRecord(main=main_hashes, lib=file_hash(lib_path), synced_at=_now()),
        )

    def record_all(self, manifest: Manifest, lib_repo: Path, spec: LibSpec) -> None:
        for mapping in spec.mappings:
            self.record_mapping(spec, mapping, lib_repo, manifest.project_root)
        self.set_head(spec.name, _git_head(lib_repo))
        if spec.pypi:
            version = _read_version(lib_repo)
            if version:
                self.set_version(spec.name, version)
        self.save()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _read_version(repo: Path) -> str:
    try:
        text = (repo / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return ""
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else ""


def _git_head(repo: Path) -> str:
    import subprocess

    proc = subprocess.run(
        ["git", "-c", f"safe.directory={repo}", "rev-parse", "HEAD"],
        check=False,
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""
