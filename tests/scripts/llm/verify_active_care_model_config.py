#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证 Active Care 统一走 MiniMax M Plan 的 M3.1 Flash

检查点：
1. active_care_models 全部指向 cloud:minimax:plan:MiniMax-M3.1-Flash
2. 不再配置 Active Care 二次回退
3. 配置访问层能识别全部 Active Care 主模型，且按角色解析到同一路由
4. .env 里存在 MINIMAX_PLAN_API_KEY（别名 plan 能被工厂注册）

用法：
    venv_cpu\\Scripts\\python.exe tests\\scripts\\llm\\verify_active_care_model_config.py

退出码：0=通过；非0=任一检查失败。
说明：诊断统一输出到 stderr，规避部分核心模块对 stdout 的重定向。
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
os.chdir(ROOT)


def _out(msg: str):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def check() -> int:
    failures = 0

    def _fail(msg: str):
        nonlocal failures
        failures += 1
        _out(msg)

    expected = "cloud:minimax:plan:MiniMax-M3.1-Flash"

    # 1. 读取 model_routing.yaml，定位 active_care_models 区段
    yaml_text = Path(ROOT, "config", "yaml", "sections", "model_routing.yaml").read_text(
        encoding="utf-8"
    )
    start = yaml_text.find("active_care_models:")
    end = yaml_text.find("journal_model:", start)
    block = yaml_text[start:end] if start >= 0 else ""

    if not block:
        _fail("model_routing.yaml 缺少 active_care_models 区段")

    # 2. 主链不得再引用任何 OpenRouter 免费端点
    for bad in ["openrouter/free", "minimax/minimax-m3:free", "minimax/minimax-m2.7:free"]:
        if bad in block:
            _fail(f"active_care_models 仍引用具体免费端点 '{bad}'")

    # 3. 每个字段都必须指向 ACTIVECARE key 的 flash
    field_expect = {
        "default:": expected,
        "aveline:": expected,
        "ye:": expected,
        "ling:": expected,
        "decision:": expected,
        "auto_eat:": expected,
        "priority_analysis:": expected,
    }
    for field, want in field_expect.items():
        line = next((ln for ln in block.splitlines() if ln.strip().startswith(field)), None)
        if line is None:
            _fail(f"yaml 缺少字段 {field}")
            continue
        if want not in line:
            _fail(f"{field} 未指向 {want}，当前: {line.strip()}")

    # 4. 配置访问层应返回唯一主模型、无回退
    sys.path.insert(0, str(ROOT))
    from config.model_config import (
        get_active_care_content_model,
        get_active_care_primary_models,
        get_fallback_model_for_active_care,
    )

    primary = get_active_care_primary_models()
    if primary != {expected}:
        _fail(f"Active Care 主模型集合异常: {sorted(primary)}")
    if get_fallback_model_for_active_care() != "":
        _fail(f"Active Care fallback 异常: {get_fallback_model_for_active_care()!r}")

    # 5. 当前两个自主角色（Aveline / Ye）都解析到同一路由
    for persona in ("Aveline", "Aveline", "Ye", "ye", "Ling"):
        resolved = get_active_care_content_model(persona)
        if resolved != expected:
            _fail(f"角色 {persona} 的 Active Care 模型为 {resolved!r}，期望 {expected!r}")
        else:
            _out(f"[OK] {persona} -> {resolved}")

    # 6. 路由里的别名必须真的注册进 cloud_provider_keys，否则会静默回退到 default key
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except Exception:  # noqa: BLE001 - 缺依赖时退回进程环境变量
        pass
    if not os.getenv("MINIMAX_PLAN_API_KEY"):
        _fail("缺少环境变量 MINIMAX_PLAN_API_KEY（M Plan 订阅 Key 未配置）")
    else:
        from config.integrated_config import get_settings

        alias = expected.split(":")[2]
        keys = get_settings().model.cloud_provider_keys.get("minimax", {})
        if alias not in keys:
            _fail(f"别名 {alias!r} 未注册（现有: {sorted(keys)}），路由会回退到 default key")
        elif keys[alias].api_key != os.getenv("MINIMAX_PLAN_API_KEY"):
            _fail(f"别名 {alias!r} 的 api_key 与 MINIMAX_PLAN_API_KEY 不一致")
        else:
            _out(f"[OK] MINIMAX_PLAN_API_KEY 已注册为别名 {alias}")

    if failures:
        _out(f"汇总: {failures} 项检查失败")
        return 1
    _out(f"汇总: Active Care 已统一走 {expected}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(check())
    except Exception:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        sys.exit(1)
