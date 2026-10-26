"""C7 语料构造：按实验臂把 notes / raw turns 变成可检索文档。"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Sequence

from ..cases import case_turns, format_turns, turn_branch


def _branch_of_sources(
    sources: Iterable[str], turns_map: Mapping[str, Mapping[str, Any]]
) -> str:
    branches = {
        turn_branch(turns_map[source]) for source in sources if source in turns_map
    }
    if len(branches) == 1:
        return next(iter(branches))
    return "mixed" if branches else "unknown"


def build_corpus(
    artifacts: Mapping[str, Any],
    arm: str,
    cases: Sequence[Mapping[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    notes_by_case: Dict[str, List[Mapping[str, Any]]] = {}
    for note in (artifacts.get("arms") or {}).get(arm) or []:
        if note.get("kind") in {"skip"} or not str(note.get("text") or "").strip():
            continue
        notes_by_case.setdefault(str(note.get("case_id")), []).append(note)

    corpus: Dict[str, List[Dict[str, Any]]] = {}
    for case in cases:
        case_id = str(case.get("id"))
        turns_map = {str(turn.get("turn_id")): turn for turn in case_turns(case)}
        docs: List[Dict[str, Any]] = []
        for note in notes_by_case.get(case_id, []):
            docs.append(
                {
                    "doc_id": str(note.get("note_id")),
                    "text": str(note.get("text") or ""),
                    "source_turns": list(note.get("source_turns") or []),
                    "branch": _branch_of_sources(
                        note.get("source_turns") or [], turns_map
                    ),
                    "kind": "summary" if arm in {"A", "B"} else "fact",
                }
            )
        if arm == "C":
            for turn in case_turns(case):
                docs.append(
                    {
                        "doc_id": f"raw-{case_id}-{turn.get('turn_id')}",
                        "text": format_turns([turn]),
                        "source_turns": [str(turn.get("turn_id"))],
                        "branch": turn_branch(turn),
                        "kind": "raw",
                    }
                )
        corpus[case_id] = docs
    return corpus


__all__ = ["build_corpus"]
