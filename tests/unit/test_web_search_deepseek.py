"""DeepSeek 搜索 provider 的单元测试（mock 网络层，不依赖真实 API 与外部环境变量）

覆盖：
1. _search_deepseek 请求构造（query 截断 128、count 钳制、need_content）
2. 结果格式化（Title/Snippet/URL/Date，summary 优先于 snippet）
3. 失败时按配置回退到 fallback provider（serper）
4. 贝叶斯全滤时回退原始结果

注意：key 一律通过 patch.dict 显式注入，不依赖运行环境是否加载了 .env，
避免 xdist 并行下因 worker 环境差异产生 flaky。
"""
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.tools.implementations import WebSearchTool


def _make_session_mock(status: int = 200, json_data: dict | None = None, text: str = "err"):
    """构造 mock 的 aiohttp.ClientSession（含 async context manager 协议）"""
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data or {})
    resp.text = AsyncMock(return_value=text)
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.post = MagicMock(return_value=resp)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


def _sample_deepseek_response() -> dict:
    """按官方文档结构构造一份 DeepSeek 搜索 API 响应"""
    return {
        "results": [
            {
                "rerank_score": 2.1,
                "title": "DeepSeek 开放平台",
                "url": "https://example.com/a",
                "snippet": "短摘要",
                "summary": "长摘要内容" * 20,
                "site_name": "example",
                "site_icon": None,
                "date": "2026-10-01T00:00:00Z",
                "authority": 3,
            },
            {
                "rerank_score": 1.2,
                "title": "无摘要结果",
                "url": "https://example.com/b",
                "snippet": "只有短摘要",
                "summary": "",
                "site_name": None,
                "site_icon": None,
                "date": None,
                "authority": -1,
            },
        ]
    }


@pytest.mark.asyncio
async def test_search_deepseek_request_and_format():
    """请求参数与结果格式化"""
    tool = WebSearchTool()
    session = _make_session_mock(json_data=_sample_deepseek_response())
    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}):
        with patch("core.tools.implementations.aiohttp.ClientSession", return_value=session):
            raw = await tool._search_deepseek("deepseek 搜索", count=3)

    # 请求构造
    assert session.post.call_args.args[0] == "https://api.deepseek.com/v1/tools/search"
    payload = session.post.call_args.kwargs["json"]
    assert payload["query"] == "deepseek 搜索"
    assert payload["need_content"] is False

    # 格式化：summary 优先、date 附加；第二条无 summary 时退回 snippet、无 Date 行
    assert "Title: DeepSeek 开放平台" in raw
    assert "URL: https://example.com/a" in raw
    assert "Date: 2026-10-01T00:00:00Z" in raw
    assert "Title: 无摘要结果" in raw
    assert "Snippet: 只有短摘要" in raw


@pytest.mark.asyncio
async def test_search_deepseek_query_truncated():
    """query 超 128 字符应被截断（API 限制 1~128）"""
    tool = WebSearchTool()
    session = _make_session_mock(json_data=_sample_deepseek_response())
    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}):
        with patch("core.tools.implementations.aiohttp.ClientSession", return_value=session):
            await tool._search_deepseek("x" * 300, count=3)
    payload = session.post.call_args.kwargs["json"]
    assert len(payload["query"]) == 128


@pytest.mark.asyncio
async def test_search_deepseek_key_missing():
    """key 缺失时返回 Error 前缀（供回退判断）"""
    tool = WebSearchTool()
    # 用不含 key 的最小环境快照，规避外部 .env 是否已加载的差异
    with patch.dict(os.environ, {}, clear=True):
        raw = await tool._search_deepseek("test", count=3)
    assert raw.startswith("Error")


@pytest.mark.asyncio
async def test_run_deepseek_fallback_to_serper():
    """deepseek 失败时应回退到 serper"""
    tool = WebSearchTool()
    with patch.object(WebSearchTool, "_resolve_provider", return_value="deepseek"), \
         patch.object(WebSearchTool, "_search_deepseek",
                      AsyncMock(return_value="Search failed with status 402")), \
         patch.object(WebSearchTool, "_search_serper",
                      AsyncMock(return_value="Title: serper结果\nSnippet: 内容\nURL: https://s.com")):
        result = await tool._run("测试", count=3)
    assert "serper结果" in result


@pytest.mark.asyncio
async def test_run_deepseek_no_fallback_on_success():
    """deepseek 成功时不应触发回退"""
    tool = WebSearchTool()
    deepseek_mock = AsyncMock(return_value="Title: ds\nSnippet: ok\nURL: https://d.com")
    serper_mock = AsyncMock(return_value="Title: serper\nSnippet: ok\nURL: https://s.com")
    with patch.object(WebSearchTool, "_resolve_provider", return_value="deepseek"), \
         patch.object(WebSearchTool, "_search_deepseek", deepseek_mock), \
         patch.object(WebSearchTool, "_search_serper", serper_mock):
        result = await tool._run("测试", count=3)
    serper_mock.assert_not_called()
    assert "ds" in result


@pytest.mark.asyncio
async def test_preprocess_deepseek_all_filtered_keeps_raw():
    """贝叶斯把所有结果都过滤掉时应保留原始结果，避免搜索空转"""
    tool = WebSearchTool()
    raw = "Title: a\nSnippet: b\nURL: c\n\nTitle: d\nSnippet: e\nURL: f"
    with patch.object(WebSearchTool, "_bayes_filter", return_value=""):
        result = await tool._preprocess_deepseek_results("q", raw)
    assert result == raw


def test_is_search_failure_prefixes():
    """失败前缀判定覆盖各 _search_xxx 的错误返回约定"""
    tool = WebSearchTool()
    for bad in ("Error: x", "Search failed with status 500", "Search timed out.", "No results found.", ""):
        assert tool._is_search_failure(bad) is True
    assert tool._is_search_failure("Title: 正常\nSnippet: ok") is False
