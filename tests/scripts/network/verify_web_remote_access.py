#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 Web 端经局域网 / Tailscale 访问时的来源放行与前端同源代理。

覆盖三件事：
1. 可信网络判据：本机回环、私网、Tailscale（100.64.0.0/10、*.ts.net）放行，公网来源拒绝；
2. CORS 正则与上述判据覆盖同一批主机（两处一改一漏会让预检被浏览器拦下）；
3. 已停用的 tunnel 域名不再出现在配置、前端与文档里。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.middleware.trusted_origin import (  # noqa: E402
    TRUSTED_ORIGIN_REGEX,
    is_trusted_network_host,
    is_trusted_origin,
    origin_host,
)

ALLOW_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:8000",
]

TRUSTED_NETWORK_HOSTS = [
    "localhost",
    "127.0.0.1",
    "100.64.0.1",
    "100.101.102.103",
    "100.127.255.254",
    "192.0.2.25",
    "10.0.0.5",
    "172.16.4.9",
    "my-pc.tailnet-abc.ts.net",
]

UNTRUSTED_HOSTS = [
    "",
    "8.8.8.8",
    "100.63.255.255",
    "100.128.0.1",
    "203.0.113.10",
    "evil.example.com",
    "ai.example.icu",
]

TRUSTED_ORIGINS = [f"http://{host}:3000" for host in TRUSTED_NETWORK_HOSTS]
UNTRUSTED_ORIGINS = [
    "https://evil.example.com",
    "http://8.8.8.8:3000",
    "http://100.128.0.1:3000",
    "https://ai.example.icu",
    "null",
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def check_trusted_network() -> None:
    for host in TRUSTED_NETWORK_HOSTS:
        require(is_trusted_network_host(host), f"可信网络主机被误拒: {host}")
    for host in UNTRUSTED_HOSTS:
        require(not is_trusted_network_host(host), f"公网主机被误放行: {host!r}")

    require(origin_host("http://100.1.2.3:3000") == "100.1.2.3", "Origin 主机名解析异常")
    require(origin_host("http://[::1]:3000") == "::1", "IPv6 Origin 主机名解析异常")
    require(origin_host("") == "", "空 Origin 应解析为空主机")


def check_origin_decision() -> None:
    for origin in ALLOW_ORIGINS + TRUSTED_ORIGINS:
        require(is_trusted_origin(origin, ALLOW_ORIGINS), f"可信 Origin 被误拒: {origin}")
    for origin in UNTRUSTED_ORIGINS:
        require(not is_trusted_origin(origin, ALLOW_ORIGINS), f"公网 Origin 被误放行: {origin}")
    # 通配符配置下全部放行，与原行为一致
    require(is_trusted_origin("https://evil.example.com", ["*"]), "通配符配置应放行全部 Origin")


def check_cors_regex() -> None:
    """CORS 正则必须与 is_trusted_origin 覆盖同一批网络来源，否则预检会被浏览器拦。"""
    for origin in TRUSTED_ORIGINS:
        require(is_trusted_origin(origin, ALLOW_ORIGINS), f"判据漏放: {origin}")
        require(bool(re.match(TRUSTED_ORIGIN_REGEX, origin)), f"CORS 正则漏放: {origin}")
    for origin in UNTRUSTED_ORIGINS:
        require(not is_trusted_origin(origin, ALLOW_ORIGINS), f"判据误放: {origin}")
        require(not re.match(TRUSTED_ORIGIN_REGEX, origin), f"CORS 正则误放: {origin}")


def check_wiring() -> None:
    """中间件与配置必须真的接上判据，避免只留一个没人调用的模块。"""
    main_py = read("main.py")
    require(
        "allow_origin_regex=TRUSTED_ORIGIN_REGEX" in main_py,
        "CORSMiddleware 未接入可信来源正则",
    )
    require(
        '"core.middleware.trusted_origin"' in main_py,
        "main.py 未导入可信来源模块",
    )
    security_py = read("core/middleware/security.py")
    require(
        "is_trusted_origin(origin, allow_origins)" in security_py,
        "strict_origin 中间件未使用可信来源判据",
    )


def check_dead_domains_removed() -> None:
    """tunnel 已停用：配置、前端与文档不得再硬编码那两个子域。"""
    for path in (
        "config/yaml/app.yaml",
        "clients/frontend/aveline-web/vite.config.ts",
        "clients/frontend/aveline-web/src/api/config.ts",
        "clients/frontend/aveline-web/src/components/SettingsView.tsx",
        "docs/important/PORTS.md",
        "PROJECT_TECHNICAL_REFERENCE.md",
    ):
        require("example.icu" not in read(path), f"{path} 仍残留 tunnel 域名")

    vite_config = read("clients/frontend/aveline-web/vite.config.ts")
    require("allowedHosts: ['.ts.net']" in vite_config, "Vite 未放行 Tailscale MagicDNS 主机名")

    api_config = read("clients/frontend/aveline-web/src/api/config.ts")
    require("isLoopbackHost" in api_config, "前端未区分本机与远端访问")
    require(
        "apiBase = origin" in api_config,
        "远端 dev 访问未切到同源 Vite 代理",
    )


def main() -> None:
    check_trusted_network()
    check_origin_decision()
    check_cors_regex()
    check_wiring()
    check_dead_domains_removed()
    print("[OK] Web 局域网/Tailscale 访问放行与 tunnel 域名清理验证通过")


if __name__ == "__main__":
    main()
