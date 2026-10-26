"""真实标注集适配层 / 报告 / 并发预热的确定性单元测试（合成数据，不调用外部模型）。"""

from __future__ import annotations

import json

import pytest

from scripts.experiments.weighted_memory import real_client
from scripts.experiments.weighted_memory.real_cases import (
    load_real_cases,
    load_turns,
    sample_haystack,
    segment_turns,
)
from scripts.experiments.weighted_memory.real_report import mcnemar_exact

CID = "web_role_demo"


def _row(role, content, ts, event_type="chat_message"):
    return {"event_id": f"ev{ts}", "ts": ts, "role": role, "type": event_type, "content": content}


def _write_mainline(tmp_path, rows):
    mainline = tmp_path / "mainline"
    mainline.mkdir()
    (mainline / f"{CID}.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8"
    )
    return mainline


def _write_candidates(tmp_path, questions):
    path = tmp_path / "candidates.json"
    path.write_text(
        json.dumps({"meta": {"version": "demo"}, "questions": questions}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _question(qid, qtype, lines, keywords=("乌龙",), status="pending_review"):
    return {
        "id": qid,
        "conversation_id": CID,
        "type": qtype,
        "question": f"问题{qid}",
        "answer_keywords": list(keywords),
        "forbidden_keywords": [],
        "status": status,
        "sources": [{"mainline_line": line} for line in lines],
    }


def test_load_turns_drops_thoughts_and_merges_repeated_user_input(tmp_path):
    rows = [
        _row("user", "我喜欢乌龙茶", 0),
        _row("system", "思考", 1, "chat_thought"),
        _row("user", "我喜欢乌龙茶", 2),
        _row("assistant", "好", 3),
        _row("user", "", 4),
        _row("user", "长" * 3000, 5),
    ]
    turns, alias = load_turns(CID, _write_mainline(tmp_path, rows))

    assert [turn["turn_id"] for turn in turns] == ["e0", "e3", "e5"]
    assert alias == {2: 0}
    assert len(turns[-1]["content"]) == 1500


def test_segment_turns_cuts_only_before_user_on_idle_or_size():
    turns = [
        {"turn_id": "e0", "role": "user", "content": "a", "timestamp": 0.0},
        {"turn_id": "e1", "role": "assistant", "content": "b", "timestamp": 4000.0},
        {"turn_id": "e2", "role": "user", "content": "c", "timestamp": 4010.0},
        {"turn_id": "e3", "role": "user", "content": "d", "timestamp": 9000.0},
    ]
    segments = segment_turns({"id": CID, "turns": turns})

    # 回复即使隔了很久也留在本轮；空闲只在下一句用户输入前封口
    assert [segment["turn_ids"] for segment in segments] == [["e0", "e1", "e2"], ["e3"]]


def test_sample_haystack_keeps_evidence_windows_and_is_deterministic():
    turns = [{"turn_id": f"e{i}"} for i in range(200)]
    first = sample_haystack(turns, ["e100"], radius=5)
    second = sample_haystack(turns, ["e100"], radius=5)
    ids = [turn["turn_id"] for turn in first]

    assert ids == [turn["turn_id"] for turn in second]
    assert {f"e{i}" for i in range(95, 106)} <= set(ids)
    assert len(ids) == len(set(ids)) and 11 < len(ids) <= 33
    assert ids == sorted(ids, key=lambda tid: int(tid[1:]))


def test_load_real_cases_maps_abstain_alias_and_rejected(tmp_path):
    rows = [
        _row("user", "我喜欢乌龙茶", 0),
        _row("user", "我喜欢乌龙茶", 1),
        _row("assistant", "嗯", 2),
    ]
    mainline = _write_mainline(tmp_path, rows)
    candidates = _write_candidates(
        tmp_path,
        [
            _question("q1", "preference", [1]),
            _question("q2", "abstain", [], keywords=("没",)),
            _question("q3", "stable_fact", [0], status="rejected"),
        ],
    )
    case = load_real_cases(candidates, mainline, full=True)["cases"][0]
    queries = {query["id"]: query for query in case["queries"]}

    assert set(queries) == {"q1", "q2"}
    assert case["gold_facts"] == [
        {"fact_id": "f-q1", "keywords": ["乌龙"], "evidence_turns": ["e0"]}
    ]
    assert queries["q1"]["answer_keywords_any"] == ["乌龙"] and not queries["q1"]["unanswerable"]
    assert queries["q2"]["type"] == "refusal" and queries["q2"]["unanswerable"]
    assert queries["q2"]["gold_fact_ids"] == []


def test_mcnemar_exact_counts_discordant_pairs():
    rows_x = [{"query_id": f"q{i}", "passed": True} for i in range(5)]
    rows_y = [{"query_id": f"q{i}", "passed": False} for i in range(5)]

    assert mcnemar_exact(rows_x, rows_y) == {"x_only": 5, "y_only": 0, "p_value": 0.0625}
    assert mcnemar_exact(rows_x, rows_x)["p_value"] == 1.0


class _FlakyClient:
    """前 ``fail_times`` 次调用抛错，之后成功；记录每次真实调用的 prompt。"""

    def __init__(self, fail_times):
        self.model, self.temperature = "fake", 0.0
        self.fail_times = fail_times
        self.calls = []

    def _append_cache(self, item):  # 预热会临时替换成加锁版本
        return None

    def chat(self, system, user, *, max_tokens=400, json_mode=None):
        self.calls.append(user)
        if len(self.calls) <= self.fail_times:
            raise RuntimeError("HTTP 429")


def _job(client):
    for text in ("甲", "乙", "甲"):
        client.chat("sys", text, max_tokens=10)


def test_prefetch_dedupes_and_retries_failed_requests(monkeypatch):
    monkeypatch.setattr(real_client.time, "sleep", lambda _seconds: None)
    client = _FlakyClient(fail_times=1)
    stats = real_client.prefetch(client, _job, workers=1, label="t")

    assert stats["requests"] == 2
    assert sorted(client.calls) == ["乙", "甲", "甲"]


def test_prefetch_raises_when_retries_exhausted(monkeypatch):
    monkeypatch.setattr(real_client.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(real_client, "MAX_ROUNDS", 2)
    client = _FlakyClient(fail_times=10_000)

    with pytest.raises(real_client.PrefetchIncomplete):
        real_client.prefetch(client, _job, workers=1, label="t")
    assert len(client.calls) == 4


def test_ndcg_scores_zero_when_nothing_relevant_retrieved():
    from scripts.experiments.weighted_memory.metrics import ndcg_at_k

    assert ndcg_at_k([0, 0, 0], 5, gold_count=2) == 0.0
    # 理想序按金标数构造：两条金标只检回一条且排第一，不能算满分
    assert ndcg_at_k([1, 0, 0], 5, gold_count=2) < 1.0
    assert ndcg_at_k([1, 1, 0], 5, gold_count=2) == 1.0


class _BadJsonClient:
    model, temperature = "fake", 0.0

    def chat(self, system, user, *, max_tokens=400, json_mode=None):
        from scripts.experiments.weighted_memory.llm_client import LLMResult

        return LLMResult(
            text="", model="fake", prompt_tokens=0, completion_tokens=0, latency_seconds=0.0
        )

    def usage(self):
        return {"calls": 0, "cached_calls": 0, "prompt_tokens": 0, "completion_tokens": 0}


def test_arm_c_records_parse_failure_instead_of_dropping_segment():
    from scripts.experiments.weighted_memory.extraction import run_arm_c

    case = {
        "id": CID,
        "turns": [{"turn_id": "t1", "role": "user", "content": "我喜欢乌龙茶", "branch": "main"}],
    }
    notes = run_arm_c([case], _BadJsonClient(), segment_turns=4)

    assert [note["kind"] for note in notes] == ["skip"]
    assert notes[0]["parse_failed"] is True


def test_hybrid_index_finds_semantic_match_bm25_misses():
    from scripts.experiments.weighted_memory.retrieval import BM25Index
    from scripts.experiments.weighted_memory.retrieval.hybrid import HybridIndex

    docs = [
        {"doc_id": "d1", "text": "今天吃了牛肉汤"},
        {"doc_id": "d2", "text": "山城这边也多"},
    ]
    # 假向量：「城市」类文本与问题同向，其余正交
    vectors = {
        "我住在哪个城市": [1.0, 0.0],
        "山城这边也多": [0.9, 0.1],
        "今天吃了牛肉汤": [0.0, 1.0],
    }

    def embed(texts):
        return [vectors[text] for text in texts]

    assert BM25Index(docs).search("我住在哪个城市", 1) == []
    assert [hit["doc_id"] for hit in HybridIndex(docs, embed).search("我住在哪个城市", 1)] == ["d2"]
