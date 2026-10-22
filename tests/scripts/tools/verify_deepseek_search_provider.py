#!/usr/bin/env python3
"""验证 DeepSeek 搜索 provider 已正确注册并接入工具链路（静态验证，不调真实 API）

检查项：
1. model_config 默认值与 model_routing.yaml 都注册了 deepseek provider
2. provider_mapping 中 deepseek 模型映射到 deepseek 搜索
3. WebSearchTool 存在 _search_deepseek / _preprocess_deepseek_results / 回退逻辑
4. 单元测试文件存在

用法：
    python tests/scripts/tools/verify_deepseek_search_provider.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config.model_config import get_web_search_config, get_web_search_provider_for_llm
from core.tools.implementations import WebSearchTool


def main() -> int:
    failures = []

    # 1. 配置注册
    cfg = get_web_search_config()
    ds_cfg = cfg.get("providers", {}).get("deepseek", {})
    if ds_cfg.get("api_url") != "https://api.deepseek.com/v1/tools/search":
        failures.append(f"deepseek provider api_url 配置异常: {ds_cfg.get('api_url')}")
    if ds_cfg.get("api_key_env") != "DEEPSEEK_API_KEY":
        failures.append(f"deepseek api_key_env 应为 DEEPSEEK_API_KEY: {ds_cfg.get('api_key_env')}")
    if ds_cfg.get("fallback_provider") != "serper":
        failures.append(f"deepseek fallback_provider 应为 serper: {ds_cfg.get('fallback_provider')}")

    # 2. 映射
    mapped = get_web_search_provider_for_llm("deepseek")
    if mapped != "deepseek":
        failures.append(f"deepseek 模型的搜索 provider 映射应为 deepseek: {mapped}")

    # 3. 工具实现
    tool = WebSearchTool()
    for method in ("_search_deepseek", "_preprocess_deepseek_results",
                   "_deepseek_fallback_provider", "_search_by_provider", "_is_search_failure"):
        if not callable(getattr(tool, method, None)):
            failures.append(f"WebSearchTool 缺少方法: {method}")

    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    src = open(os.path.join(repo_root, "core/tools/implementations.py"), encoding="utf-8").read()
    if "if provider == \"deepseek\":" not in src:
        failures.append("_run 中缺少 deepseek 分支")

    # 4. 单测存在
    unit_test = os.path.join(repo_root, "tests/unit/test_web_search_deepseek.py")
    if not os.path.isfile(unit_test):
        failures.append("缺少单元测试 tests/unit/test_web_search_deepseek.py")

    if failures:
        print("验证失败:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("验证通过: deepseek 搜索 provider 注册、映射、实现与回退链路均就绪")
    return 0


if __name__ == "__main__":
    sys.exit(main())
