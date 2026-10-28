#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""双系统代码同步：走本地磁盘，不依赖 GitHub Actions。

Windows / Linux 双启动、同一时刻只有一个系统在线，所以「push 触发 → 另一台
runner 来拉」注定在对方离线时入队、排队到 24 小时过期；而两个方向天生不对称：
Linux 读得到 Windows 的 NTFS 分区，Windows 读不了 Linux 的 ext4。

- ``pull``（两边都跑）：fetch 后只做 ``--ff-only``。Linux 的对端是 Windows 工作
  副本（连它没推到 GitHub 的提交也能拿到），Windows 的对端是同盘裸仓库 hub。
- ``push``（只在 Linux 跑）：把本机提交写进 hub，供 Windows 下次启动时拉。

GitHub（``origin-private``）仍是备份 / 发布 / 部署源，不参与双机同步。
退出码：0 已同步或无需同步；2 被本地改动或分叉挡住（可重试）；1 真错误。
调用方（``start.sh`` / ``start.bat``）一律按「不阻塞启动」处理：非零只警告。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Optional

MAIN_REF = "refs/heads/main"
SYNC_REMOTE = "autarkia-sync"
#: 兼容旧引用；pull 现在按来源各用一个 ref，避免后一次 fetch 覆盖前一次
SYNC_REF = f"refs/remotes/{SYNC_REMOTE}/main"

#: 环境变量新名优先、旧名兼容（Linux /etc/environment 可能仍是旧写法）
ENV_HUB, ENV_HUB_LEGACY = "AUTARKIA_CODE_HUB", "XIAOYOU_CODE_HUB"
ENV_PEER, ENV_PEER_LEGACY = "AUTARKIA_CODE_PEER", "XIAOYOU_CODE_PEER"
ENV_SYNC, ENV_SYNC_LEGACY = "AUTARKIA_SYNC_CODE", "XIAOYOU_SYNC_CODE"

DEFAULT_WIN_HUB = Path(r"D:\projects\autarkia-hub.git")
DEFAULT_LINUX_HUB = Path("/mnt/win_p4/AI/Autarkia-hub.git")
DEFAULT_LINUX_PEER = Path("/mnt/win_p4/AI/Autarkia")

RC_OK = 0
RC_ERROR = 1
RC_PENDING = 2


def is_windows() -> bool:
    """当前是否运行在 Windows 侧。"""
    return os.name == "nt"


def project_root() -> Path:
    """返回仓库根目录（本文件位于 scripts/sync/ 下）。"""
    return Path(__file__).resolve().parents[2]


def default_hub() -> Path:
    """同盘裸仓库默认路径：Windows 用盘符，Linux 用挂载点。"""
    env = (os.environ.get(ENV_HUB) or os.environ.get(ENV_HUB_LEGACY) or "").strip()
    if env:
        return Path(env).expanduser()
    return DEFAULT_WIN_HUB if is_windows() else DEFAULT_LINUX_HUB


def default_peer() -> Optional[Path]:
    """对端工作副本：只有 Linux 读得到 Windows，反方向返回 None。"""
    env = (os.environ.get(ENV_PEER) or os.environ.get(ENV_PEER_LEGACY) or "").strip()
    if env:
        return Path(env).expanduser()
    return None if is_windows() else DEFAULT_LINUX_PEER


