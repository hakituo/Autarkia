#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""刷新断句 golden 语料：用 Python 真源重算 `segmentation_cases.json` 的 expected。

语料的用途与读写入口见 [segmentation_corpus] 模块文档。本脚本只做"重算 + 写回/校验"。

用法
----
    # 校验当前 expected 与真源是否一致（默认，不写文件）
    venv_cpu\\Scripts\\python.exe tests\\scripts\\android_frontend\\refresh_segmentation_golden.py

    # 改完规则后刷新 expected（会覆盖文件，之后必须人工看 diff）
    venv_cpu\\Scripts\\python.exe tests\\scripts\\android_frontend\\refresh_segmentation_golden.py --save
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from segmentation_corpus import (  # noqa: E402
    CASES_PATH,
    SECTIONS,
    compute_expected,
    load_cases,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="刷新/校验断句 golden 语料")
    ap.add_argument("--save", action="store_true", help="把重算结果写回语料文件")
    args = ap.parse_args()

    data = load_cases()
    params = data["params"]

    changed: list[str] = []
    missing: list[str] = []
    total = 0
    for section in SECTIONS:
        for case in data.get(section, []):
            total += 1
            expected = compute_expected(case, section, params)
            if not case.get("expected"):
                missing.append(f"{section} / {case['name']}")
            elif case["expected"] != expected:
                changed.append(
                    f"{section} / {case['name']}\n"
                    f"      旧: {case['expected']}\n"
                    f"      新: {expected}"
                )
            case["expected"] = expected

    if args.save:
        CASES_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"✅ 已刷新 {total} 条用例 → {CASES_PATH.name}")
        if missing:
            print(f"   其中 {len(missing)} 条原本是空 expected：")
            for name in missing:
                print(f"   - {name}")
        if changed:
            print(f"   ⚠️ {len(changed)} 条期望值发生变化，必须人工确认：")
            for item in changed:
                print(f"   - {item}")
        if any(
            item.startswith("web_smart_segment") for item in (*missing, *changed)
        ):
            print(
                "   ⚠️ web_smart_segment 只收「Web 与真源同行为」的用例："
                "请跑 clients/frontend/aveline-web 的 npm test 复核 Web 侧行为，"
                "不一致时替换用例，不要把真源期望硬套给 Web。"
            )
        return 0

    if missing:
        print(f"❌ {len(missing)} 条用例的 expected 为空（跑 --save 生成）：")
        for name in missing:
            print(f"   - {name}")
        return 1
    if changed:
        print(f"❌ {len(changed)} 条用例的 expected 与真源不一致：")
        for item in changed:
            print(f"   - {item}")
        print("\n确认是真源改动导致的话，跑 --save 刷新并人工看 diff。")
        return 1

    print(f"✅ {total} 条用例的 expected 与 Python 真源一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
