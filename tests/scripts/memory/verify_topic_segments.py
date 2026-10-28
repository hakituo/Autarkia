"""验证分段器 v2（spec §7.1）：交换为单位、空闲硬切、长会话按话题深度二分。

    venv_cpu/bin/python tests/scripts/memory/verify_topic_segments.py           # 临时数据
    venv_cpu/bin/python tests/scripts/memory/verify_topic_segments.py --live --scope ye

``--live`` 只读本机真实数据、只打印计数（段数、边界原因、字数分位、问答切开数、重放一致性），
不输出任何正文；会加载本地 bge 编码长会话（aveline 约 4 分钟）。
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from itertools import pairwise
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory.nightly.segment_jobs.topic_scorer import EmbeddingScorer
from memory.topology.events import normalize_event
from memory.topology.topic_split import TopicParams, build_topic_segments


def _check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'OK' if ok else 'FAIL'}] {name} {detail}")
    return ok


def _pct(values: list[int], ratio: float) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * ratio))] if ordered else 0


def _qa_splits(segments, events) -> int:
    """段以助手消息开头、且同会话上一段以用户消息结尾：问与答被切开。"""
    role = {event.event_id: event.speaker_role for event in events}
    count = 0
    for before, after in pairwise(segments):
        if before.boundary_reason == "topic" and (
            role[after.source_event_ids[0]] == "assistant"
            and role[before.source_event_ids[-1]] == "user"
        ):
            count += 1
    return count


def run_temp() -> bool:
    def event(i, ts, role, text):
        return normalize_event(
            {
                "event_id": f"e{i:03d}",
                "conversation_id": "c",
                "role": role,
                "content": text,
                "timestamp": ts,
                "turn_id": f"m{i}",
            }
        )

    spec = [("user", "猫" * 100), ("assistant", "猫" * 150), ("assistant", "猫" * 50)] * 8
    spec += [("user", "车" * 100), ("assistant", "车" * 200)] * 8
    spec += [("user", "晚安")]
    events = [event(i, 1000 + i * 20, r, t) for i, (r, t) in enumerate(spec)]
    events.append(event(999, 1000 + len(spec) * 20 + 7200, "user", "早"))

    def by_head(units, i):
        return 1.0 if units[i - 1][0].content[0] != units[i][0].content[0] else 0.0

    result = build_topic_segments(events, tree_id="c", scorer=by_head)
    again = build_topic_segments(list(reversed(events)), tree_id="c", scorer=by_head)
    ok = _check("话题切点落在换话题处", result.segments[0].char_count == 2400)
    ok &= _check(
        "空闲硬切", [s.boundary_reason for s in result.segments][-2:] == ["idle", "path_end"]
    )
    ok &= _check("问答不切开", _qa_splits(result.segments, events) == 0)
    ok &= _check(
        "乱序重放段号一致",
        [s.segment_id for s in result.segments] == [s.segment_id for s in again.segments],
    )
    return ok


def run_live(scopes: list[str]) -> bool:
    from core.services.chat_history_store import ChatHistoryStore
    from core.utils.data import data_paths
    from memory.nightly.segment_jobs import inputs, mainline

    ok = True
    params = TopicParams()
    for scope in scopes:
        store = ChatHistoryStore(Path(data_paths.get_role_chat_history_dir(scope)))
        scorer = EmbeddingScorer()
        segments, reasons, splits, mismatched = [], Counter(), 0, 0
        for cid in inputs.list_scope_conversations(scope):
            raw = store.list_conversation_events(cid, limit=0)
            conv = inputs._payload_conversation_id(raw) or cid
            line = mainline.prepare_mainline(raw, conversation_id=conv)
            if not line.normalized:
                continue
            first = build_topic_segments(
                line.normalized, tree_id=conv, params=params, scorer=scorer
            )
            cuts = {digest: cut for digest, cut, _tail in first.sessions}
            replay = build_topic_segments(
                line.normalized,
                tree_id=conv,
                params=params,
                lookup=lambda d, _s, table=cuts: table.get(d),
            )
            mismatched += [s.segment_id for s in first.segments] != [
                s.segment_id for s in replay.segments
            ]
            segments.extend(first.segments)
            reasons.update(s.boundary_reason for s in first.segments)
            splits += _qa_splits(first.segments, line.normalized)
        chars = [s.char_count for s in segments]
        print(
            f"[{scope}] 段 {len(segments)} 边界 {dict(reasons)} 字数 p50/p90/p99/max="
            f"{_pct(chars, 0.5)}/{_pct(chars, 0.9)}/{_pct(chars, 0.99)}/{max(chars, default=0)}"
            f" 编码交换 {scorer.encoded}"
        )
        ok &= _check(f"{scope} 问答不切开", splits == 0, f"({splits})")
        ok &= _check(f"{scope} 读切点重放段号一致", mismatched == 0, f"(不一致会话 {mismatched})")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--scope", action="append", default=None)
    args = parser.parse_args()
    ok = run_live(args.scope or ["ye"]) if args.live else run_temp()
    print("全部通过" if ok else "存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
