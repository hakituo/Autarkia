# -*- coding: utf-8 -*-
"""价格抓取用的 HTTP 客户端。

单独一个模块只为解决代理这一件事。环境里的 ``ALL_PROXY`` 经常写成
``socks://127.0.0.1:7897/``（Clash 系客户端就这么发），而 httpx 只认
``socks4/socks5``，默认的 ``trust_env`` 会让每轮抓取在建连接之前就抛
``Unknown scheme for proxy URL``——看着像「网不通」，其实是代理写法没人认，
而且 httpx 会拿这个非法值去解析，连本来能用的 ``HTTPS_PROXY`` 都被带崩。

所以这里 ``trust_env=False``，代理完全由本模块决定：按目标 scheme 取对应变量，
把裸 ``socks://`` 降级成 ``http://``（混合端口同一个口既讲 SOCKS 也讲 HTTP）。
``socks5://`` 保持原样交给 httpx，它缺依赖时报的错才有指导性。
"""

from __future__ import annotations

import os
from typing import Optional
from urllib.parse import urlsplit

import httpx

#: 各级代理变量，大小写都查：Windows 常见只有大写，容器里常见只有小写
_HTTPS_VARS = ("https_proxy", "http_proxy", "all_proxy")
_HTTP_VARS = ("http_proxy", "all_proxy")


def _split_proxy(value: str) -> str:
    """把裸 ``socks://`` 归一成 httpx 接受的写法。"""
    parts = urlsplit(value if "//" in value else f"//{value}")
    scheme = (parts.scheme or "http").lower()
    fixed = "http" if scheme == "socks" else scheme
    netloc = parts.netloc or value
    return f"{fixed}://{netloc}"


def _bypass(host: str) -> bool:
    """``no_proxy`` 命中就走直连，逗号分隔的后缀匹配（本地镜像源靠它）。"""
    raw = os.environ.get("no_proxy") or os.environ.get("NO_PROXY") or ""
    return any(
        host == item or host.endswith("." + item.lstrip("."))
        for item in (entry.strip() for entry in raw.split(","))
        if item
    )


def proxy_for(url: str) -> Optional[str]:
    """解析该 URL 该用的代理；不需要或没有可用代理时返回 None（直连）。"""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if not host or _bypass(host):
        return None
    for name in _HTTPS_VARS if parts.scheme == "https" else _HTTP_VARS:
        value = os.environ.get(name) or os.environ.get(name.upper())
        if value:
            return _split_proxy(value)
    return None


def client(url: str, timeout: float, user_agent: str, accept: str) -> httpx.AsyncClient:
    """建一次性的抓取客户端（调用方用 ``async with`` 关掉）。"""
    return httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        trust_env=False,
        proxy=proxy_for(url),
        headers={"User-Agent": user_agent, "Accept": accept},
    )
