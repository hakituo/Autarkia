"""真实聊天标注集 → 离线原型的 case 结构（只读 output/evaluation，不入库数据）。

输入：
- ``output/evaluation/real_qa_candidates_v1.json``：已审核的题目（出处为主线行号）；
- ``output/evaluation/real_qa_mainline/<会话>.jsonl``：主线事件（已过世界线闸门 + 推断去重）。

每个会话整条主线是一个 case；三臂看到同一份输入。预处理对三臂一致：
去掉思考记录、合并连续重复提交的同一句用户输入、单条正文截断。
"""

from __future__ import annotations

import json
import random
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[3]
EVAL_DIR = ROOT_DIR / "output" / "evaluation"
CANDIDATES = EVAL_DIR / "real_qa_candidates_v1.json"
MAINLINE_DIR = EVAL_DIR / "real_qa_mainline"

MAX_TURN_CHARS = 1500
#: 分段参数（实验变量，不是生产默认值）
IDLE_SECONDS = 30 * 60
MAX_SEGMENT_TURNS = 16
MAX_SEGMENT_CHARS = 4000


def _turn_id(line: int) -> str:
    return f"e{line}"


def load_turns(
    cid: str, mainline_dir: Path = MAINLINE_DIR
) -> tuple[list[dict[str, Any]], dict[int, int]]:
    """返回 (turns, 行号别名)；被合并掉的重复用户输入映射到保留的那一行。"""
    turns: list[dict[str, Any]] = []
    alias: dict[int, int] = {}
    last_user: tuple[int, str] | None = None
    path = mainline_dir / f"{cid}.jsonl"
    for line, raw in enumerate(path.read_text(encoding="utf-8").splitlines()):
        row = json.loads(raw)
        role = str(row.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        content = str(row.get("content") or "").strip()
        if not content:
            continue
        if role == "user" and last_user and last_user[1] == content:
            alias[line] = last_user[0]
            continue
        last_user = (line, content) if role == "user" else None
        turns.append(
            {
                "turn_id": _turn_id(line),
                "role": role,
                "content": content[:MAX_TURN_CHARS],
                "timestamp": float(row.get("ts") or 0.0),
                "branch": "main",
            }
        )
    return turns, alias


def segment_turns(case: Mapping[str, Any], _unused: int = 0) -> list[dict[str, Any]]:
    """只在用户发言前切段：空闲超过阈值，或段内轮数 / 字数达到上限。"""
    segments: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    chars = 0

    def flush() -> None:
        nonlocal current, chars
        if current:
            segments.append(
                {
                    "segment_id": f"seg-{case.get('id')}-{len(segments)}",
                    "case_id": case.get("id"),
                    "branch": "main",
                    "turn_ids": [str(turn["turn_id"]) for turn in current],
                    "turns": list(current),
                }
            )
        current, chars = [], 0

    for turn in case.get("turns") or []:
        if current and turn.get("role") == "user":
            idle = float(turn.get("timestamp") or 0) - float(current[-1].get("timestamp") or 0)
            if (
                idle > IDLE_SECONDS
                or len(current) >= MAX_SEGMENT_TURNS
                or chars + len(turn["content"]) > MAX_SEGMENT_CHARS
            ):
                flush()
        current.append(turn)
        chars += len(turn["content"])
    flush()
    return segments


def sample_haystack(
    turns: list[dict[str, Any]], evidence: list[str], *, radius: int = 15, seed: int = 20261026
) -> list[dict[str, Any]]:
    """证据前后各 ``radius`` 条 + 同等条数的随机干扰窗口；三臂共用同一份子集。"""
    index = {turn["turn_id"]: i for i, turn in enumerate(turns)}
    keep: set = set()
    for tid in evidence:
        if tid in index:
            keep.update(
                range(max(0, index[tid] - radius), min(len(turns), index[tid] + radius + 1))
            )
    target = 2 * len(keep)
    rng = random.Random(seed)
    attempts = 0
    while len(keep) < min(target, len(turns)) and attempts < 10_000:
        attempts += 1
        center = rng.randrange(len(turns))
        window = range(max(0, center - radius), min(len(turns), center + radius + 1))
        if not keep.intersection(window):
            keep.update(window)
    return [turns[i] for i in sorted(keep)]


def _query(question: Mapping[str, Any], evidence: list[str]) -> dict[str, Any]:
    abstain = question.get("type") == "abstain"
    return {
        "id": question["id"],
        "text": question["question"],
        "type": "refusal" if abstain else question["type"],
        "gold_fact_ids": [] if abstain or not evidence else [f"f-{question['id']}"],
        "answer_keywords": [],
        "answer_keywords_any": list(question.get("answer_keywords") or []),
        "forbidden_keywords": list(question.get("forbidden_keywords") or []),
        "unanswerable": abstain,
    }


def load_real_cases(
    candidates: Path = CANDIDATES, mainline_dir: Path = MAINLINE_DIR, *, full: bool = False
) -> dict[str, Any]:
    data = json.loads(Path(candidates).read_text(encoding="utf-8"))
    questions = [q for q in data["questions"] if q.get("status") != "rejected"]
    cases: list[dict[str, Any]] = []
    for cid in sorted({q["conversation_id"] for q in questions}):
        turns, alias = load_turns(cid, mainline_dir)
        known = {turn["turn_id"] for turn in turns}
        gold_facts: list[dict[str, Any]] = []
        queries: list[dict[str, Any]] = []
        for question in (q for q in questions if q["conversation_id"] == cid):
            evidence = []
            for source in question.get("sources") or []:
                tid = _turn_id(alias.get(source["mainline_line"], source["mainline_line"]))
                if tid in known and tid not in evidence:
                    evidence.append(tid)
            query = _query(question, evidence)
            if query["gold_fact_ids"]:
                gold_facts.append(
                    {
                        "fact_id": query["gold_fact_ids"][0],
                        "keywords": query["answer_keywords_any"][:1],
                        "evidence_turns": evidence,
                    }
                )
            queries.append(query)
        if not full:
            turns = sample_haystack(turns, [t for f in gold_facts for t in f["evidence_turns"]])
        cases.append(
            {
                "id": cid,
                "active_branch": "main",
                "turns": turns,
                "gold_facts": gold_facts,
                "queries": queries,
            }
        )
    return {"version": data["meta"]["version"], "cases": cases}


__all__ = ["load_real_cases", "load_turns", "segment_turns"]
