#!/usr/bin/env python3
"""验证 fetch_url 工具：注册、常驻、发现元数据、prompt 分工与真实抓取。

用法：
    python tests/scripts/tools/verify_web_fetch_tool.py            # 含真实抓取
    python tests/scripts/tools/verify_web_fetch_tool.py --offline  # 仅静态校验
"""

import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

LIVE_URL = "https://example.icu"


def _check_registry(failures: list[str]) -> None:
    from core.tools.registry import ToolRegistry, register_all_tools
    from core.tools.tool_metadata import get_tool_domain

    registry = ToolRegistry()
    register_all_tools(registry)
    tool = registry.get_tool("fetch_url")
    if tool is None:
        failures.append("fetch_url 未注册进 ToolRegistry")
        return
    if get_tool_domain("fetch_url") != "information":
        failures.append(f"fetch_url 发现领域应为 information: {get_tool_domain('fetch_url')}")
    if tool.category != "utility":
        failures.append(f"fetch_url category 应为 utility: {tool.category}")


def _check_profiles(failures: list[str]) -> None:
    data = json.loads((PROJECT_ROOT / "config" / "tool_profiles.json").read_text(encoding="utf-8"))
    entries = [("defaults", data["defaults"])]
    entries.extend((scope, cfg) for scope, cfg in data.get("roles", {}).items())
    for scope, cfg in entries:
        if "fetch_url" not in cfg.get("resident", []):
            failures.append(f"{scope} 常驻列表缺少 fetch_url")
    if not any("fetch_url" in route.get("tools", []) for route in data.get("routes", [])):
        failures.append("routes 中没有指向 fetch_url 的网址路由")


def _check_guides(failures: list[str]) -> None:
    from core.agents.chat_agent_components.persona_system.prompt.components import (
        build_web_tools_guide,
    )

    both = build_web_tools_guide(["fetch_url", "web_search"])
    if "fetch_url" not in both or "web_search" not in both:
        failures.append("两种联网工具都在时，引导未说明分工")
    if "不要把整条网址丢给 web_search" not in both:
        failures.append("引导缺少「网址不要当搜索词」的反例")
    only_fetch = build_web_tools_guide(["fetch_url"])
    if "【联网搜索】" in only_fetch:
        failures.append("只有 fetch_url 时不应注入搜索段落")
    if build_web_tools_guide([]):
        failures.append("没有联网工具时不应注入引导")


async def _check_live(failures: list[str]) -> None:
    from core.tools.web_fetch import WebFetchTool

    tool = WebFetchTool()
    result = await tool._run(url=LIVE_URL, max_chars=4000)
    if result.startswith("Error"):
        failures.append(f"真实抓取失败: {result}")
        return
    lowered = result.lower()
    if "hakituo" not in lowered and "autarkia" not in lowered:
        failures.append("抓取结果里没有站点自身内容（hakituo / Autarkia）")
    print(f"[live] 抓取 {LIVE_URL} 成功，返回 {len(result)} 字")
    print("-" * 60)
    print(result[:600])
    print("-" * 60)


def main() -> int:
    failures: list[str] = []
    _check_registry(failures)
    _check_profiles(failures)
    _check_guides(failures)

    if "--offline" not in sys.argv:
        asyncio.run(_check_live(failures))
    else:
        print("[live] 已跳过真实抓取")

    if failures:
        print("验证失败:")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("验证通过: fetch_url 已注册、常驻、按网址走 fetch / 关键词走搜索的引导就绪")
    return 0


if __name__ == "__main__":
    sys.exit(main())
