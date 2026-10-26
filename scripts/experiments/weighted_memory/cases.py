"""离线实验共用：加载合成评测集、按分支切段、取金标事实与证据轮次。

只读 fixtures，不依赖生产 MemoryManager / Chroma / nightly。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

ROOT_DIR = Path(__file__).resolve().parents[3]
FIXTURE_PATH = ROOT_DIR / "tests" / "fixtures" / "memory_topology" / "extraction_e2e_cases.json"

ROLE_LABELS = {"user": "用户", "assistant": "角色"}


def load_cases(path: Optional[Path] = None) -> Dict[str, Any]:
    target = Path(path) if path else FIXTURE_PATH
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise ValueError(f"{target} 不是合法的评测集")
    return data


def case_turns(case: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return [dict(turn) for turn in case.get("turns") or []]


def turn_branch(turn: Mapping[str, Any]) -> str:
    return str(turn.get("branch") or "main").strip() or "main"


def turn_text(turn: Mapping[str, Any]) -> str:
    role = ROLE_LABELS.get(str(turn.get("role") or ""), str(turn.get("role") or ""))
    return f"[{turn.get('turn_id')}] {role}: {turn.get('content')}"


def format_turns(turns: Iterable[Mapping[str, Any]]) -> str:
    return "\n".join(turn_text(turn) for turn in turns)


def segment_case(case: Mapping[str, Any], segment_turns: int) -> List[Dict[str, Any]]:
    """只在同一分支的连续 turn 上切段；分支切换处强制断开。

    实验变量固定为 ``segment_turns``；生产参数由 C4 回放分布另行决定。
    """
    segments: List[Dict[str, Any]] = []
    current: List[Dict[str, Any]] = []
    current_branch = ""

    def flush() -> None:
        nonlocal current
        if not current:
            return
        turn_ids = [str(turn.get("turn_id")) for turn in current]
        segments.append(
            {
                "segment_id": f"seg-{case.get('id')}-{len(segments)}",
                "case_id": case.get("id"),
                "branch": current_branch,
                "turn_ids": turn_ids,
                "turns": list(current),
            }
        )
        current = []

    for turn in case_turns(case):
        branch = turn_branch(turn)
        if current and (branch != current_branch or len(current) >= segment_turns):
            flush()
        current_branch = branch
        current.append(turn)
    flush()
    return segments


def gold_fact_map(case: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(fact.get("fact_id")): dict(fact)
        for fact in (case.get("gold_facts") or [])
        if isinstance(fact, dict)
    }


def query_evidence_turns(case: Mapping[str, Any], query: Mapping[str, Any]) -> List[str]:
    facts = gold_fact_map(case)
    turns: List[str] = []
    for fact_id in query.get("gold_fact_ids") or []:
        fact = facts.get(str(fact_id))
        if not fact:
            continue
        for turn_id in fact.get("evidence_turns") or []:
            key = str(turn_id)
            if key not in turns:
                turns.append(key)
    return turns


def turns_by_id(case: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(turn.get("turn_id")): dict(turn)
        for turn in case_turns(case)
        if str(turn.get("turn_id") or "").strip()
    }


__all__ = [
    "FIXTURE_PATH",
    "case_turns",
    "format_turns",
    "gold_fact_map",
    "load_cases",
    "query_evidence_turns",
    "segment_case",
    "turn_branch",
    "turn_text",
    "turns_by_id",
]
