# -*- coding: utf-8 -*-
"""LLM token 用量统计的单元测试。

覆盖三件事：
1. 日志字段归一：历史记录（无 completion）与新记录（有 completion）都要正确；
2. 聚合：日 / 月分桶、模型分布、补零、筛选；
3. 落盘与接口：log_llm_usage 写出的字段、/api/v1/token-stats 的响应结构。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.llm import llm_logger
from core.llm.token_stats import aggregate, build_overview, load_records, normalize_record


def _record(
    timestamp: str,
    model: str = "m1",
    provider: str = "openai_compat",
    prompt: int = 1000,
    hit: int = 600,
    miss: int = 400,
    completion=None,
    total=None,
    source: str = "streaming.py::stream_chat_impl",
) -> dict:
    record = {
        "timestamp": timestamp,
        "provider": provider,
        "model": model,
        "source": source,
        "hit_tokens": hit,
        "miss_tokens": miss,
        "prompt_tokens": prompt,
    }
    if completion is not None:
        record["completion_tokens"] = completion
    if total is not None:
        record["total_tokens"] = total
    return record


def _write_log(path: Path, records: list) -> Path:
    path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in records) + "\n",
        encoding="utf-8",
    )
    return path


# ==================== 字段归一 ====================


def test_normalize_legacy_record_without_completion():
    """历史记录没有 completion：prompt 回退 hit+miss，输出保持 None。"""
    record = normalize_record(_record("2026-08-16T23:54:35.325712+08:00", prompt=0, hit=0, miss=0))
    assert record is not None
    assert record["prompt_tokens"] == 0
    assert record["completion_tokens"] is None
    assert record["total_tokens"] == 0
    assert record["has_completion"] is False
    assert record["date"] == "2026-08-16"


def test_normalize_new_record_keeps_completion_and_total():
    record = normalize_record(
        _record(
            "2026-10-22T20:00:00+08:00",
            prompt=880,
            hit=600,
            miss=280,
            completion=120,
            total=1000,
        )
    )
    assert record is not None
    assert (record["prompt_tokens"], record["completion_tokens"], record["total_tokens"]) == (
        880,
        120,
        1000,
    )
    assert record["has_completion"] is True
    assert record["month"] == "2026-10"


def test_normalize_skips_bad_timestamp():
    assert normalize_record({"timestamp": "not-a-time", "model": "m"}) is None


# ==================== 聚合 ====================


def test_aggregate_day_and_month_buckets():
    records = [
        normalize_record(_record("2026-08-31T23:00:00+08:00")),
        normalize_record(_record("2026-09-01T01:00:00+08:00", completion=50)),
    ]
    day = aggregate(records, granularity="day")
    assert [bucket["key"] for bucket in day["series"]] == ["2026-08-31", "2026-09-01"]
    assert day["totals"]["requests"] == 2
    assert day["totals"]["prompt_tokens"] == 2000
    assert day["totals"]["completion_tokens"] == 50
    assert day["totals"]["hit_rate"] == 0.6

    month = aggregate(records, granularity="month")
    assert [bucket["key"] for bucket in month["series"]] == ["2026-08", "2026-09"]


def test_aggregate_breakdown_top_merges_rest():
    records = [
        normalize_record(_record("2026-09-01T10:00:00+08:00", model=name, prompt=size))
        for name, size in (("a", 3000), ("b", 2000), ("c", 1000))
    ]
    result = aggregate(records, top=2)
    assert [row["key"] for row in result["by_model"]] == ["a", "b", "其他"]
    assert result["by_model"][-1]["prompt_tokens"] == 1000
    assert sum(row["requests"] for row in result["by_model"]) == 3


# ==================== 报表与筛选 ====================


def test_build_overview_fills_gap_days(tmp_path):
    log = _write_log(
        tmp_path / "stats.log",
        [
            _record("2026-09-01T10:00:00+08:00", model="a"),
            _record("2026-09-03T10:00:00+08:00", model="b", completion=10),
        ],
    )
    data = build_overview(log_path=log)
    assert [bucket["key"] for bucket in data["series"]] == [
        "2026-09-01",
        "2026-09-02",
        "2026-09-03",
    ]
    assert data["series"][1]["requests"] == 0
    assert data["coverage"]["records"] == 2
    assert data["coverage"]["with_completion"] == 1
    assert data["options"]["models"] == ["a", "b"]


def test_build_overview_filters_by_model_and_range(tmp_path):
    log = _write_log(
        tmp_path / "stats.log",
        [
            _record("2026-09-01T10:00:00+08:00", model="a"),
            _record("2026-09-02T10:00:00+08:00", model="b"),
            _record("2026-09-03T10:00:00+08:00", model="b"),
        ],
    )
    data = build_overview(start="2026-09-02", end="2026-09-03", model="b", log_path=log)
    assert data["coverage"]["records"] == 2
    assert data["totals"]["prompt_tokens"] == 2000
    assert data["series"][0]["key"] == "2026-09-02"
    # 筛选不影响可选模型列表
    assert data["options"]["models"] == ["a", "b"]


def test_load_records_skips_broken_lines(tmp_path):
    path = tmp_path / "stats.log"
    path.write_text(
        '{"timestamp": "2026-09-01T10:00:00+08:00", "model": "a"}\n'
        "not json\n"
        '{"timestamp": "bad", "model": "b"}\n',
        encoding="utf-8",
    )
    assert len(load_records(path)) == 1


# ==================== 写入与接口 ====================


def test_log_llm_usage_records_completion_fields(tmp_path, monkeypatch):
    log_path = tmp_path / "prompt_cache_stats.log"
    monkeypatch.setattr(llm_logger, "_prompt_cache_stats_log", log_path)
    llm_logger.log_llm_usage(
        "openai_compat",
        "deepseek-v4-flash",
        {
            "prompt_tokens": 900,
            "completion_tokens": 100,
            "total_tokens": 1000,
            "prompt_cache_hit_tokens": 700,
            "prompt_cache_miss_tokens": 200,
            "completion_tokens_details": {"reasoning_tokens": 40},
        },
        extra={"mode": "stream"},
    )
    record = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["prompt_tokens"] == 900
    assert record["completion_tokens"] == 100
    assert record["total_tokens"] == 1000
    assert record["reasoning_tokens"] == 40
    assert record["hit_rate"] == round(700 / 900, 4)


def test_log_llm_usage_accepts_dashscope_field_names(tmp_path, monkeypatch):
    log_path = tmp_path / "prompt_cache_stats.log"
    monkeypatch.setattr(llm_logger, "_prompt_cache_stats_log", log_path)
    llm_logger.log_llm_usage("dashscope", "qwen-max", {"input_tokens": 300, "output_tokens": 60})
    record = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["prompt_tokens"] == 300
    assert record["completion_tokens"] == 60
    assert record["total_tokens"] == 360


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import core.llm.token_stats.report as report_module
    import routers.v1.token_stats as router_module

    log = _write_log(
        tmp_path / "stats.log",
        [
            _record("2026-09-01T10:00:00+08:00", model="a", completion=30),
            _record("2026-09-02T10:00:00+08:00", model="b"),
        ],
    )
    monkeypatch.setattr(report_module, "get_stats_log_path", lambda: log)

    # 这几条用例只管 token 口径；价目表要联网，一律挡掉
    async def _no_catalog(force: bool = False):
        return None

    monkeypatch.setattr(router_module, "_catalog_or_none", _no_catalog)
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api/v1")
    return TestClient(app)


def test_router_overview(client):
    response = client.get("/api/v1/token-stats/overview?granularity=day")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    data = payload["data"]
    assert data["totals"]["requests"] == 2
    assert data["totals"]["completion_tokens"] == 30
    assert data["filters"]["granularity"] == "day"


def test_router_overview_rejects_bad_granularity(client):
    assert client.get("/api/v1/token-stats/overview?granularity=week").status_code == 422


def test_router_dashboard_serves_html(client):
    response = client.get("/api/v1/token-stats/dashboard")
    assert response.status_code == 200
    assert "LLM 用量" in response.text
