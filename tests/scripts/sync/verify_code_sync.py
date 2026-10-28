#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 scripts/sync/code_sync.py 的双系统代码同步逻辑。

用临时目录搭出真实 git 仓库（对端工作副本 / 本机副本 / 同盘裸仓库 hub），
让脚本在临时仓库上真实执行 fetch / merge / push，校验：

1. pull 能从对端工作副本拿到提交（含对端还没推到 GitHub 的提交），且幂等；
2. push 把本机提交写进 hub，对端随后能从 hub 拉到；
3. **无关的未跟踪文件不再卡死同步**（旧 workflow 正是被这条拖死的）；
4. 本地改动与新提交冲突时返回 2，本地内容原样保留，且只点名真正挡路的文件；
5. 两端各有独有提交（分叉）时返回 2，不做自动合并；
6. 非 main 分支直接跳过，不动工作区；
7. hub 不存在时 push 自动建裸仓库；
8. 对端领先、hub 落后时仍追平对端（两个来源各用独立 ref，互不覆盖）。

运行：python tests/scripts/sync/verify_code_sync.py
退出码：0=全部通过；1=存在失败项。
"""

from __future__ import annotations

import contextlib
import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "sync"))

import code_sync  # noqa: E402

GIT_ARGS = [
    "-c",
    "user.name=verify",
    "-c",
    "user.email=verify@example.com",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "init.defaultBranch=main",
]

_failures: list[str] = []
_last_output = ""


def _check(condition: bool, message: str) -> None:
    if condition:
        print(f"  [OK] {message}")
        return
    print(f"  [FAIL] {message}")
    if _last_output:
        print("        —— 脚本输出 ——")
        for line in _last_output.strip().splitlines()[-12:]:
            print(f"        {line}")
    _failures.append(message)


def git(cwd: Path, *args: str) -> str:
    """在 cwd 里执行 git，返回 stdout；失败抛异常（验证脚本要立刻暴露环境问题）。"""
    proc = subprocess.run(
        ["git", *GIT_ARGS, *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败：{proc.stderr.strip()}")
    return proc.stdout.strip()


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD")


def init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    git(path, "symbolic-ref", "HEAD", "refs/heads/main")


def commit_file(repo: Path, name: str, content: str, message: str) -> str:
    (repo / name).write_text(content, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", message)
    return head(repo)


class Fixture:
    """一套最小双系统场景：Windows 工作副本 / Linux 工作副本 / 同盘 hub。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.win = root / "win"
        self.lin = root / "linux"
        self.hub = root / "hub.git"

    def build(self) -> None:
        init_repo(self.win)
        commit_file(self.win, "a.txt", "base\n", "base")
        subprocess.run(
            ["git", *GIT_ARGS, "clone", "-q", str(self.win), str(self.lin)],
            check=True,
            capture_output=True,
            text=True,
        )
        git(self.root, "init", "--bare", "-q", str(self.hub))


def call(action: str, repo: Path, hub: Path, peer: Path | None) -> int:
    """调用被测脚本，吞掉它自己的打印（只在失败时展示）。"""
    global _last_output
    argv = [
        action,
        "--repo",
        str(repo),
        "--hub",
        str(hub),
        "--peer",
        "" if peer is None else str(peer),
    ]
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = code_sync.main(argv)
    _last_output = buffer.getvalue()
    return code


def case_pull_from_peer(tmp: Path) -> None:
    print("[1] pull：从对端工作副本拿到提交，且幂等")
    fx = Fixture(tmp / "c1")
    fx.build()
    win_head = commit_file(fx.win, "b.txt", "from-win\n", "win: add b")

    code = call("pull", fx.lin, fx.hub, fx.win)
    _check(code == 0, "pull 返回 0")
    _check(head(fx.lin) == win_head, "Linux 副本追平到 Windows 提交")
    _check((fx.lin / "b.txt").exists(), "对端新文件已落到本地")

    code = call("pull", fx.lin, fx.hub, fx.win)
    _check(code == 0, "重复 pull 仍返回 0")
    _check(head(fx.lin) == win_head, "重复 pull 不改变 HEAD")


def case_push_then_windows_pull(tmp: Path) -> None:
    print("[2] push：写进 hub，对端从 hub 拉到")
    fx = Fixture(tmp / "c2")
    fx.build()
    lin_head = commit_file(fx.lin, "c.txt", "from-linux\n", "linux: add c")

    code = call("push", fx.lin, fx.hub, None)
    _check(code == 0, "push 返回 0")
    _check(git(fx.hub, "rev-parse", "refs/heads/main") == lin_head, "hub 的 main 指向 Linux 提交")

    code = call("pull", fx.win, fx.hub, None)
    _check(code == 0, "Windows 侧 pull 返回 0")
    _check(head(fx.win) == lin_head, "Windows 副本追平到 hub")
    _check((fx.win / "c.txt").exists(), "Linux 新文件已落到 Windows 副本")


def case_untracked_does_not_block(tmp: Path) -> None:
    print("[3] 无关的未跟踪文件不再卡死同步（旧 workflow 的死因）")
    fx = Fixture(tmp / "c3")
    fx.build()
    (fx.lin / "scratch.tmp").write_text("wip\n", encoding="utf-8")
    win_head = commit_file(fx.win, "d.txt", "from-win\n", "win: add d")

    code = call("pull", fx.lin, fx.hub, fx.win)
    _check(code == 0, "存在未跟踪文件时 pull 仍返回 0")
    _check(head(fx.lin) == win_head, "未跟踪文件不阻断快进")
    _check((fx.lin / "scratch.tmp").exists(), "未跟踪文件未被删除")


