#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""前缀布局埋点回归测试。

固化三件事：
1. 资料段（working_set）夹在 system 与历史之间时，被判定为断点，
   working_set 一变就白算 `stable_blocks - reusable_blocks` 块；
2. 没有资料段时，system 与历史天然连续，不产生额外损失；
3. 埋点只写日志、不改请求内容，关闭开关后不落盘也不报错。

token 估算在用例里固定住，避免依赖 C++ 分词器是否存在导致结果漂移。
"""

from __future__ import annotations

import json

import pytest

from core.agents.chat_agent_components.persona_system.prompt import cache_prefix_trace as trace


def _pin_tokens(monkeypatch, mapping):
    """把 token 估算钉成固定表，未列出的文本回退成字符数。"""
    monkeypatch.setattr(
        trace,
        "_estimate_tokens",
        lambda text: mapping.get(text, len(text)),
    )


def _history(*contents):
    return [{"role": "user", "content": text} for text in contents]


# ---------------------------------------------------------------- 分段与断裂点


def test_working_set_is_reported_as_break_point(monkeypatch):
    _pin_tokens(monkeypatch, {"S" * 10: 1000, "W" * 10: 500, "H" * 10: 3000})
    layout = trace.build_prefix_layout(
        static_prompt="S" * 10,
        working_set_prompt="W" * 10,
        history_messages=_history("H" * 10),
        key="core_ye:d3adbeef",
    )

    assert layout["break_at"] == "working_set"
    # 只有 system 那 7 块是任何情况下都能复用的
    assert layout["reusable_blocks"] == 7
    # 资料段稳定时上限是 (1000+500+3000)//128
    assert layout["stable_blocks"] == 35
    # 资料段一变，这 28 块全部白算
    assert layout["ws_break_blocks"] == 28
    assert layout["ws_break_tokens"] == 3500
    assert layout["key"] == "core_ye:d3adbeef"


def test_history_is_in_prefix_when_working_set_absent(monkeypatch):
    _pin_tokens(monkeypatch, {"S" * 10: 1000, "H" * 10: 3000})
    layout = trace.build_prefix_layout(
        static_prompt="S" * 10,
        working_set_prompt="",
        history_messages=_history("H" * 10),
    )

    assert layout["break_at"] == "none"
    # system + 历史连续，31 块全可复用
    assert layout["reusable_blocks"] == 31
    assert layout["stable_blocks"] == 31
    assert layout["ws_break_blocks"] == 0
    assert layout["ws_break_tokens"] == 0


def test_partial_block_is_not_counted(monkeypatch):
    """不足 128 tokens 不计块：与上游「最小命中 1 块」的口径一致。"""
    _pin_tokens(monkeypatch, {"S": 127, "W": 1})
    layout = trace.build_prefix_layout(
        static_prompt="S",
        working_set_prompt="W",
        history_messages=[],
    )

    assert layout["reusable_blocks"] == 0
    assert layout["stable_blocks"] == 1


def test_multimodal_history_counts_text_only(monkeypatch):
    calls = []

    def fake_estimate(text):
        calls.append(text)
        return len(text)

    monkeypatch.setattr(trace, "_estimate_tokens", fake_estimate)
    layout = trace.build_prefix_layout(
        static_prompt="system",
        working_set_prompt="",
        history_messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "看图"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,x"}},
                ],
            }
        ],
    )

    # 历史文本只取 text 块，不受 base64 影响
    assert layout["history_chars"] == 2
    assert "data:image/png" not in calls
    assert layout["history_count"] == 1


# ---------------------------------------------------------------- 估算口径


def test_chinese_estimate_matches_deepseek_ratio():
    """中文按 1.5 字符/token 估算，不能套用上下文预算的 0.6 口径（会高估一倍多）。"""
    assert trace._estimate_tokens("你" * 150) == 100


def test_ascii_estimate_uses_four_chars_per_token():
    assert trace._estimate_tokens("a" * 400) == 100


def test_mixed_text_estimate_is_additive():
    assert trace._estimate_tokens("你" * 15 + "a" * 40) == 20


# ---------------------------------------------------------------- 落盘与开关


def test_record_appends_one_jsonl_line(monkeypatch, tmp_path):
    target = tmp_path / "prompt_cache_prefix.log"
    monkeypatch.setattr(trace, "_prefix_trace_log", target)
    _pin_tokens(monkeypatch, {"S": 256, "W": 256})

    record = trace.record_prefix_layout(
        static_prompt="S",
        working_set_prompt="W",
        history_messages=_history("H"),
    )

    lines = target.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    written = json.loads(lines[0])
    assert written["ws_fp"] == record["ws_fp"]
    assert written["break_at"] == "working_set"
    assert written["timestamp"]


def test_trace_can_be_disabled(monkeypatch, tmp_path):
    target = tmp_path / "prompt_cache_prefix.log"
    monkeypatch.setattr(trace, "_prefix_trace_log", target)
    monkeypatch.setenv("XIAOYOU_PREFIX_TRACE", "0")
    _pin_tokens(monkeypatch, {"S": 256})

    record = trace.record_prefix_layout(
        static_prompt="S",
        working_set_prompt="",
        history_messages=[],
    )

    assert trace.trace_enabled() is False
    assert record["reusable_blocks"] == 2
    assert not target.exists()


def test_write_failure_does_not_raise(monkeypatch, tmp_path):
    """日志目录不可写时不能把聊天主链路带崩。"""
    monkeypatch.setattr(trace, "_prefix_trace_log", tmp_path / "no_such_dir" / "x.log")
    _pin_tokens(monkeypatch, {"S": 128})

    record = trace.record_prefix_layout(
        static_prompt="S",
        working_set_prompt="",
        history_messages=[],
    )

    assert record["static_tokens"] == 128


def test_clear_removes_log(monkeypatch, tmp_path):
    target = tmp_path / "prompt_cache_prefix.log"
    monkeypatch.setattr(trace, "_prefix_trace_log", target)
    target.write_text("{}\n", encoding="utf-8")

    trace.clear_prefix_trace_log()

    assert not target.exists()


# ---------------------------------------------------------------- 分组键


def test_trace_key_hides_raw_user_id():
    key = trace.make_trace_key("core_ye.json", "1234567890")

    assert key.startswith("core_ye:")
    assert "1234567890" not in key


def test_trace_key_empty_when_no_identity():
    assert trace.make_trace_key(None, None) == ""


@pytest.mark.parametrize("raw", ["0", "false", "False"])
def test_trace_disabled_values(monkeypatch, raw):
    monkeypatch.setenv("XIAOYOU_PREFIX_TRACE", raw)
    assert trace.trace_enabled() is False
