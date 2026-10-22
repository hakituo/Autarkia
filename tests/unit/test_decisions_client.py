#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Decisions API 客户端单测：响应解析与客户端构造。

影子模式、精编 state 的用例在 test_active_care_decision_engine.py。
"""

from __future__ import annotations

import pytest

from core.llm.decisions.client import (
    DecisionResult,
    DecisionsClient,
    resolve_decisions_client,
)


# ============================== 响应解析 ==============================


def test_parse_response_extracts_noul_and_choice():
    """解析 noul / choice / probabilities / confidence / usage。"""
    body = (
        '{"model":"microsoft-decision-1","answers":{'
        '"worth_contacting":{"type":"noul","noul":0.92},'
        '"retry_bucket":{"type":"choice","choice":"900",'
        '"probabilities":{"60":0.2,"900":0.7},"confidence":0.66}},'
        '"usage":{"input_tokens":273,"output_tokens":0,"cost":1.15e-05}}'
    )
    result = DecisionsClient._parse_response(body, "microsoft-decision-1", 1200.0)
    assert result is not None
    assert result.noul("worth_contacting") == pytest.approx(0.92)
    assert result.choice("retry_bucket") == "900"
    assert result.answers["retry_bucket"].probabilities["900"] == pytest.approx(0.7)
    assert result.answers["retry_bucket"].confidence == pytest.approx(0.66)
    assert result.input_tokens == 273
    assert result.output_tokens == 0
    assert result.cost_usd == pytest.approx(1.15e-05)
    assert result.latency_ms == pytest.approx(1200.0)


def test_parse_response_returns_none_on_bad_payload():
    """结构不符时返回 None 而不是抛异常。"""
    assert DecisionsClient._parse_response("not json", "m", 1.0) is None
    assert DecisionsClient._parse_response('{"answers": null}', "m", 1.0) is None
    assert DecisionsClient._parse_response("[]", "m", 1.0) is None


def test_missing_answer_returns_none():
    """取不存在的问题时返回 None，不 KeyError。"""
    result = DecisionResult(model="m", answers={})
    assert result.noul("nope") is None
    assert result.choice("nope") is None


# ============================== 客户端构造 ==============================


def test_resolve_client_reads_openrouter_key(monkeypatch):
    """key 与代理的解析口径与 factory.py 的 openrouter 分支一致。"""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("OPENROUTER_PROXY_URL", "http://127.0.0.1:7897")
    client = resolve_decisions_client()
    assert client.api_key == "sk-or-test"
    assert client.proxy == "http://127.0.0.1:7897"
    assert client.get_status()["api_key_configured"] is True


def test_resolve_client_falls_back_to_telegram_proxy(monkeypatch):
    """未配置 OPENROUTER_PROXY_URL 时复用 TELEGRAM_PROXY_URL。"""
    monkeypatch.delenv("OPENROUTER_PROXY_URL", raising=False)
    monkeypatch.setenv("TELEGRAM_PROXY_URL", "http://127.0.0.1:7897")
    client = resolve_decisions_client(api_key="k")
    assert client.proxy == "http://127.0.0.1:7897"
