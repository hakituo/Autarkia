"""C6/C7 离线原型的确定性单元测试（不调用外部模型）。"""

from __future__ import annotations

from scripts.experiments.weighted_memory.cases import segment_case
from scripts.experiments.weighted_memory.extraction import run_arm_a
from scripts.experiments.weighted_memory.llm_client import LLMResult
from scripts.experiments.weighted_memory.metrics import (
    bootstrap_ci,
    gold_coverage,
    norm_text,
)
from scripts.experiments.weighted_memory.report import _choose_arm
from scripts.experiments.weighted_memory.retrieval import (
    BM25Index,
    filter_visible_docs,
    judge_answer,
)


def _case():
    return {
        "id": "branch_case",
        "active_branch": "main",
        "turns": [
            {"turn_id": "t1", "role": "user", "content": "主线一", "branch": "main"},
            {"turn_id": "t2", "role": "assistant", "content": "主线二", "branch": "main"},
            {"turn_id": "t3", "role": "user", "content": "支线一", "branch": "sibling"},
            {"turn_id": "t4", "role": "assistant", "content": "支线二", "branch": "sibling"},
            {"turn_id": "t5", "role": "user", "content": "主线三", "branch": "main"},
        ],
    }


def test_segment_case_splits_on_branch_change():
    segments = segment_case(_case(), 4)

    assert [segment["branch"] for segment in segments] == ["main", "sibling", "main"]
    assert [segment["turn_ids"] for segment in segments] == [["t1", "t2"], ["t3", "t4"], ["t5"]]


def test_bm25_respects_branch_filter():
    docs = [
        {"doc_id": "main", "text": "周五去杭州出差", "source_turns": ["t1"], "branch": "main"},
        {"doc_id": "sibling", "text": "周五去苏州", "source_turns": ["t2"], "branch": "sibling"},
        {"doc_id": "other", "text": "楼下有只橘猫", "source_turns": ["t3"], "branch": "main"},
    ]
    visible = filter_visible_docs(docs, "main")
    index = BM25Index(visible)

    results = index.search("周五去哪里", 5)

    assert [doc["doc_id"] for doc in results] == ["main"]


def test_judge_answer_distinguishes_update_and_refusal():
    current_city = {
        "answer_keywords": ["上海"],
        "forbidden_keywords": ["北京"],
        "type": "knowledge_update",
    }
    assert judge_answer(current_city, "你现在住在上海。")["passed"] is True
    assert judge_answer(current_city, "你之前在北京，现在在上海。")["passed"] is False

    unknown = {"unanswerable": True, "answer_keywords": [], "forbidden_keywords": []}
    assert judge_answer(unknown, "不知道，你没有提过。")["passed"] is True
    assert judge_answer(unknown, "你在一家互联网公司上班。")["passed"] is False


def test_gold_coverage_requires_evidence_intersection():
    gold = {"f1": {"keywords": ["乌龙"], "evidence_turns": ["t9"]}}

    wrong_source = [
        {"kind": "fact", "text": "用户喜欢乌龙茶", "source_turns": ["t1"], "provenance_ok": True}
    ]
    right_source = [
        {"kind": "fact", "text": "用户喜欢乌龙茶", "source_turns": ["t9"], "provenance_ok": True}
    ]

    assert gold_coverage(wrong_source, gold)["matched"] == 0
    assert gold_coverage(right_source, gold)["matched"] == 1


def test_bootstrap_ci_is_deterministic():
    first = bootstrap_ci([1.0, 0.0, 0.5], n_boot=200)
    second = bootstrap_ci([1.0, 0.0, 0.5], n_boot=200)

    assert first == second


def test_norm_text_normalizes_chinese_numbers_and_dates():
    assert norm_text("二百四十元") == "240元"
    assert norm_text("十月三号") == "10月3日"
    assert norm_text("三张") == "3张"
    assert norm_text("十分开心") == "十分开心"


def test_judge_answer_accepts_arabic_number():
    query = {"answer_keywords": ["二百四十"], "forbidden_keywords": []}

    assert judge_answer(query, "一共花了240元。")["passed"] is True
    assert judge_answer(query, "一共花了三百元。")["passed"] is False


def test_judge_answer_supports_any_keywords():
    query = {
        "answer_keywords": [],
        "answer_keywords_any": ["近", "不远"],
        "forbidden_keywords": [],
    }

    assert judge_answer(query, "不远。")["passed"] is True
    assert judge_answer(query, "很近。")["passed"] is True
    assert judge_answer(query, "很远。")["passed"] is False


class _FakeClient:
    model = "fake"
    temperature = 0.0
    json_mode = False

    def __init__(self, text: str):
        self._text = text

    def chat(self, system, user, *, max_tokens=400, json_mode=None):
        return LLMResult(
            text=self._text,
            model=self.model,
            prompt_tokens=1,
            completion_tokens=1,
            latency_seconds=0.0,
        )


def test_empty_summary_becomes_skip_note():
    notes = run_arm_a([_case()], _FakeClient('{"summary": ""}'))

    assert notes[0]["kind"] == "skip"
    assert notes[0]["text"] == ""


def test_valid_summary_is_kept():
    notes = run_arm_a([_case()], _FakeClient('{"summary": "用户提到主线一"}'))

    assert notes[0]["kind"] == "summary"
    assert notes[0]["text"] == "用户提到主线一"
    assert notes[0]["provenance_ok"] is True


def _c6(provenance=1.0, parse_fail=0.0):
    return {
        "metrics": {
            "A": {"provenance": {"rate": provenance}, "parse_failure_rate": parse_fail},
            "B": {"provenance": {"rate": provenance}, "parse_failure_rate": parse_fail},
            "C": {"provenance": {"rate": provenance}, "parse_failure_rate": parse_fail},
        },
        "usage": {"A": {}, "B": {}, "C": {}},
    }


def _c7(accuracy, recall=1.0, cross=0):
    return {
        "arms": {
            arm: {
                "cross_line": {"cross_line_evidence": cross},
                "answers": {"overall": {"rate": value}},
                "retrieval": {"recall": {"mean": recall}},
            }
            for arm, value in accuracy.items()
        }
    }


def test_decision_rule_respects_hard_constraints():
    c6 = _c6()
    c7 = _c7({"A": 0.6, "B": 0.5, "C": 0.9})

    assert _choose_arm(c6, c7)["chosen"] == "C"

    c6_bad = _c6(provenance=0.9)
    assert _choose_arm(c6_bad, c7)["chosen"] == "A"
