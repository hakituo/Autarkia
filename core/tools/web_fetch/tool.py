"""fetch_url 工具：按网址打开页面并返回正文，与 web_search 分工。"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from urllib.parse import urlparse

import aiohttp
from pydantic import BaseModel, Field

from core.utils.logger import get_logger

from ..base import BaseTool
from .extract import FetchResult, clean_text, extract_text

logger = get_logger("web_fetch_tool")

FETCH_TIMEOUT = 20
DEFAULT_MAX_CHARS = 6000
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_URL_LENGTH = 2048

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
_ACCEPTED_CONTENT_TYPES = (
    "text/",
    "application/json",
    "application/xml",
    "application/xhtml",
)
# 只拦真实内网/本机段；198.18.0.0/15 与 2001:2::/48 是本地代理的 fake-ip，故意放行。
_BLOCKED_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.168.0.0/16",
        "::/128",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    )
)


class WebFetchInput(BaseModel):
    url: str = Field(
        description="要打开的网址，可直接传用户发来的链接或域名（example.icu 会按 https 补全）"
    )
    max_chars: int = Field(
        default=DEFAULT_MAX_CHARS,
        description="返回正文的最大字符数，默认 6000；页面很长时可调大，上限 20000",
    )


class WebFetchTool(BaseTool):
    name = "fetch_url"
    description = (
        "按网址打开网页并返回正文：用户直接发来链接、让你看某个页面/网站时用它。"
        "搜索关键词、找最新资料用 web_search，不要把整条网址当搜索词。"
        "页面打不开或没有正文时如实说明，不要凭网址猜内容。"
    )
    short_description = "打开指定网址读取网页正文"
    category = "utility"
    args_schema = WebFetchInput

    async def _run(self, url: str, max_chars: int = DEFAULT_MAX_CHARS) -> str:
        try:
            target = self._validate_url(url)
            limit = max(500, min(int(max_chars or DEFAULT_MAX_CHARS), 20000))
            await self._assert_public_host(urlparse(target).hostname or "")
            result = await self._fetch(target)
        except ValueError as exc:
            return f"Error: {exc}"
        except asyncio.TimeoutError:
            logger.warning("[WebFetch] 抓取超时: %s", url)
            return "Error: 抓取超时，页面长时间没有响应。"
        except aiohttp.ClientError as exc:
            logger.warning("[WebFetch] 请求失败: %s (%s)", url, exc)
            return f"Error: 请求失败（{type(exc).__name__}）。"
        except Exception as exc:  # noqa: BLE001 - 工具边界必须返回可读错误
            logger.warning("[WebFetch] 抓取异常: %s (%s)", url, exc)
            return f"Error: 抓取异常（{type(exc).__name__}）。"

        body = result.text.strip()
        if not body:
            return "Error: 页面没有可读正文（可能是纯脚本渲染或需要登录）。"
        if len(body) > limit:
            body = body[:limit].rstrip() + "\n...(已截断)"

        lines = []
        if result.title:
            lines.append(f"Title: {result.title}")
        lines.append(f"URL: {result.final_url}")
        lines.append("Content:")
        lines.append(body)
        logger.info(
            "[WebFetch] 抓取完成: %s, 正文%d字, 类型=%s",
            result.final_url,
            len(body),
            result.content_type or "unknown",
        )
        return "\n".join(lines)

    @staticmethod
    def _validate_url(url: str) -> str:
        raw = str(url or "").strip()
        if not raw:
            raise ValueError("网址为空。")
        if len(raw) > MAX_URL_LENGTH:
            raise ValueError("网址过长。")
        # 用户常直接发 example.icu 这种裸域名，补默认协议；显式写了别的协议则拒绝。
        if re.match(r"^[A-Za-z][A-Za-z0-9+.\-]*:", raw):
            parsed = urlparse(raw)
            if parsed.scheme not in ("http", "https"):
                raise ValueError("只支持 http/https 网址。")
        else:
            parsed = urlparse("https://" + raw.lstrip("/"))
        if not parsed.hostname:
            raise ValueError("网址缺少域名。")
        return parsed.geturl()

    @classmethod
    async def _assert_public_host(cls, hostname: str) -> None:
        """拒绝本机与内网地址，避免借抓取探测内网服务。"""
        host = hostname.strip().lower().rstrip(".")
        if not host:
            raise ValueError("网址缺少域名。")
        if host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".internal")):
            raise ValueError("不允许抓取本机或内网地址。")
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None:
            cls._assert_public_ip(literal)
            return
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, None)
        except socket.gaierror as exc:
            raise ValueError(f"域名解析失败: {host}。") from exc
        for info in infos:
            address = str(info[4][0]).split("%")[0]
            try:
                parsed = ipaddress.ip_address(address)
            except ValueError:
                continue
            cls._assert_public_ip(parsed)

    @staticmethod
    def _assert_public_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
        # 本机开 Clash 这类代理时 DNS 会返回 fake-ip，用 is_private 会误伤所有公网站点。
        if address.is_multicast:
            raise ValueError("不允许抓取本机或内网地址。")
        for network in _BLOCKED_NETWORKS:
            if address.version == network.version and address in network:
                raise ValueError("不允许抓取本机或内网地址。")

    async def _fetch(self, url: str) -> FetchResult:
        timeout = aiohttp.ClientTimeout(total=FETCH_TIMEOUT)
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "text/plain;q=0.8,*/*;q=0.5"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        }
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url, allow_redirects=True) as response:
                if response.status >= 400:
                    raise ValueError(f"页面返回 HTTP {response.status}。")
                content_type = str(response.headers.get("Content-Type", "")).lower()
                if content_type and not content_type.startswith(_ACCEPTED_CONTENT_TYPES):
                    raise ValueError(f"不支持的内容类型: {content_type.split(';')[0]}。")
                raw = await self._read_limited(response)
                charset = response.charset or "utf-8"
                try:
                    body = raw.decode(charset, errors="replace")
                except LookupError:
                    body = raw.decode("utf-8", errors="replace")
                final_url = str(response.url)

        if "html" in content_type or not content_type:
            title, text = extract_text(body)
        else:
            title, text = "", clean_text(body)
        return FetchResult(title=title, text=text, final_url=final_url, content_type=content_type)

    @staticmethod
    async def _read_limited(response: aiohttp.ClientResponse) -> bytes:
        buffer = bytearray()
        async for chunk in response.content.iter_chunked(65536):
            buffer.extend(chunk)
            if len(buffer) >= MAX_RESPONSE_BYTES:
                break
        return bytes(buffer)
