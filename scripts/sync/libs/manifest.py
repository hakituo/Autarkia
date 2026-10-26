"""组件库同步清单：主仓源文件与组件库文件的唯一映射表。

清单真源是 ``config/libs_sync.json``。脚本、验证脚本和文档都从这里读，
不要在别处再维护一份路径表。

``published`` 为真表示该库有 GitHub 远端并已发布到 PyPI；
``unpublished/`` 下的库只在磁盘两侧同步，不推送远端。
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
ENV_ROOT = "AUTARKIA_LIBS_ROOT"
ENV_STATE = "AUTARKIA_LIBS_SYNC_STATE"
DEFAULT_MANIFEST = "config/libs_sync.json"


class ManifestError(RuntimeError):
    """清单缺失或结构不合法。"""


@dataclass(frozen=True)
class Mapping:
    """一个组件库文件对应的主仓源文件（可能一对多）。"""

    lib: str
    main: tuple[str, ...]


@dataclass(frozen=True)
class LibSpec:
    """一个组件库仓库的同步配置。"""

    name: str
    path: str
    published: bool
    pypi: bool
    mappings: tuple[Mapping, ...]


@dataclass(frozen=True)
class Manifest:
    """解析后的同步清单与路径。"""

    libs: tuple[LibSpec, ...]
    project_root: Path
    libs_root: Path
    peer_root: Path | None
    state_dir: Path

    def get(self, name: str) -> LibSpec:
        for spec in self.libs:
            if spec.name == name:
                return spec
        raise ManifestError(f"未知组件库: {name}")

    def names(self) -> list[str]:
        return [spec.name for spec in self.libs]

    def repo(self, spec: LibSpec) -> Path:
        return self.libs_root / spec.path

    def peer_repo(self, spec: LibSpec) -> Path | None:
        if self.peer_root is None:
            return None
        return self.peer_root / spec.path

    def main_to_libs(self, changed: Iterable[str]) -> dict[str, list[Mapping]]:
        """把主仓变更文件映射到受影响的组件库。"""
        normalized = {_norm(path) for path in changed}
        hits: dict[str, list[Mapping]] = {}
        for spec in self.libs:
            for mapping in spec.mappings:
                if any(_norm(source) in normalized for source in mapping.main):
                    hits.setdefault(spec.name, []).append(mapping)
        return hits


def project_root() -> Path:
    """返回主仓根目录（本文件位于 scripts/sync/libs/ 下）。"""
    return Path(__file__).resolve().parents[3]


def _norm(path: str) -> str:
    return str(path).replace("\\", "/").strip().lstrip("./")


def _windows_to_posix(raw: str, mount: str) -> Path:
    """把 ``D:\\AI\\Autarkia-Libs`` 映射到 ``/mnt/win_p4/AI/Autarkia-Libs``。"""
    _, _, rest = str(raw).partition(":")
    return Path(mount) / rest.replace("\\", "/").lstrip("/")


def _resolve_libs_root(data: dict[str, Any], root: Path) -> Path:
    override = os.environ.get(ENV_ROOT, "").strip()
    if override:
        return Path(override).expanduser()
    key = "windows" if os.name == "nt" else "linux"
    raw = data.get("libs_roots", {}).get(key)
    if not raw:
        raise ManifestError(f"清单缺少 libs_roots.{key}")
    return Path(str(raw)).expanduser()


def _resolve_peer_root(data: dict[str, Any]) -> Path | None:
    """Windows 侧读不到 Linux 的 ext4，因此只有 Linux 侧存在对端。"""
    if os.name == "nt":
        return None
    raw = data.get("libs_roots", {}).get("windows")
    mount = data.get("windows_mount")
    if not raw or not mount:
        return None
    peer = _windows_to_posix(str(raw), str(mount))
    return peer if peer.parent.exists() else None


def _resolve_state_dir(data: dict[str, Any], libs_root: Path, peer: Path | None) -> Path:
    override = os.environ.get(ENV_STATE, "").strip()
    if override:
        return Path(override).expanduser()
    # 状态放在 Windows 分区，双系统共用同一份基线；挂载缺失时才退回本地。
    if peer is not None:
        return peer / ".sync-state"
    return libs_root / ".sync-state"


def _parse_mapping(raw: dict[str, Any], lib_name: str) -> Mapping:
    lib_file = _norm(str(raw.get("lib", "")))
    sources = raw.get("main") or []
    if not lib_file or not isinstance(sources, list) or not sources:
        raise ManifestError(f"{lib_name}: 映射项缺少 lib/main")
    return Mapping(lib=lib_file, main=tuple(_norm(str(item)) for item in sources))


def _parse_spec(raw: dict[str, Any]) -> LibSpec:
    name = str(raw.get("name", "")).strip()
    path = _norm(str(raw.get("path", "")))
    if not name or not path:
        raise ManifestError("组件库项缺少 name/path")
    mappings = tuple(_parse_mapping(item, name) for item in raw.get("mappings", []))
    if not mappings:
        raise ManifestError(f"{name}: mappings 不能为空")
    return LibSpec(
        name=name,
        path=path,
        published=bool(raw.get("published", False)),
        pypi=bool(raw.get("pypi", False)),
        mappings=mappings,
    )


def load_manifest(path: Path | None = None, root: Path | None = None) -> Manifest:
    """读取并校验清单；路径默认相对主仓根目录。"""
    root = root or project_root()
    manifest_path = path or root / DEFAULT_MANIFEST
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManifestError(f"找不到同步清单: {manifest_path}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"清单不是合法 JSON: {manifest_path}: {exc}") from exc
    if int(data.get("schema", 0)) != SCHEMA_VERSION:
        raise ManifestError(f"清单 schema 必须为 {SCHEMA_VERSION}")
    libs = tuple(_parse_spec(item) for item in data.get("libs", []))
    if not libs:
        raise ManifestError("清单里没有任何组件库")
    libs_root = _resolve_libs_root(data, root)
    peer = _resolve_peer_root(data)
    return Manifest(
        libs=libs,
        project_root=root,
        libs_root=libs_root,
        peer_root=peer,
        state_dir=_resolve_state_dir(data, libs_root, peer),
    )
