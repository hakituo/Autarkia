#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可信网络来源判据（Origin / CORS 共用）。

通过局域网或 Tailscale 组网访问 Web 前端时，浏览器给出的 Origin 是运行期才知道的
动态地址（`192.168.x.x:3000`、`100.x.x.x:3000`、MagicDNS 主机名），无法预先写进
`server.allowed_origins`。这类来源只在受信任网络内可达；而 Origin 校验防的是
「恶意站点借用户浏览器跨站打本地后端」，攻击者站点不会落在这些网段里，
因此按网段放行不降低防护强度。

显式白名单（`config/yaml/app.yaml` 的 `server.allowed_origins`）仍是跨公网访问的唯一依据，
本模块只补充「网络位置可信」这一类判据，不替代白名单。
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

# Tailscale / WireGuard 默认使用 CGNAT 段分配地址（与 vpn_address.py 同一口径）
GROUP_NETWORK = ipaddress.ip_network("100.64.0.0/10")

# 显式登记私网段：不用 ipaddress.is_private，它把文档保留段（203.0.113.0/24 等）
# 也算私有，会把不可路由的示例网段当成可信来源
PRIVATE_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)

# Tailscale MagicDNS 默认后缀；自定义 tailnet 域名仍走显式白名单
MAGICDNS_SUFFIXES = (".ts.net",)

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0:0:0:0:0:0:0:1"})

# Starlette CORSMiddleware 用正则匹配，必须与 is_trusted_network_host 覆盖同一批主机
TRUSTED_ORIGIN_REGEX = (
    r"^https?://("
    r"localhost|127\.0\.0\.1|\[::1\]"
    r"|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}"
    r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.ts\.net"
    r")(?::\d{1,5})?$"
)


def origin_host(origin: str) -> str:
    """从 Origin 头取出小写主机名（去端口、去 IPv6 方括号）。"""
    try:
        hostname = urlsplit(str(origin or "")).hostname
    except ValueError:
        return ""
    return (hostname or "").lower()


def is_trusted_network_host(host: str) -> bool:
    """判断主机是否属于本机回环、私网或 Tailscale 组网。"""
    if not host:
        return False
    if host in LOOPBACK_HOSTS:
        return True
    if host.endswith(MAGICDNS_SUFFIXES):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if address in GROUP_NETWORK:
        return True
    return any(address in network for network in PRIVATE_NETWORKS)


def is_trusted_origin(origin: str, allow_origins: list[str]) -> bool:
    """Origin 是否可信：显式白名单命中，或来自可信网络位置。"""
    if "*" in allow_origins or origin in allow_origins:
        return True
    return is_trusted_network_host(origin_host(origin))
