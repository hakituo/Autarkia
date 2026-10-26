"""fetch_url 工具的单元测试（mock 网络层，不依赖真实站点）。"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from core.tools.web_fetch import FetchResult, WebFetchTool, extract_text


def test_extract_strips_script_and_reads_title():
    """正文提取：保留标题与段落，剔除脚本和样式。"""
    html = (
        "<html><head><title>我的 站点</title><style>.a{color:red}</style></head>"
        "<body><h1>标题</h1><script>alert(1)</script>"
        "<p>正文一</p><p>正文二</p></body></html>"
    )
    title, text = extract_text(html)
    assert title == "我的 站点"
    assert "标题" in text
    assert "正文一" in text and "正文二" in text
    assert "alert" not in text
    assert "color:red" not in text


def test_validate_url_adds_scheme_and_rejects_others():
    """裸域名补 https；非 http(s) 协议与空值直接拒绝。"""
    assert WebFetchTool._validate_url("example.icu") == "https://example.icu"
    assert WebFetchTool._validate_url("https://example.icu/blog") == "https://example.icu/blog"
    with pytest.raises(ValueError):
        WebFetchTool._validate_url("file:///etc/passwd")
    with pytest.raises(ValueError):
        WebFetchTool._validate_url("")


@pytest.mark.asyncio
async def test_run_formats_and_truncates():
    """输出带 Title/URL/Content，超出 max_chars 时截断。"""
    tool = WebFetchTool()
    result = FetchResult(
        title="标题",
        text="字" * 2000,
        final_url="https://x.com/",
        content_type="text/html",
    )
    with (
        patch.object(WebFetchTool, "_assert_public_host", AsyncMock()),
        patch.object(WebFetchTool, "_fetch", AsyncMock(return_value=result)),
    ):
        out = await tool._run("https://x.com", max_chars=500)

    assert out.startswith("Title: 标题")
    assert "URL: https://x.com/" in out
    assert "Content:" in out
    assert "已截断" in out


@pytest.mark.asyncio
async def test_run_rejects_private_host():
    """本机/内网地址在发请求前就被拦住。"""
    tool = WebFetchTool()
    out = await tool._run("http://127.0.0.1/admin")
    assert out.startswith("Error")
    assert "内网" in out


@pytest.mark.asyncio
async def test_run_timeout_returns_error():
    """超时返回可读错误，不抛异常。"""
    tool = WebFetchTool()
    with (
        patch.object(WebFetchTool, "_assert_public_host", AsyncMock()),
        patch.object(WebFetchTool, "_fetch", AsyncMock(side_effect=asyncio.TimeoutError)),
    ):
        out = await tool._run("https://x.com")
    assert "超时" in out


@pytest.mark.asyncio
async def test_run_empty_body_returns_error():
    """页面没有正文时明确提示，避免模型编内容。"""
    tool = WebFetchTool()
    result = FetchResult(title="", text="   ", final_url="https://x.com/", content_type="text/html")
    with (
        patch.object(WebFetchTool, "_assert_public_host", AsyncMock()),
        patch.object(WebFetchTool, "_fetch", AsyncMock(return_value=result)),
    ):
        out = await tool._run("https://x.com")
    assert "没有可读正文" in out