def case_local_change_blocks(tmp: Path) -> None:
    print("[4] 本地改动与新提交冲突：返回 2、不覆盖本地内容、只点名挡路文件")
    fx = Fixture(tmp / "c4")
    fx.build()
    # 先让两侧共享 extra.txt 的历史，本机随后改它时才算「无关的本地改动」
    commit_file(fx.win, "extra.txt", "base\n", "win: add extra")
    git(fx.lin, "pull", "-q", str(fx.win), "main")
    commit_file(fx.win, "a.txt", "from-win\n", "win: change a")
    (fx.lin / "a.txt").write_text("local-wip\n", encoding="utf-8")
    (fx.lin / "extra.txt").write_text("local-extra\n", encoding="utf-8")
    lin_head = head(fx.lin)

    code = call("pull", fx.lin, fx.hub, fx.win)
    _check(code == 2, "被本地改动挡住时返回 2（可重试，不是成功）")
    _check((fx.lin / "a.txt").read_text(encoding="utf-8") == "local-wip\n", "本地改动原样保留")
    _check(head(fx.lin) == lin_head, "HEAD 未被移动")
    _check("挡住：a.txt" in _last_output, "输出点名真正挡路的 a.txt")
    _check("extra.txt" not in _last_output, "对端没改的本机改动不被当成挡路者")


def case_diverged(tmp: Path) -> None:
    print("[5] 两端各有独有提交：返回 2，不自动合并")
    fx = Fixture(tmp / "c5")
    fx.build()
    commit_file(fx.win, "x.txt", "win\n", "win: add x")
    commit_file(fx.lin, "y.txt", "linux\n", "linux: add y")
    lin_head = head(fx.lin)

    code = call("pull", fx.lin, fx.hub, fx.win)
    _check(code == 2, "分叉时返回 2")
    _check(head(fx.lin) == lin_head, "分叉时 HEAD 未被移动")
    _check((fx.lin / "y.txt").exists(), "本机独有提交未被丢弃")


def case_non_main_branch(tmp: Path) -> None:
    print("[6] 非 main 分支：静默跳过")
    fx = Fixture(tmp / "c6")
    fx.build()
    git(fx.lin, "checkout", "-q", "-b", "feature")
    before = head(fx.lin)
    commit_file(fx.win, "e.txt", "from-win\n", "win: add e")

    code = call("pull", fx.lin, fx.hub, fx.win)
    _check(code == 0, "非 main 分支返回 0")
    _check(head(fx.lin) == before, "非 main 分支不被移动")
    _check(not (fx.lin / "e.txt").exists(), "非 main 分支不落盘对端提交")


def case_push_creates_hub(tmp: Path) -> None:
    print("[7] hub 不存在时 push 自动建裸仓库")
    fx = Fixture(tmp / "c7")
    fx.build()
    shutil.rmtree(fx.hub)
    commit_file(fx.lin, "f.txt", "from-linux\n", "linux: add f")

    code = call("push", fx.lin, fx.hub, None)
    _check(code == 0, "push 返回 0")
    _check(fx.hub.is_dir(), "hub 被自动创建")


def case_peer_ahead_of_hub(tmp: Path) -> None:
    print("[9] 对端领先、hub 落后：追平对端，不被 hub 的旧位置覆盖")
    fx = Fixture(tmp / "c9")
    fx.build()
    _check(call("push", fx.lin, fx.hub, None) == 0, "先把 base 写进 hub（hub 从此落后）")
    win_head = commit_file(fx.win, "g.txt", "from-win\n", "win: add g")

    code = call("pull", fx.lin, fx.hub, fx.win)
    _check(code == 0, "pull 返回 0")
    _check(head(fx.lin) == win_head, "HEAD 追平对端，未被 hub 的旧提交盖回去")
    _check("无法快进" not in _last_output, "两个来源各用独立 ref，日志不再自相矛盾")


def case_status(tmp: Path) -> None:
    print("[8] status：只报告，不动工作区")
    fx = Fixture(tmp / "c8")
    fx.build()
    before = head(fx.lin)

    code = call("status", fx.lin, fx.hub, fx.win)
    _check(code == 0, "status 返回 0")
    _check(head(fx.lin) == before, "status 不移动 HEAD")


def main() -> int:
    if shutil.which("git") is None:
        print("[FAIL] 未找到 git，无法验证")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="verify_code_sync_"))
    try:
        for case in (
            case_pull_from_peer,
            case_push_then_windows_pull,
            case_untracked_does_not_block,
            case_local_change_blocks,
            case_diverged,
            case_non_main_branch,
            case_push_creates_hub,
            case_peer_ahead_of_hub,
            case_status,
        ):
            case(tmp)
            print()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if _failures:
        print(f"未通过 {len(_failures)} 项：")
        for item in _failures:
            print(f"  - {item}")
        return 1
    print("全部通过：双系统代码同步行为符合预期")
    return 0


if __name__ == "__main__":
    sys.exit(main())
