#!/usr/bin/env python3
"""本机配置跨系统同步：.env 键级并集合并 + CodeRabbit CLI 就位检查（门面）。

双系统的三条同步通道（代码走 git 提交、运行数据走 learning_data_sync 语义合并、
组件库走 libs_sync 镜像）都覆盖不到 gitignore 的 ``.env`` 与装在系统里的 CLI：
它们不在提交里、也不在任何数据根里。本脚本补第四条通道，随 start.sh 启停各跑一次：

- ``merge``：对两边 ``.env`` 做「键级并集、只补缺、不覆盖」。一侧新加的配置
  （连同注释块）补到缺的另一侧；两边都有的键即使值不同也保持本机现状、只报告
  差异——路径类配置本就该各写各的，整文件覆盖会互相破坏。合并幂等且与方向无关。
- ``ensure-cli``：本机缺 ``coderabbit`` / ``cr`` 命令时用官方 install.sh 自动
  补装（直连失败自动改走本地代理）。CLI 是平台相关二进制，只能各侧自装。

用法::

    python -m scripts.sync.env_sync merge --peer-root /mnt/win_p4/AI/Autarkia --auto --apply
    python -m scripts.sync.env_sync ensure-cli

环境变量：``AUTARKIA_SYNC_ENV``（旧名 ``XIAOYOU_SYNC_ENV``）置 0 时整个脚本直接跳过。
退出码：0 已同步或无需同步；1 真错误。

本文件是薄壳门面：实现在 ``env_merge``（.env 解析与合并）与 ``cli_setup``（CLI
就位与补装），这里只做编排与命令行解析。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.sync.code_sync import default_peer
from scripts.sync.env_sync import cli_setup
from scripts.sync.env_sync.cli_setup import (
    DEFAULT_PROXY,
    INSTALL_TIMEOUT_S,
    cli_installed,
    ensure_cli,
    install_cli,
)
from scripts.sync.env_sync.env_merge import (
    RC_ERROR,
    RC_OK,
    merge,
)

#: 环境变量开关（新名优先、旧名兼容），与 AUTARKIA_SYNC_CODE 同一套约定
ENV_TOGGLE, ENV_TOGGLE_LEGACY = "AUTARKIA_SYNC_ENV", "XIAOYOU_SYNC_ENV"

__all__ = [
    "DEFAULT_PROXY",
    "ENV_TOGGLE",
    "ENV_TOGGLE_LEGACY",
    "INSTALL_TIMEOUT_S",
    "RC_ERROR",
    "RC_OK",
    "cli_installed",
    "cli_setup",
    "ensure_cli",
    "install_cli",
    "main",
    "merge",
]


def main(argv: list[str] | None = None) -> int:
    if (os.environ.get(ENV_TOGGLE) or os.environ.get(ENV_TOGGLE_LEGACY) or "").strip() == "0":
        print(f"[INFO] {ENV_TOGGLE}=0，跳过本机配置同步")
        return RC_OK

    parser = argparse.ArgumentParser(
        prog="env_sync",
        description="双系统 .env 键级并集合并 + CodeRabbit CLI 就位检查",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_merge = sub.add_parser("merge", help="合并两边 .env（默认 dry-run，--apply 才写盘）")
    p_merge.add_argument("--local", help="本机 .env，默认项目根下 .env")
    p_merge.add_argument("--peer-root", help="对端仓库根目录（默认取 code_sync 的对端）")
    p_merge.add_argument("--auto", action="store_true", help="没有可用对端时静默跳过")
    p_merge.add_argument("--apply", action="store_true", help="真正写入（默认只出计划）")

    sub.add_parser("ensure-cli", help="检查并自动补装 CodeRabbit CLI")

    args = parser.parse_args(argv)

    if args.command == "ensure-cli":
        return ensure_cli()

    local_path = Path(args.local).expanduser() if args.local else _PROJECT_ROOT / ".env"
    if args.peer_root:
        peer_path = Path(args.peer_root).expanduser() / ".env"
    else:
        peer = default_peer()
        if peer is None:
            if args.auto:
                return RC_OK
            print("[ERROR] 没有可用对端（传 --peer-root 或设置 AUTARKIA_CODE_PEER）")
            return RC_ERROR
        peer_path = peer / ".env"

    if args.auto and not peer_path.is_file():
        print("[INFO] 对端仓库不可用，跳过 .env 合并")
        return RC_OK
    if not local_path.is_file():
        print(f"[ERROR] 本机 .env 不存在：{local_path}")
        return RC_ERROR
    return merge(local_path, peer_path, apply=args.apply)


if __name__ == "__main__":
    sys.exit(main())
