#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""备份数据层：清单 / 排除 / 增量拷贝 / 快照保留策略。

只回答「备份哪些、跳过哪些、怎么拷」；编排与命令行入口在 ``auto_backup.py``。
实现只用标准库与 ``pathlib``，Windows / Linux 通用。
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, List, Sequence

#: 目录级排除（按目录名，任意层级命中即整棵剪枝）
EXCLUDE_DIR_NAMES = frozenset({
    "indexes",  # SQLite 派生索引，程序启动后按真源自动重建
    "cache",  # 缓存目录
    "temp",  # 运行临时目录
    "backups",  # 程序自带的一次性 zip 备份，不与本备份叠加
    "chromadb_store",  # 向量库，可由原始数据重建
    "chroma",
    "__pycache__",
    ".git",
    "node_modules",
    ".venv",
    "venv_cpu",
    "venv_core",
    "venv_linux",
})

#: 文件级排除（后缀）：SQLite 派生库、锁文件、传输 / 拷贝临时文件
EXCLUDE_SUFFIXES = (
    ".db",
    ".db-wal",
    ".db-shm",
    ".lock",
    ".tmp",
    ".sync-tmp",
    ".backup-tmp",
)

#: 仓库内整树备份的运行时数据（相对仓库根）
DATA_TREES = ("companion_data", "output", "data")

#: 散落文件白名单（相对仓库根的 glob；命中文件按同相对路径收进 files/）。
#: 这些是 git 忽略、丢了没有第二份的隐私配置与本地资料。
FILE_PATTERNS = (
    ".env*",
    "config/qweather_private_key.pem",
    "clients/bots/config.json",
    "clients/bots/config_official*.json",
    "clients/bots/qq_bot_config.json",
    "clients/bots/multi_qq_config.json",
    "clients/bots/qq/sensitive_paths.py",
    "clients/bots/telegram/sensitive_media.py",
    "scripts/publish/publish_whitelist.json",
    "scripts/publish/audit_rules.json",
    "core/character/configs/extra/**/distilled_profile.md",
    "Lin-完整人设.md",
)

#: 快照目录命名（只清理这个形状的目录）
SNAPSHOT_RE = re.compile(r"^\d{4}-\d{2}$")
#: mtime 比较容差（秒）：跨文件系统的时间精度不同（FAT 为 2 秒）
MTIME_TOLERANCE = 2.0


def log_line(message: str) -> None:
    """统一输出前缀，便于在日志里检索。"""
    print(f"[backup] {message}")


@dataclass
class Stats:
    """一次备份的累计统计。"""

    copied: int = 0
    skipped: int = 0
    bytes_copied: int = 0
    removed_snapshots: List[str] = field(default_factory=list)
    failures: List[str] = field(default_factory=list)


def iter_tree_files(root: Path) -> Iterator[Path]:
    """遍历 root 下的文件，跳过排除目录与排除后缀（目录名剪枝，不进入）。"""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIR_NAMES)
        for name in sorted(filenames):
            if name.endswith(EXCLUDE_SUFFIXES):
                continue
            yield Path(dirpath) / name


def _same_file(src: Path, dst: Path) -> bool:
    """目标已有一份同源文件（大小一致且 mtime 在容差内）。"""
    try:
        s = src.stat()
        d = dst.stat()
    except OSError:
        return False
    return d.st_size == s.st_size and abs(d.st_mtime - s.st_mtime) <= MTIME_TOLERANCE


def _copy_one(src: Path, dst: Path, stats: Stats, *, apply: bool) -> None:
    """备份单个文件：已一致则跳过，否则在 apply 模式下原子拷贝。

    dry-run 也累计字节数，便于落盘前预估体积。
    """
    if _same_file(src, dst):
        stats.skipped += 1
        return
    try:
        size = src.stat().st_size
    except OSError as exc:
        stats.failures.append(f"{src}: {exc}")
        return
    if apply:
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(dst.name + ".backup-tmp")
            shutil.copy2(src, tmp)  # copy2 保留 mtime，增量判断依赖它
            os.replace(tmp, dst)
        except OSError as exc:
            stats.failures.append(f"{src}: {exc}")
            return
    stats.bytes_copied += size
    stats.copied += 1


def backup_tree(src: Path, dst: Path, stats: Stats, *, apply: bool) -> int:
    """整树增量备份，返回本次复制的文件数。"""
    before = stats.copied
    for path in iter_tree_files(src):
        _copy_one(path, dst / path.relative_to(src), stats, apply=apply)
    return stats.copied - before


def match_pattern_files(
    repo_root: Path, patterns: Sequence[str] = FILE_PATTERNS
) -> List[Path]:
    """按白名单 glob 收集散落文件；跳过 .example 模板，命中去重。"""
    found: List[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        for path in sorted(repo_root.glob(pattern)):
            if not path.is_file() or path.name.endswith(".example") or path in seen:
                continue
            seen.add(path)
            found.append(path)
    return found


def backup_files(
    repo_root: Path,
    dst: Path,
    stats: Stats,
    *,
    apply: bool,
    patterns: Sequence[str] = FILE_PATTERNS,
) -> int:
    """备份白名单散落文件到 dst（保持相对仓库根的子路径）。"""
    before = stats.copied
    for path in match_pattern_files(repo_root, patterns):
        _copy_one(path, dst / path.relative_to(repo_root), stats, apply=apply)
    return stats.copied - before


def prune_snapshots(dest: Path, keep: int, *, apply: bool) -> List[str]:
    """只保留最近 keep 个 YYYY-MM 快照目录；返回被删（或计划删）的目录名。"""
    if keep <= 0 or not dest.is_dir():
        return []
    months = sorted(
        (p for p in dest.iterdir() if p.is_dir() and SNAPSHOT_RE.match(p.name)),
        key=lambda p: p.name,
    )
    removed: List[str] = []
    for path in months[:-keep]:
        if apply:
            shutil.rmtree(path)
        removed.append(path.name)
    return removed


def guard_dest(dest: Path, sources: Iterable[Path]) -> None:
    """备份根不能位于任何被备份目录内部，否则会把备份自己再备份进去。"""
    resolved = dest.resolve()
    for src in sources:
        if not src.is_dir():
            continue
        src_resolved = src.resolve()
        if resolved == src_resolved or src_resolved in resolved.parents:
            raise ValueError(f"备份根 {dest} 位于被备份目录 {src} 内部，请更换位置")
