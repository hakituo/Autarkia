#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行时数据自动备份：按月快照到仓库外的备份根，保留最近 N 份。

git 里有的（代码 / 人设 / 语料）不需要本脚本操心 —— origin-private 本身就是
异地副本；git 之外、丢了不可再生的运行时数据才是备份对象：

    <备份根>/YYYY-MM/
      companion_data/   各角色聊天 / 记忆 / 作息 / 用户数据
      output/           背单词进度与生成媒体（排除 cache）
      data/             学习数据 / 表情包 / 素材（排除 chromadb 向量库）
      Study/            学习库（仓库外，默认取 <仓库父目录>/Study）
      files/            散落配置与隐私文件，按「相对仓库根」的路径存放
                        （.env / 密钥 / bot 配置 / 发布白名单 / 月度蒸馏记忆）

行为约定：
- 同一月份重复运行是增量刷新：size + mtime（2 秒容差）相同即跳过；
- 只保留最近 --keep 个「YYYY-MM」命名的快照目录，更老的整目录删除；
- 默认 dry-run 只出计划，确认后加 --apply 才真正落盘（与同步脚本一致）；
- 清理动作只认 YYYY-MM 命名的目录，别的手工目录一律不碰。

建议在程序停止时运行（避免抓到写一半的文件）。恢复方式：把快照目录下的
companion_data / output / data / Study 拷回原位置，files/ 按其中保留的相对
路径逐个还原即可。

用法::

    python scripts/backup/auto_backup.py                      # dry-run 出计划
    python scripts/backup/auto_backup.py --dest G:/Autarkia-backup --apply
    python scripts/daily/daily.py backup --dest G:/Autarkia-backup --apply
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:  # 支持直接执行本文件（不依赖调用方 cwd）
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.backup.snapshot import (  # noqa: E402
    DATA_TREES,
    Stats,
    backup_files,
    backup_tree,
    guard_dest,
    log_line,
    prune_snapshots,
)

#: 备份根默认值：命令行 --dest > 环境变量（新名优先、旧名兼容）> <仓库父目录>/Autarkia-backup
DEST_ENV = "AUTARKIA_BACKUP_ROOT"
DEST_ENV_LEGACY = "XIAOYOU_BACKUP_ROOT"
#: 学习库根覆盖（默认 <仓库父目录>/Study，与跨平台镜像表的默认一致）
STUDY_ENV = "AUTARKIA_STUDY_ROOT"
STUDY_ENV_LEGACY = "XIAOYOU_STUDY_ROOT"

#: 默认保留的快照月份数
DEFAULT_KEEP = 6


def run_backup(
    *,
    dest: Path,
    repo_root: Path = _REPO_ROOT,
    study_root: Optional[Path] = None,
    keep: int = DEFAULT_KEEP,
    apply: bool = False,
    now: Optional[datetime] = None,
) -> Stats:
    """执行一次备份，返回统计；退出码由 ``main`` 决定。"""
    month = (now or datetime.now()).strftime("%Y-%m")
    snapshot = dest / month

    trees = [repo_root / name for name in DATA_TREES]
    if study_root is not None:
        trees.append(study_root)
    guard_dest(dest, trees)

    log_line(f"仓库根：{repo_root}")
    log_line(f"备份根：{dest}")
    log_line(f"快照目录：{snapshot}")
    log_line(f"模式：{'实拷贝' if apply else 'dry-run（只出计划，加 --apply 落盘）'}")

    stats = Stats()
    started = time.monotonic()

    for src in trees:
        if not src.is_dir():
            log_line(f"{src}：不存在，跳过")
            continue
        count = backup_tree(src, snapshot / src.name, stats, apply=apply)
        log_line(f"{src.name}：本次复制 {count} 个文件")

    count = backup_files(repo_root, snapshot / "files", stats, apply=apply)
    log_line(f"files（散落配置）：本次复制 {count} 个文件")

    stats.removed_snapshots = prune_snapshots(dest, keep, apply=apply)
    if stats.removed_snapshots:
        action = "已删除" if apply else "将删除（dry-run）"
        log_line(f"{action}超期快照：{', '.join(stats.removed_snapshots)}")
    else:
        log_line(f"保留策略：无需清理（keep={keep}）")

    elapsed = time.monotonic() - started
    log_line(
        f"完成：复制 {stats.copied} 个（{stats.bytes_copied / 1024 / 1024:.1f} MB），"
        f"跳过 {stats.skipped} 个，失败 {len(stats.failures)} 个，用时 {elapsed:.1f}s"
    )
    for item in stats.failures:
        log_line(f"失败：{item}")
    return stats


def env_first(primary: str, legacy: str) -> str:
    """读环境变量：新名优先，回退旧名，都没设时返回空串。"""
    return (os.environ.get(primary) or os.environ.get(legacy) or "").strip()


def _default_dest() -> str:
    """备份根默认值：环境变量优先，否则放仓库父目录旁的 Autarkia-backup。"""
    return env_first(DEST_ENV, DEST_ENV_LEGACY) or str(_REPO_ROOT.parent / "Autarkia-backup")


def _default_study_root() -> Path:
    """学习库默认位置：与跨平台镜像表一致（仓库父目录下的 Study）。"""
    return Path(env_first(STUDY_ENV, STUDY_ENV_LEGACY) or (_REPO_ROOT.parent / "Study"))


def build_parser() -> argparse.ArgumentParser:
    """命令行参数（默认 dry-run，--apply 才落盘）。"""
    parser = argparse.ArgumentParser(
        prog="auto_backup.py",
        description="运行时数据按月快照备份（默认 dry-run，--apply 落盘）",
    )
    parser.add_argument(
        "--dest",
        default=_default_dest(),
        help="备份根目录（默认 %(default)s，可用环境变量 AUTARKIA_BACKUP_ROOT 覆盖）",
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=DEFAULT_KEEP,
        help="保留最近 N 个月份快照，0 表示不清理（默认 %(default)s）",
    )
    parser.add_argument(
        "--study-root",
        default=str(_default_study_root()),
        help="学习库根目录，不存在则跳过（默认 %(default)s）",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真正落盘；缺省只出计划不写文件",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI 入口：0 成功、1 有失败项、2 参数 / 位置错误。"""
    args = build_parser().parse_args(argv)

    study_root: Optional[Path] = Path(args.study_root).expanduser()
    if not study_root.is_dir():
        log_line(f"学习库不存在，跳过：{study_root}")
        study_root = None

    try:
        stats = run_backup(
            dest=Path(args.dest).expanduser(),
            study_root=study_root,
            keep=args.keep,
            apply=args.apply,
        )
    except ValueError as exc:
        log_line(f"错误：{exc}")
        return 2
    return 1 if stats.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
