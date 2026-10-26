"""C6 三种提取粒度：A 逐消息摘要 / B segment 单 episode / C segment 原子 fact。

控制变量：同一模型、temperature=0、同一 system prompt、同一输入证据与预算。
差异只在「输入单位 + 输出形态」，对应 spec §11.1 的 A/B/C 三个实验臂。
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .cases import case_turns, format_turns, segment_case

ARM_A = "A"
ARM_B = "B"
ARM_C = "C"

SYSTEM_PROMPT = (
    "你是离线记忆提取器。只依据给定对话提取可长期复用的事实、偏好、计划与关系；"
    "不得编造对话中没有的信息；不要输出解释或 Markdown，只输出 JSON。"
)

_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _parse_json(text: str) -> Optional[Dict[str, Any]]:
    raw = _CODE_FENCE.sub("", str(text or "").strip()).strip()
    if not raw:
        return None
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except Exception:  # noqa: BLE001
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            value = json.loads(raw[start : end + 1])
            return value if isinstance(value, dict) else None
        except Exception:  # noqa: BLE001
            return None


def _clean_text(value: Any, limit: int = 800) -> str:
    text = str(value or "").strip().replace("\n", " ")
    return text[:limit]


def _note(
    *,
    arm: str,
    case_id: str,
    index: int,
    kind: str,
    text: str,
    source_turns: Iterable[str],
    provenance_ok: bool,
    parse_failed: bool,
) -> Dict[str, Any]:
    sources = [str(item) for item in source_turns if str(item).strip()]
    return {
        "note_id": f"{arm}-{case_id}-{index}",
        "case_id": case_id,
        "arm": arm,
        "kind": kind,
        "text": text,
        "source_turns": sources,
        "provenance_ok": bool(provenance_ok and sources),
        "parse_failed": bool(parse_failed),
    }


def _summary_call(
    client: Any,
    *,
    system: str,
    user: str,
    max_tokens: int,
) -> tuple[str, bool, float]:
    result = client.chat(system, user, max_tokens=max_tokens)
    elapsed = result.latency_seconds if not result.cached else 0.0
    data = _parse_json(result.text)
    if data is None:
        return _clean_text(result.text), True, elapsed
    return _clean_text(data.get("summary")), False, elapsed


def run_arm_a(
    cases: Iterable[Mapping[str, Any]],
    client: Any,
    *,
    max_tokens: int = 220,
) -> List[Dict[str, Any]]:
    notes: List[Dict[str, Any]] = []
    for case in cases:
        case_id = str(case.get("id"))
        for index, turn in enumerate(case_turns(case)):
            user_prompt = (
                "任务：把这一轮对话压缩成一条长期记忆摘要，只保留以后可能用到的事实、偏好或计划。\n"
                '只输出 JSON：{"summary": "..."}\n'
                f"内容：\n{format_turns([turn])}"
            )
            text, failed, _latency = _summary_call(
                client, system=SYSTEM_PROMPT, user=user_prompt, max_tokens=max_tokens
            )
            notes.append(
                _note(
                    arm=ARM_A,
                    case_id=case_id,
                    index=index,
                    kind="summary" if text else "skip",
                    text=text,
                    source_turns=[str(turn.get("turn_id"))],
                    provenance_ok=True,
                    parse_failed=failed,
                )
            )
    return notes


def run_arm_b(
    cases: Iterable[Mapping[str, Any]],
    client: Any,
    *,
    segment_turns: int,
    max_tokens: int = 320,
) -> List[Dict[str, Any]]:
    notes: List[Dict[str, Any]] = []
    for case in cases:
        case_id = str(case.get("id"))
        for index, segment in enumerate(segment_case(case, segment_turns)):
            user_prompt = (
                "任务：把这一段连续对话压缩成一条 episode 摘要，保留可长期复用的事实、偏好与计划。\n"
                '只输出 JSON：{"summary": "..."}\n'
                f"内容：\n{format_turns(segment['turns'])}"
            )
            text, failed, _latency = _summary_call(
                client, system=SYSTEM_PROMPT, user=user_prompt, max_tokens=max_tokens
            )
            notes.append(
                _note(
                    arm=ARM_B,
                    case_id=case_id,
                    index=index,
                    kind="summary" if text else "skip",
                    text=text,
                    source_turns=segment["turn_ids"],
                    provenance_ok=True,
                    parse_failed=failed,
                )
            )
    return notes


def run_arm_c(
    cases: Iterable[Mapping[str, Any]],
    client: Any,
    *,
    segment_turns: int,
    max_tokens: int = 480,
) -> List[Dict[str, Any]]:
    notes: List[Dict[str, Any]] = []
    counter = 0
    for case in cases:
        case_id = str(case.get("id"))
        for segment in segment_case(case, segment_turns):
            allowed = set(segment["turn_ids"])
            user_prompt = (
                "任务：从这段连续对话提取 0..n 条原子事实/偏好/计划，每条只表达一件事。\n"
                "每条必须给出证据 turn_id（只能来自输入的方括号 ID）；没有可复用信息就输出空数组。\n"
                '只输出 JSON：{"facts": [{"text": "...", "evidence_turns": ["t1"]}]}\n'
                f"内容：\n{format_turns(segment['turns'])}"
            )
            result = client.chat(
                SYSTEM_PROMPT, user_prompt, max_tokens=max_tokens
            )
            data = _parse_json(result.text)
            parse_failed = data is None
            facts = data.get("facts") if isinstance(data, dict) else None
            if not isinstance(facts, list):
                facts = []
                parse_failed = True
            for fact in facts:
                if not isinstance(fact, dict):
                    continue
                text = _clean_text(fact.get("text"))
                if not text:
                    continue
                sources = [
                    str(item)
                    for item in (fact.get("evidence_turns") or [])
                    if str(item).strip()
                ]
                valid = [item for item in sources if item in allowed]
                counter += 1
                notes.append(
                    _note(
                        arm=ARM_C,
                        case_id=case_id,
                        index=counter,
                        kind="fact",
                        text=text,
                        source_turns=valid,
                        provenance_ok=bool(valid) and len(valid) == len(sources),
                        parse_failed=parse_failed,
                    )
                )
            if not facts:
                # 解析失败也要留一条 skip，否则失败段被静默丢掉、解析失败率恒为 0
                counter += 1
                notes.append(
                    _note(
                        arm=ARM_C,
                        case_id=case_id,
                        index=counter,
                        kind="skip",
                        text="",
                        source_turns=[],
                        provenance_ok=False,
                        parse_failed=parse_failed,
                    )
                )
    return notes


def run_extraction(
    cases: List[Mapping[str, Any]],
    client: Any,
    *,
    segment_turns: int = 4,
) -> Dict[str, Any]:
    arms: Dict[str, List[Dict[str, Any]]] = {}
    usage: Dict[str, Dict[str, Any]] = {}
    for arm, runner in (
        (ARM_A, lambda: run_arm_a(cases, client)),
        (ARM_B, lambda: run_arm_b(cases, client, segment_turns=segment_turns)),
        (ARM_C, lambda: run_arm_c(cases, client, segment_turns=segment_turns)),
    ):
        before = client.usage()
        started = time.time()
        arms[arm] = runner()
        after = client.usage()
        usage[arm] = {
            "calls": after["calls"] - before["calls"],
            "cached_calls": after["cached_calls"] - before["cached_calls"],
            "prompt_tokens": after["prompt_tokens"] - before["prompt_tokens"],
            "completion_tokens": after["completion_tokens"] - before["completion_tokens"],
            "cached_prompt_tokens": after.get("cached_prompt_tokens", 0)
            - before.get("cached_prompt_tokens", 0),
            "cached_completion_tokens": after.get("cached_completion_tokens", 0)
            - before.get("cached_completion_tokens", 0),
            "wall_seconds": round(time.time() - started, 2),
        }
    return {
        "meta": {
            "model": client.model,
            "temperature": client.temperature,
            "segment_turns": segment_turns,
            "case_count": len(cases),
            "turn_count": sum(len(case_turns(case)) for case in cases),
            "segment_count": sum(
                len(segment_case(case, segment_turns)) for case in cases
            ),
            "system_prompt": SYSTEM_PROMPT,
        },
        "arms": arms,
        "usage": usage,
        "client_usage": client.usage(),
    }


__all__ = [
    "ARM_A",
    "ARM_B",
    "ARM_C",
    "run_extraction",
]
