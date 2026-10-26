"""组件库同步用到的 git 操作。

所有函数都显式接收仓库路径，不依赖当前工作目录；同时通过
``-c safe.directory=<repo>`` 放行 NTFS 上属主为 root 的对端仓库，
不改用户全局 git 配置。
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

TIMEOUT = 180


def run(
    repo: Path,
    *args: str,
    env: dict[str, str] | None = None,
    timeout: int = TIMEOUT,
    safe: tuple[Path, ...] = (),
):
    """在 ``repo`` 里执行 git，返回 CompletedProcess。

    ``safe`` 用于 ``git fetch <对端路径>``：NTFS 上的对端属主是 root，
    不把对端也放行会触发 dubious ownership。
    """
    cmd = ["git", "-c", "core.quotepath=false"]
    for path in {repo, *safe}:
        cmd += ["-c", f"safe.directory={path}"]
    cmd += list(args)
    merged = {**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env or {})}
    try:
        return subprocess.run(
            cmd,
            check=False,
            cwd=str(repo),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=merged,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(cmd, 1, "", str(exc))


def out(repo: Path, *args: str) -> str:
    proc = run(repo, *args)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def is_repo(repo: Path) -> bool:
    return repo.is_dir() and (repo / ".git").exists()


def head(repo: Path) -> str:
    return out(repo, "rev-parse", "HEAD")


def branch(repo: Path) -> str:
    return out(repo, "rev-parse", "--abbrev-ref", "HEAD")


def porcelain(repo: Path) -> list[str]:
    proc = run(repo, "status", "--porcelain", "--untracked-files=normal")
    return (
        [line for line in proc.stdout.splitlines() if line.strip()] if proc.returncode == 0 else []
    )


def changed_files(repo: Path) -> list[str]:
    """解析 ``git status --porcelain`` 的文件名（重命名取新名）。"""
    files: list[str] = []
    for line in porcelain(repo):
        rest = line[3:]
        if " -> " in rest:
            rest = rest.split(" -> ", 1)[1]
        files.append(rest.strip().strip('"'))
    return files


def is_clean(repo: Path) -> bool:
    return not porcelain(repo)


def is_ancestor(repo: Path, older: str, newer: str) -> bool:
    if not older or not newer:
        return False
    return run(repo, "merge-base", "--is-ancestor", older, newer).returncode == 0


def ahead_of_origin(repo: Path) -> int:
    """当前分支领先 origin 的提交数；没有 origin/main 时返回 0。"""
    if not out(repo, "rev-parse", "--verify", "--quiet", "origin/main"):
        return 0
    raw = out(repo, "rev-list", "--count", "origin/main..HEAD")
    return int(raw) if raw.isdigit() else 0


def has_origin(repo: Path) -> bool:
    return bool(out(repo, "remote", "get-url", "origin"))


def commit_all(repo: Path, message: str) -> tuple[bool, str]:
    """提交工作区全部改动；无改动视为成功。"""
    add = run(repo, "add", "-A")
    if add.returncode != 0:
        return False, add.stderr.strip()
    proc = run(repo, "commit", "-m", message)
    if proc.returncode == 0:
        return True, "committed"
    combined = (proc.stdout + proc.stderr).lower()
    if "nothing to commit" in combined or "无文件要提交" in combined:
        return True, "nothing"
    return False, (proc.stdout + proc.stderr).strip()


def ensure_pushurl(repo: Path) -> str:
    """HTTPS 远端无凭据时，为 origin 补一个 SSH pushurl。"""
    existing = out(repo, "config", "--get", "remote.origin.pushurl")
    if existing:
        return existing
    url = out(repo, "remote", "get-url", "origin")
    if not url or not url.startswith("https://github.com/"):
        return url
    # Windows 侧通常由 Git Credential Manager 管 HTTPS 凭据，不强行改成 SSH。
    if os.name == "nt":
        return url
    match = re.match(r"https://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", url)
    if not match:
        return url
    ssh = f"git@github.com:{match.group(1)}/{match.group(2)}.git"
    run(repo, "config", "remote.origin.pushurl", ssh)
    return ssh


def push_origin(repo: Path, branch_name: str = "main") -> tuple[bool, str]:
    if not has_origin(repo):
        return True, "无 origin（未发布库，跳过 GitHub）"
    ensure_pushurl(repo)
    # 走远端名而不是裸 URL：push 后 origin/main 跟踪引用会一起更新，
    # 下次检测「未推送提交数」才不会被上一轮的提交一直算进去。
    proc = run(
        repo,
        "push",
        "origin",
        f"HEAD:{branch_name}",
        env={"GCM_INTERACTIVE": "never"},
        timeout=120,
    )
    if proc.returncode != 0:
        return False, proc.stderr.strip() or proc.stdout.strip()
    return True, "pushed"


@dataclass
class MirrorResult:
    status: str
    detail: str = ""


def mirror(local: Path, peer: Path, branch_name: str = "main") -> MirrorResult:
    """把领先的一侧快进到另一侧；只做 ff-only，不合并、不覆盖脏工作树。"""
    if peer is None or not is_repo(peer):
        return MirrorResult("skip", "对端仓库不存在")
    if not is_repo(local):
        return MirrorResult("skip", "本地仓库不存在")
    local_head, peer_head = head(local), head(peer)
    if not local_head or not peer_head:
        return MirrorResult("skip", "仓库还没有提交")
    if local_head == peer_head:
        return MirrorResult("same", "提交一致")

    # 先把对象互相同步，否则「谁是谁的祖先」在缺对象的一侧根本算不出来。
    fetch = run(
        local,
        "fetch",
        "--no-tags",
        str(peer),
        f"+refs/heads/{branch_name}:refs/remotes/peer/{branch_name}",
        safe=(peer,),
    )
    if fetch.returncode != 0:
        return MirrorResult("error", fetch.stderr.strip())
    fetch = run(
        peer,
        "fetch",
        "--no-tags",
        str(local),
        f"+refs/heads/{branch_name}:refs/remotes/peer/{branch_name}",
        safe=(local,),
    )
    if fetch.returncode != 0:
        return MirrorResult("error", fetch.stderr.strip())

    local_dirty = not is_clean(local)
    peer_dirty = not is_clean(peer)
    if is_ancestor(local, peer_head, local_head):
        if peer_dirty:
            # 常见情形：Windows 侧手工把文件改成了和 Linux 新提交一样的内容，
            # 此时 checkout 掉脏文件是安全的，否则会永远卡在「工作树有改动」。
            if not _overwrite_safe(peer, local_head):
                return MirrorResult("blocked", "Windows 工作树有未提交改动")
            _restore_dirty(peer)
        merge = run(peer, "merge", "--ff-only", f"refs/remotes/peer/{branch_name}")
        if merge.returncode != 0:
            return MirrorResult("blocked", merge.stderr.strip() or merge.stdout.strip())
        return MirrorResult("pushed", f"{peer_head[:8]}→{local_head[:8]}")

    if is_ancestor(local, local_head, peer_head):
        if local_dirty:
            return MirrorResult("blocked", "Linux 工作树有未提交改动")
        merge = run(local, "merge", "--ff-only", f"refs/remotes/peer/{branch_name}")
        if merge.returncode != 0:
            return MirrorResult("blocked", merge.stderr.strip() or merge.stdout.strip())
        return MirrorResult("pulled", f"{local_head[:8]}→{peer_head[:8]}")

    return MirrorResult("diverged", "两侧提交已分叉")


def _overwrite_safe(repo: Path, target: str) -> bool:
    """脏文件是否已经等于目标提交里的内容（允许被 checkout 覆盖）。"""
    entries = porcelain(repo)
    if not entries:
        return True
    for entry in entries:
        code, name = entry[:2], entry[3:]
        # 只处理「仅工作树修改」，重命名/删除/未跟踪一律不动。
        if code != " M" or " -> " in name:
            return False
        try:
            current = (repo / name).read_bytes().decode("utf-8", errors="replace")
        except OSError:
            return False
        shown = run(repo, "show", f"{target}:{name}")
        if shown.returncode != 0:
            return False
        if _normalize(current) != _normalize(shown.stdout):
            return False
    return True


def _restore_dirty(repo: Path) -> None:
    """把已确认安全的脏文件恢复到 HEAD 内容。"""
    names = [entry[3:] for entry in porcelain(repo) if entry[:2] == " M"]
    if names:
        run(repo, "checkout", "--", *names)


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")
