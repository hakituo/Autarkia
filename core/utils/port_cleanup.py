"""端口占用清理工具。

场景：服务异常退出后残留僵尸进程占着首选端口（如 8000），重启时被迫漂移到
8001/8002。本模块在启动阶段把端口"抢"回来：

1. 找出监听指定 TCP 端口的进程 PID（跨平台：lsof / fuser / netstat -ano）；
2. 强制终止占用者（排除自身避免自杀；Windows 用 taskkill /F /T 连进程树一起清）；
3. 提供 SO_REUSEADDR 绑定探测，区分「活进程占用」与「TIME_WAIT 残留」。

设计约束：
- 只针对监听（LISTEN）该端口的进程，不碰仅发起连接的进程；
- 拿不到 PID 或无权限终止时返回空列表，由调用方降级处理（切换端口兜底）；
- 全程不抛异常，启动路径不允许被清理逻辑本身拖垮。
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import time

from core.utils.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "can_bind_with_reuse",
    "find_port_listeners",
    "free_port",
    "kill_port_occupants",
]


def _run_cmd(
    cmd: list[str], timeout: float = 15.0
) -> subprocess.CompletedProcess[str] | None:
    """运行外部命令；命令不存在 / 超时 / 其他异常一律返回 None，不抛出。"""
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _parse_pid_list(text: str | None) -> list[int]:
    """从命令 stdout 解析 PID 列表（按空白切分，仅保留正整数）。"""
    if not text:
        return []
    pids: list[int] = []
    for token in text.split():
        if token.isdigit():
            pid = int(token)
            if pid > 0:
                pids.append(pid)
    return pids


def _pids_via_lsof(port: int) -> list[int] | None:
    """用 lsof 列出监听端口的 PID；lsof 不存在返回 None（交由 fuser 兜底）。"""
    result = _run_cmd(["lsof", "-t", "-i", f"TCP:{port}", "-s", "TCP:LISTEN"])
    if result is None:
        return None
    return _parse_pid_list(result.stdout)


def _pids_via_fuser(port: int) -> list[int] | None:
    """用 fuser 列出占用 port/tcp 的 PID（PID 打在 stdout，说明文字在 stderr）。"""
    result = _run_cmd(["fuser", f"{port}/tcp"])
    if result is None:
        return None
    return _parse_pid_list(result.stdout)


def _pids_via_netstat(port: int) -> list[int]:
    """Windows: 解析 netstat -ano 的 LISTENING 行，取本地端口匹配的 PID。"""
    result = _run_cmd(["netstat", "-ano", "-p", "TCP"])
    if result is None or not result.stdout:
        return []
    pids: list[int] = []
    port_suffix = f":{port}"
    for line in result.stdout.splitlines():
        parts = line.split()
        # 典型行: TCP  0.0.0.0:8000  0.0.0.0:0  LISTENING  12345
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        if "LISTENING" not in parts[3].upper():
            continue
        if not parts[1].lower().endswith(port_suffix):
            continue
        pid_token = parts[-1]
        if pid_token.isdigit() and int(pid_token) > 0:
            pids.append(int(pid_token))
    return pids


def find_port_listeners(port: int) -> list[int]:
    """返回当前监听指定 TCP 端口的进程 PID 列表（可能为空）。"""
    port = int(port)
    if os.name == "nt":
        return _pids_via_netstat(port)
    pids = _pids_via_lsof(port)
    if pids is None:
        pids = _pids_via_fuser(port)
    return pids or []


def _kill_pid(pid: int) -> bool:
    """POSIX: SIGKILL 终止单个进程；已不存在视为成功，无权限等返回 False。"""
    try:
        os.kill(pid, signal.SIGKILL)
        return True
    except ProcessLookupError:
        return True
    except PermissionError:
        logger.warning("无权限终止进程 PID %s（可能由更高权限服务拉起）", pid)
        return False
    except OSError as exc:
        logger.warning("终止进程 PID %s 失败: %s", pid, exc)
        return False


def _kill_pid_windows(pid: int) -> bool:
    """Windows: taskkill /F /T 强制终止进程树。"""
    result = _run_cmd(["taskkill", "/F", "/T", "/PID", str(pid)], timeout=10.0)
    return result is not None and result.returncode == 0


def kill_port_occupants(
    port: int, exclude_pids: set[int] | None = None
) -> list[int]:
    """强制终止监听指定端口的进程，返回成功终止的 PID 列表。

    恒排除当前进程自身（exclude_pids 可追加其他需保护的 PID）；
    任何失败都不抛异常，返回已成功的部分，调用方按空列表降级。
    """
    port = int(port)
    excluded = {os.getpid()} | (exclude_pids or set())
    killed: list[int] = []
    seen: set[int] = set()
    for pid in find_port_listeners(port):
        if pid in excluded or pid in seen:
            continue
        seen.add(pid)
        ok = _kill_pid_windows(pid) if os.name == "nt" else _kill_pid(pid)
        if ok:
            killed.append(pid)
    return killed


def can_bind_with_reuse(host: str, port: int) -> bool:
    """带 SO_REUSEADDR 的绑定探测。

    能绑上说明没有「活进程」占用（TIME_WAIT 残留不影响正式监听，本项目
    正式监听 socket 本就带 SO_REUSEADDR，见 main._make_reuse_socket）；
    绑不上说明仍有活进程在监听，需要降级换端口。
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, int(port)))
        return True
    except OSError:
        return False
    finally:
        try:
            sock.close()
        except OSError:
            pass


def free_port(
    host: str,
    port: int,
    wait_seconds: float = 1.0,
    exclude_pids: set[int] | None = None,
) -> list[int]:
    """一体化入口：清理占用端口的进程，返回被终止的 PID 列表。

    返回非空时已额外等待 wait_seconds 供内核回收 socket；随后调用方可用
    can_bind_with_reuse 复核端口是否真的可用。
    """
    killed = kill_port_occupants(port, exclude_pids=exclude_pids)
    if killed:
        logger.warning(
            "已强制结束占用端口 %s 的进程 (PID: %s)，等待 %.1fs 释放...",
            port,
            ", ".join(map(str, killed)),
            wait_seconds,
        )
        time.sleep(wait_seconds)
    return killed
