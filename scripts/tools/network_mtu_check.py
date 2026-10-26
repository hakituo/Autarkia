"""网络 MTU 自检：判断「大包被丢导致下载极慢」并给出修复命令。

典型症状：ping 正常、网页能开，但 pip / 下载只有几十 KB/s —— 多为路径 MTU 不足：
标准 1500 的大包被路上某段（路由器 PPPoE / VPN / 光猫封装）静默丢弃，TCP 反复重传。

运行：.venv/bin/python scripts/tools/network_mtu_check.py
退出码：0 = 健康；2 = 需要降 MTU；1 = 无法判定（缺少工具/网络不通）

修复（Linux NetworkManager，持久化）：
    sudo nmcli connection modify "<连接名>" 802-11-wireless.mtu 1400
    sudo nmcli connection up "<连接名>"
临时：sudo ip link set dev <接口> mtu 1400
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return proc.returncode, (proc.stdout or proc.stderr).strip()
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def default_interface() -> str:
    """默认路由所在接口名（Linux: ip route；Windows 无此命令时返回空）。"""
    if os.name == "nt":
        return ""
    code, out = _run(["ip", "route", "show", "default"])
    match = re.search(r"\bdev\s+(\S+)", out)
    return match.group(1) if code == 0 and match else ""


def default_gateway() -> str:
    """默认路由网关。探测本地网关最能反映本机链路 MTU（公网目标常限制 ICMP 大包）。"""
    if os.name == "nt":
        return ""
    code, out = _run(["ip", "route", "show", "default"])
    match = re.search(r"\bvia\s+(\S+)", out)
    return match.group(1) if code == 0 and match else ""


def interface_mtu(name: str) -> int:
    code, out = _run(["ip", "link", "show", name])
    match = re.search(r"\bmtu\s+(\d+)", out)
    return int(match.group(1)) if code == 0 and match else 0


def pmtu_ok(payload: int, host: str, attempts: int = 3) -> bool:
    """探测指定 payload（不含 28 字节 IP/ICMP 头）能否直达。

    重试 attempts 次、任意一次成功即判通：偶发丢包/运营商对 ICMP 大包限速
    会让单次探测误报，而 MTU 不足是稳定复现的。
    """
    for _ in range(attempts):
        if os.name == "nt":
            cmd = ["ping", "-n", "1", "-f", "-l", str(payload), "-w", "2000", host]
        else:
            cmd = ["ping", "-M", "do", "-s", str(payload), "-c", "1", "-W", "2", host]
        code, _ = _run(cmd)
        if code == 0:
            return True
    return False


def main() -> int:
    if not shutil.which("ping"):
        print("[UNKNOWN] 缺少 ping 命令，无法探测")
        return 1

    iface = default_interface()
    mtu = interface_mtu(iface) if iface else 0
    gateway = default_gateway()
    print(f"默认接口: {iface or '(未知)'}  接口 MTU: {mtu or '(未知)'}  网关: {gateway or '(未知)'}")

    # 优先探测本地网关：公网 CDN 常对 ICMP 大包限速，会造成误报
    host = gateway or "223.5.5.5"
    ok_1500 = pmtu_ok(1472, host)   # 1472 + 28 = 1500
    ok_1400 = pmtu_ok(1372, host)   # 1372 + 28 = 1400
    print(f"PMTU 探测 {host}:  1500={'通' if ok_1500 else '丢'}  1400={'通' if ok_1400 else '丢'}")

    if ok_1500:
        print("[OK] 路径支持 1500，无需调整 MTU")
        return 0
    if ok_1400:
        if mtu and mtu <= 1400:
            print(f"[OK] 路径上限 1400，接口 MTU={mtu} 已适配，无需处理")
            return 0
        print("[WARN] 路径只通 1400 —— 大包被丢，下载会退化为几十 KB/s")
        if iface and mtu and mtu > 1400:
            print(f"[建议] 当前接口 MTU={mtu}，降到 1400 后重测下载速度：")
        print("  临时: sudo ip link set dev %s mtu 1400" % (iface or "<接口>"))
        print('  持久: sudo nmcli connection modify "<连接名>" 802-11-wireless.mtu 1400')
        print('        sudo nmcli connection up "<连接名>"')
        return 2
    if mtu and mtu <= 1400:
        print(f"[UNKNOWN] 接口 MTU 已是 {mtu}，探测仍失败：多为目标限制 ICMP 大包，不代表链路坏")
        print("          以实际下载速度为准；若下载正常则无需处理")
        return 1
    print("[FAIL] 连 1400 都不通，先排查网络本身（DNS / 代理 / 链路）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
