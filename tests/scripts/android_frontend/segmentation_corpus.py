#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""断句**行为语料**的加载与真源比对（`segmentation_cases.json` 的唯一读写入口）。

为什么要有这份语料
------------------
断句规则的真源只有 Python（`core/utils/text_segmenter*.py`），但实现有四份：Python（QQ）、
安卓 `utils/text/*.kt`、安卓 `ChatFlushManager.kt`、Web `utils/text.ts`。原先的一致性校验
（`verify_text_segmenter_parity.py`）只比常量字面量、**不执行 Kotlin/TS**，算法漂移检不出来。

这份语料把「输入 → 期望气泡」钉在一处：

- Python：`verify_text_segmenter_parity.py` 断言 `split_message` / `split_for_display` 和 Web 可兼容子集符合真源。
- 安卓：`SegmentationGoldenTest.kt` 读同一份语料断言 Kotlin 的同名入口。
- Web：`aveline-web/tests/segmentation.test.mjs` 读 `web_smart_segment` 子集，实际执行
  `src/utils/text.ts`，不引入测试框架依赖。

Web 子集（``web_smart_segment``）只收**两端行为明确一致**的边界用例：Web ``smartSegmentText``
是简化实现，与真源全功能并不等价，涉及时间戳剥离、Markdown 结构分组、换行分泡等特性的
行为不许进该子集，也不许由真源生成期望后硬套给 Web。准入流程：先用 Web 测试
（``npm --prefix clients/frontend/aveline-web test``）确认该输入在 Web 侧的输出与真源一致，
再写进语料；刷新后若发现两端不一致，只能替换/剔除用例，不许手改 expected 迁就。
期望值由真源生成，不手改：改完规则跑 `refresh_segmentation_golden.py --save` 并人工看 diff。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.utils.text_segmenter import (  # noqa: E402
    split_chat_message,
    split_for_display,
)

CASES_PATH = ROOT / "tests" / "scripts" / "android_frontend" / "segmentation_cases.json"

# 同一批基准结果还被 Web 的可兼容子集消费；Web 目前仍是简化实现。
SECTIONS = ("split_message", "split_for_display", "web_smart_segment")


def load_cases() -> dict:
    """读语料；文件缺失直接抛错，不静默降级。"""
    if not CASES_PATH.exists():
        raise AssertionError(f"找不到断句行为语料：{CASES_PATH}")
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def compute_expected(case: dict, section: str, params: dict) -> list[str]:
    """按语料里的参数跑一次真源。

    逗号断句概率固定为 0：真源那条分支带随机数，不固定就没法跨端比对。
    安卓侧 `TextSegmenter.splitForDisplay` 因此也把三个参数透传出来（不再写死默认值）。
    """
    kwargs = {
        "max_len": params["max_len"],
        "comma_split_prob": params["comma_split_prob"],
        "min_split_len": params["min_split_len"],
    }
    if section == "split_message":
        return split_chat_message(case["input"], **kwargs)
    # split_for_display 与 web_smart_segment 都走展示链路。web 子集是人工挑出来的
    # 「两端同行为」用例，期望仍由真源计算；两端不一致时必须换用例（见模块文档），
    # 不能把 Web 简化实现当成与真源全功能等价。
    return split_for_display(case["input"], **kwargs)


def _runner(section: str):
    return split_chat_message if section == "split_message" else split_for_display


def assert_python_matches(data: dict | None = None) -> int:
    """断言 Python 真源跑出的结果与语料记录的期望一致，返回用例总数。

    红了有两种含义——「真源被改坏」或「真源改了但没刷新语料」；两种情况都要求跑
    `refresh_segmentation_golden.py --save` 并人工看 diff。
    """
    data = data if data is not None else load_cases()
    params = data["params"]
    total = 0
    for section in SECTIONS:
        cases = data.get(section) or []
        if not cases:
            raise AssertionError(f"语料缺少 section：{section}")
        runner = _runner(section)
        for case in cases:
            total += 1
            expected = case.get("expected")
            if not expected:
                raise AssertionError(
                    f"用例 expected 为空：{section} / {case['name']}"
                    "（跑 refresh_segmentation_golden.py --save）"
                )
            actual = runner(case["input"], **{
                "max_len": params["max_len"],
                "comma_split_prob": params["comma_split_prob"],
                "min_split_len": params["min_split_len"],
            })
            assert actual == expected, (
                f"用例与真源不一致：{section} / {case['name']}\n"
                f"    语料: {expected}\n"
                f"    实际: {actual}"
            )
    return total
