#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日常操作统一入口（薄壳转发）。

只做转发，不复制任何逻辑：每个子命令都调用仓库里已有的正式脚本，
实现只有一处，日常不用再记一堆长路径。

用法（Windows / Linux 通用，解释器自动探测）：

    python scripts/daily/daily.py status
    python scripts/daily/daily.py log .tmp/xxx_payload.json
    python scripts/daily/daily.py index
    python scripts/daily/daily.py check
    python scripts/daily/daily.py commit --dry-run --private-mode
    python scripts/daily/daily.py commit -m "一句话摘要"
    python scripts/daily/daily.py deploy          # 仅 Linux
    python scripts/daily/daily.py backup          # 运行时数据按月快照备份

子命令之后的未知参数原样透传给被调用的脚本。
解释器优先用本机虚拟环境（RULES.md §2），可用 XIAOYOU_PY 覆盖。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

RULE_CHECK = "tests/scripts/docs/check_rules_consistency.py"
SIZE_CHECK = "tests/scripts/docs/check_file_sizes.py"
TEST_AUDIT = "tests/scripts/audit_tests.py"
RECORDS = "scripts/doc_records/update_project_records.py"
UPDATES = "scripts/doc_records/split_updates_to_daily.py"
COMMIT = "scripts/git/auto_commit_push.py"
DEPLOY = "scripts/deploy/deploy_linux.sh"
BACKUP = "scripts/backup/auto_backup.py"


def interpreter() -> str:
    """按 RULES.md §2 优先用本机虚拟环境解释器，找不到才退回当前解释器。"""
    override = os.environ.get("XIAOYOU_PY", "").strip()
    if override:
        return override

    if os.name == "nt":
        candidates = [ROOT / "venv_cpu" / "Scripts" / "python.exe"]
    else:
        candidates = [
            ROOT / "venv_linux" / "bin" / "python",
            ROOT / "venv_cpu" / "bin" / "python",
        ]

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    print(f"[daily] 警告：未找到虚拟环境解释器，退回 {sys.executable}")
    return sys.executable


def run(cmd: list[str]) -> int:
    print(f"[daily] {' '.join(cmd)}")
    try:
        return subprocess.call(cmd, cwd=str(ROOT))
    except FileNotFoundError as exc:
        print(f"[daily] 执行失败：{exc}")
        return 127


def run_py(script: str, extra: list[str]) -> int:
    return run([interpreter(), script, *extra])


def cmd_status(_args, _extra) -> int:
    return run(["git", "status", "--porcelain"])


def cmd_log(args, _extra) -> int:
    if not args.payload:
        print("[daily] 用法：daily.py log <payload.json>")
        return 2
    return run_py(RECORDS, ["--payload-file", args.payload])


def cmd_index(_args, _extra) -> int:
    """先重建索引与根入口，再跑一次结构校验。"""
    code = run_py(UPDATES, ["--index"])
    if code != 0:
        return code
    return run_py(UPDATES, ["--check"])


def cmd_check(_args, _extra) -> int:
    """按 RULES.md 口径跑三项：规则一致性、行数分档、测试审计。"""
    results = [
        ("规则一致性", run_py(RULE_CHECK, [])),
        ("行数分档", run_py(SIZE_CHECK, [])),
        ("测试审计", run_py(TEST_AUDIT, [])),
    ]
    failed = [name for name, code in results if code != 0]
    if failed:
        print(f"[daily] 未通过：{'、'.join(failed)}")
        return 1
    print("[daily] 三项检查全部通过")
    return 0


def cmd_commit(_args, extra) -> int:
    return run_py(COMMIT, extra)


def cmd_deploy(_args, extra) -> int:
    if os.name == "nt":
        print("[daily] deploy 只能在 Linux 服务器上执行（依赖 bash 与 systemd）")
        return 2
    return run(["bash", DEPLOY, *extra])


def cmd_backup(_args, extra) -> int:
    return run_py(BACKUP, extra)


HANDLERS = {
    "status": cmd_status,
    "log": cmd_log,
    "index": cmd_index,
    "check": cmd_check,
    "commit": cmd_commit,
    "deploy": cmd_deploy,
    "backup": cmd_backup,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="daily.py",
        description="日常操作统一入口（薄壳转发到既有正式脚本）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="查看工作区改动（git status --porcelain）")

    log_parser = sub.add_parser("log", help="按 JSON 载荷写入更新日志")
    log_parser.add_argument("payload", nargs="?", help="JSON 载荷文件路径")

    sub.add_parser("index", help="刷新更新日志索引与根入口，并校验")

    sub.add_parser("check", help="规则一致性 + 行数分档 + 测试审计")

    # 透传型子命令关掉自带 help：否则 -h/--help 会被 argparse 吃掉，
    # 关掉后 `daily.py commit -h` 会把 -h 交给底层脚本，显示它自己的帮助。
    sub.add_parser(
        "commit", help="提交推送，参数透传给 auto_commit_push.py", add_help=False
    )

    sub.add_parser(
        "deploy", help="Linux 服务器部署，参数透传给 deploy_linux.sh", add_help=False
    )

    sub.add_parser(
        "backup", help="运行时数据按月快照备份，参数透传给 auto_backup.py", add_help=False
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args, extra = parser.parse_known_args(argv)
    return HANDLERS[args.command](args, extra)


if __name__ == "__main__":
    raise SystemExit(main())