def run_git(
    repo: Path, *args: str, safe: Iterable[Path] = ()
) -> subprocess.CompletedProcess[str]:
    """在 ``repo`` 里执行 git。

    ntfs-3g 挂出来的文件属主是 root，直接访问会触发 ``dubious ownership``，
    因此把主仓库与被读取的对端仓库都通过 ``-c safe.directory`` 放行，
    不改用户全局配置。
    """
    cmd = ["git"]
    for path in sorted({str(repo), *(str(item) for item in safe)}):
        cmd += ["-c", f"safe.directory={path}"]
    cmd += ["-c", "core.quotepath=false", *args]
    return subprocess.run(
        cmd,
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def git_out(repo: Path, *args: str, safe: Iterable[Path] = ()) -> str:
    """执行 git 并返回去尾空白的 stdout（失败返回空串）。"""
    proc = run_git(repo, *args, safe=safe)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def rev(repo: Path, ref: str) -> str:
    """解析引用为提交号；不存在返回空串。"""
    return git_out(repo, "rev-parse", "--verify", "--quiet", ref)


def is_ancestor(repo: Path, older: str, newer: str) -> bool:
    """``older`` 是否为 ``newer`` 的祖先。"""
    return run_git(repo, "merge-base", "--is-ancestor", older, newer).returncode == 0


def current_branch(repo: Path) -> str:
    """当前分支名；detached 时返回 HEAD 之外的值，调用方自行判断。"""
    return git_out(repo, "rev-parse", "--abbrev-ref", "HEAD")


def fetch_from(repo: Path, source: Path, ref: str = SYNC_REF) -> bool:
    """从本地路径 fetch 对方的 main，落到指定的远端跟踪引用。

    ``ref`` 由调用方按来源区分：peer 与 hub 各用一个，否则拉完 hub 会把
    peer 的结果冲掉，日志里先「无法快进」再「已是最新」，自相矛盾。
    """
    proc = run_git(
        repo,
        "fetch",
        "--no-tags",
        str(source),
        f"+{MAIN_REF}:{ref}",
        safe=[source],
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        print(f"[WARN] 从 {source} 拉取失败：{detail[-1] if detail else '未知原因'}")
        return False
    return True


def blocked_files(repo: Path, target: str) -> list[str]:
    """列出真正挡住快进的文件：对端要改、本机又有未提交改动的交集。

    直接打印整份 ``git status`` 没用 —— 双系统并存时本机常有上百个无关改动，
    真正挡路的往往只有一两个，混在里头看不出来。
    """
    incoming = set(git_out(repo, "diff", "--name-only", "HEAD", target).splitlines())
    if not incoming:
        return []
    local = set(git_out(repo, "diff", "--name-only", "HEAD").splitlines())
    return sorted(incoming & local)


def merge_fast_forward(repo: Path, ref: str = SYNC_REF) -> int:
    """把 ``ref`` 快进到当前分支；不能快进时如实说明原因。"""
    head = rev(repo, "HEAD")
    if not head:
        print("[INFO] 本机仓库还没有提交，跳过合并")
        return RC_OK
    target = rev(repo, ref)
    if not target:
        print("[INFO] 对端还没有 main 分支，跳过")
        return RC_OK
    if head == target:
        print("[PASS] 已是最新，无需合并")
        return RC_OK
    if is_ancestor(repo, target, head):
        print("[INFO] 本机领先对端，无需合并")
        return RC_OK
    if not is_ancestor(repo, head, target):
        print("[WARN] 与对端已分叉（两端各有独有提交），需人工处理；对端新增：")
        print(git_out(repo, "log", "--oneline", "--max-count=5", f"{head}..{target}"))
        return RC_PENDING

    proc = run_git(repo, "merge", "--ff-only", ref)
    if proc.returncode != 0:
        print("[WARN] 无法快进：本地改动挡住了这次合并，提交或还原后下次自动重试")
        blocked = blocked_files(repo, target)
        for path in blocked:
            print(f"       挡住：{path}")
        if not blocked:
            # 交集为空说明挡路的不是已跟踪改动（如未跟踪文件与对端新文件同名），
            # 这时只能给出 git 自己的最后一句。
            detail = (proc.stderr or proc.stdout).strip().splitlines()
            print(f"       {detail[-1] if detail else '未知原因'}")
        return RC_PENDING
    print(f"[PASS] 已快进 {head[:7]} -> {target[:7]}")
    return RC_OK


def do_pull(repo: Path, hub: Path, peer: Optional[Path]) -> int:
    """按「对端工作副本 → 同盘 hub」的顺序各拉一次，每次都尝试快进。"""
    branch = current_branch(repo)
    if branch != "main":
        print(f"[INFO] 当前分支 {branch or '(detached)'} 不是 main，跳过代码同步")
        return RC_OK

    sources = [
        (label, path)
        for label, path in (("peer", peer), ("hub", hub))
        if path is not None and path.exists() and path.resolve() != repo.resolve()
    ]
    if not sources:
        print("[INFO] 没有可用的对端仓库（首次使用需先建同盘 hub），跳过")
        return RC_OK

    pending = False
    for label, source in sources:
        # 先确认它真是 git 仓库：分区挂错 / 路径写错时不能报成「没有 main 分支」，
        # 那会让人以为同步正常、只是对端还没提交。
        if run_git(source, "rev-parse", "--git-dir").returncode != 0:
            print(f"[WARN] {source} 不是 git 仓库（分区挂错或路径写错？），跳过")
            continue
        if not rev(source, MAIN_REF):
            print(f"[INFO] {source} 还没有 main 分支，跳过")
            continue
        # 每个来源一个 ref：共用一个的话，hub 拉完会把 peer 的 fetch 结果冲掉。
        ref = f"refs/remotes/{SYNC_REMOTE}/{label}"
        if not fetch_from(repo, source, ref):
            continue
        print(f"[INFO] 已从 {source} 获取提交")
        if merge_fast_forward(repo, ref) == RC_PENDING:
            pending = True
    return RC_PENDING if pending else RC_OK


def do_push(repo: Path, hub: Path) -> int:
    """把本机 main 写进同盘 hub（供 Windows 侧下次启动时拉取）。"""
    branch = current_branch(repo)
    if branch != "main":
        print(f"[INFO] 当前分支 {branch or '(detached)'} 不是 main，跳过代码回写")
        return RC_OK

    head = rev(repo, "HEAD")
    if not head:
        print("[WARN] 仓库还没有提交，跳过代码回写")
        return RC_OK

    # hub 被指到本仓库自身时直接退出：git 不允许往自己身上回收推送，
    # 报错信息也看不出根因，不如自己拦掉。
    if hub.resolve() == repo.resolve():
        print(f"[WARN] hub 指向本仓库自身（{ENV_HUB} 配置有误），跳过代码回写")
        return RC_OK

    if not hub.exists():
        # 父目录不存在说明 Windows 数据盘没挂上（开机时很常见），跳过而非报错。
        if not hub.parent.is_dir():
            print(f"[INFO] hub 所在目录不可用（{hub.parent}），跳过代码回写")
            return RC_OK
        print(f"[INFO] hub 不存在，初始化裸仓库：{hub}")
        proc = run_git(repo, "init", "--bare", str(hub))
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip().splitlines()
            print(f"[ERROR] 创建 hub 失败：{detail[-1] if detail else '未知原因'}")
            return RC_ERROR

    # safe 里带上 hub：本地推送会起 receive-pack，它同样做 dubious ownership 检查
    # （Linux 侧 hub 在 ntfs-3g 上属主是 root）。
    proc = run_git(repo, "push", str(hub), f"{MAIN_REF}:{MAIN_REF}", safe=[hub])
    if proc.returncode != 0:
        print("[WARN] 回写 hub 失败（多为 hub 上有本机没有的提交，先跑一次 pull）")
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        for line in detail[-3:]:
            print(f"       {line}")
        return RC_PENDING

    print(f"[PASS] 已把 {head[:7]} 写入 {hub}")
    return RC_OK


def do_status(repo: Path, hub: Path, peer: Optional[Path]) -> int:
    """只报告各端位置，不动任何工作区。"""
    print(f"仓库        : {repo}")
    print(f"当前分支    : {current_branch(repo)}")
    print(f"HEAD        : {rev(repo, 'HEAD')[:7] or '(空)'}")
    for label, path in (("对端工作副本", peer), ("同盘 hub", hub)):
        if path is None:
            print(f"{label}  : 不适用（当前系统读不到对端）")
        elif not path.exists():
            print(f"{label}  : 不存在 {path}")
        else:
            sha = rev(path, MAIN_REF)
            print(f"{label}  : {path} -> {sha[:7] if sha else '(无 main)'}")
    return RC_OK


def main(argv: list[str] | None = None) -> int:
    # 关闭开关统一在这里判断：start.bat 只留一行调用，判断全交给这里
    # （批处理里不能写中文，多字节内容会让 cmd 在 chcp 65001 之后错位）。
    if (os.environ.get(ENV_SYNC) or os.environ.get(ENV_SYNC_LEGACY) or "").strip() == "0":
        print(f"[INFO] {ENV_SYNC}=0，跳过代码同步")
        return RC_OK

    parser = argparse.ArgumentParser(
        prog="code_sync.py",
        description="双系统代码同步（本地磁盘通道，不依赖 GitHub Actions）",
    )
    parser.add_argument("action", choices=["pull", "push", "status"], help="要执行的动作")
    parser.add_argument("--repo", help="仓库路径，默认本项目根")
    parser.add_argument("--hub", help="同盘裸仓库路径（默认按系统取 Autarkia-hub.git）")
    parser.add_argument("--peer", help="对端工作副本路径；传空串表示禁用（Windows 侧天然禁用）")
    args = parser.parse_args(argv)

    repo = Path(args.repo).expanduser().resolve() if args.repo else project_root()
    if not repo.is_dir():
        print(f"[ERROR] 仓库目录不存在：{repo}")
        return RC_ERROR
    if run_git(repo, "rev-parse", "--git-dir").returncode != 0:
        print(f"[ERROR] 不是 git 仓库：{repo}")
        return RC_ERROR

    hub = Path(args.hub).expanduser() if args.hub else default_hub()
    if args.peer is None:
        peer = default_peer()
    else:
        text = args.peer.strip()
        peer = Path(text).expanduser() if text else None

    if args.action == "pull":
        return do_pull(repo, hub, peer)
    if args.action == "push":
        return do_push(repo, hub)
    return do_status(repo, hub, peer)


if __name__ == "__main__":
    sys.exit(main())
