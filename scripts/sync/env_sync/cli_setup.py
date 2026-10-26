#!/usr/bin/env python3
"""CodeRabbit CLI 就位检查与自动补装。

CLI 本体是平台相关二进制，无法跨系统搬运，只能各侧自装；本模块只保证
Linux 侧就位（``coderabbit`` / ``cr`` 在 PATH），缺装时用官方 install.sh
补装，直连失败自动改走本地代理。Windows 侧仍需手动装一次。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from scripts.sync.env_sync.env_merge import RC_ERROR, RC_OK

#: CodeRabbit CLI 官方安装脚本与本机代理兜底（直连该域名会被重置）
CLI_INSTALL_CMD = "curl -fsSL https://cli.coderabbit.ai/install.sh | sh"
DEFAULT_PROXY = "http://127.0.0.1:7897"

#: 单次安装尝试的限时（秒）：脚本挂在 start.sh 启停流程里，必须给启动一个上界
INSTALL_TIMEOUT_S = 90


def cli_installed() -> str | None:
    """返回本机 coderabbit CLI 的路径；未装返回 None。

    先查 PATH；查不到再兜底检查官方 install.sh 的固定安装位置 ``~/.local/bin``
    ——当前进程（如 start.sh 环境）的 PATH 未必包含它，否则会把刚装好的 CLI
    误报成未安装。
    """
    found = shutil.which("coderabbit") or shutil.which("cr")
    if found:
        return found
    local_bin = Path.home() / ".local" / "bin"
    for name in ("coderabbit", "cr"):
        cand = local_bin / name
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    return None


def install_cli(
    runner=subprocess.run, finder=cli_installed
) -> bool:
    """用官方 install.sh 补装 CLI；直连失败自动带一次本地代理重试。

    单次尝试限时 :data:`INSTALL_TIMEOUT_S`（脚本挂在启动流程里，不能无上限地
    阻塞启动；超时视为该次失败，转入下一档重试）。``runner`` / ``finder``
    供测试注入，运行期用默认实现。
    """
    for extra_env in ({}, {"https_proxy": DEFAULT_PROXY, "http_proxy": DEFAULT_PROXY}):
        env = {**os.environ, **extra_env}
        label = "直连" if not extra_env else f"代理 {DEFAULT_PROXY}"
        print(f"[INFO] 安装 CodeRabbit CLI（{label}，限时 {INSTALL_TIMEOUT_S}s）...")
        try:
            proc = runner(
                ["sh", "-c", CLI_INSTALL_CMD],
                env=env,
                capture_output=True,
                text=True,
                timeout=INSTALL_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            print(f"[WARN] {label}安装超时（{INSTALL_TIMEOUT_S}s），转入下一档")
            continue
        if proc.returncode == 0 and finder():
            return True
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        print(f"[WARN] {label}安装失败：{detail[-1] if detail else '未知原因'}")
    return False


def _probe_version(path: str) -> str | None:
    """跑 ``--version``：命令成功执行且退出码为 0 才返回版本行，否则 None。

    探测失败说明 CLI 在盘上但不可用（缺依赖、损坏等），不能当作就位。
    """
    try:
        proc = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    lines = (proc.stdout or proc.stderr or "").strip().splitlines()
    return lines[0] if lines else None


def ensure_cli() -> int:
    """保证本机有可用的 coderabbit CLI；已装且版本探测通过才算就位。"""
    found = cli_installed()
    if found:
        version = _probe_version(found)
        if version is not None:
            print(f"[PASS] CodeRabbit CLI 已就位：{found}（{version}）")
            return RC_OK
        print(f"[WARN] 检测到 {found} 但版本探测失败，尝试补装修复")
    else:
        print("[WARN] 本机未安装 CodeRabbit CLI（coderabbit / cr 不在 PATH）")
    if install_cli():
        found = cli_installed()
        if found and _probe_version(found) is not None:
            print("[PASS] CLI 补装完成")
            return RC_OK
        print("[WARN] CLI 已在盘上但版本探测仍失败；提交门禁遇缺只告警放行，"
              "可稍后手动检查：")
    else:
        print("[WARN] CLI 自动补装失败；提交门禁遇缺只告警放行，可稍后手动执行：")
    print(f"       {CLI_INSTALL_CMD}")
    return RC_ERROR
