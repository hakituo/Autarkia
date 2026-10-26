# -*- coding: utf-8 -*-
"""价目表抓取的代理解析单测。

守一件会复发的事故：Clash 系客户端把 ``ALL_PROXY`` 写成 ``socks://127.0.0.1:7897/``，
httpx 只认 ``socks4/socks5``，于是每轮抓取在建连接之前就抛
``Unknown scheme for proxy URL``——看板上价格永远停在旧快照，现象却像「外网不通」。
"""

from __future__ import annotations

import pytest

from core.llm.token_stats.pricing import net as net_module

_PROXY_VARS = (
    "https_proxy",
    "HTTPS_PROXY",
    "http_proxy",
    "HTTP_PROXY",
    "all_proxy",
    "ALL_PROXY",
    "no_proxy",
    "NO_PROXY",
)


@pytest.fixture(autouse=True)
def clean_proxy_env():
    """先把代理变量清空：CI 机器上留没留 HTTP_PROXY 会直接改写结论。"""
    import os

    for name in _PROXY_VARS:
        os.environ.pop(name, None)
    yield
    for name in _PROXY_VARS:
        os.environ.pop(name, None)


def test_bare_socks_scheme_downgraded_to_http(monkeypatch):
    """裸 socks:// 换成 http://：混合端口同一个口既讲 SOCKS 也讲 HTTP，这样才抓得到。"""
    monkeypatch.setenv("all_proxy", "socks://127.0.0.1:7897/")
    assert net_module.proxy_for("https://openrouter.ai/api/v1/models") == "http://127.0.0.1:7897"


def test_scheme_specific_proxy_wins_over_all_proxy(monkeypatch):
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:7897/")
    monkeypatch.setenv("all_proxy", "socks://127.0.0.1:7897/")
    assert net_module.proxy_for("https://api-docs.deepseek.com/quick_start/pricing/") == (
        "http://127.0.0.1:7897"
    )


def test_socks5_scheme_kept_as_written(monkeypatch):
    """socks5:// 是 httpx 认的写法，不要替它改口——缺依赖时它的报错才有指导性。"""
    monkeypatch.setenv("all_proxy", "socks5://127.0.0.1:7897")
    assert net_module.proxy_for("http://api.example.com") == "socks5://127.0.0.1:7897"


def test_no_proxy_suffix_bypasses(monkeypatch):
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:7897/")
    monkeypatch.setenv("no_proxy", "internal.example.com,.test")
    assert net_module.proxy_for("https://mirror.internal.example.com/pricing") is None
    assert net_module.proxy_for("https://host.test/pricing") is None
    assert net_module.proxy_for("https://openrouter.ai/api") == "http://127.0.0.1:7897"


def test_no_proxy_env_means_direct(monkeypatch):
    """一个都没配就是直连：不拿 None 去把 httpx 的默认行为搅乱。"""
    assert net_module.proxy_for("https://openrouter.ai/api") is None
