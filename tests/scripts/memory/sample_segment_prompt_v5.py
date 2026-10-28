"""v5 提取提示词的小样本实测：每个角色跑几段，终端看口吻、输入长度、分 key 缓存与成本。

**只读、不入库**：不写任何笔记或文件，摘要只打印到终端（不落盘、不提交）。
默认每角色取最新的 3 个未处理段（优先正文 >= 80 字），同一角色顺序调用以观察前缀缓存
从首调未命中到后续命中的变化：

    venv_cpu/bin/python tests/scripts/memory/sample_segment_prompt_v5.py
    venv_cpu/bin/python tests/scripts/memory/sample_segment_prompt_v5.py --scope aveline --sample 2
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.agents.chat_agent_components.persona_system.prompt.offline_persona_prefix import (
    build_offline_role_prefix,
)
from memory.nightly.perspective import perspective_for_scope
from memory.nightly.segment_jobs.episode import EpisodeExtractor
from memory.nightly.segment_jobs.inputs import collect_segment_inputs
from memory.notes import NoteStore
from scripts.maintenance.segment_backfill import policy
from scripts.maintenance.segment_backfill.scheduler import DirectScheduler

PRICING_PATH = ROOT_DIR / "data/model_pricing.json"


def _pending(scope: str, versions: set[str]) -> list:
    store, done_by, pending = NoteStore(scope), {}, []
    for item in collect_segment_inputs(scope):
        if item.conversation_id not in done_by:
            done_by[item.conversation_id] = {
                note.get("source_segment_id")
                for note in store.list_notes(item.conversation_id)
                if note.get("extractor_version") in versions
            }
        if item.segment_id in done_by[item.conversation_id]:
            continue
        pending.append(item)
    return pending


def _pick(pending: list, count: int, min_chars: int) -> list:
    pool = [item for item in pending if item.char_count >= min_chars] or pending
    pool.sort(key=lambda item: -item.segment.ended_at)
    return pool[:count]


def _deepseek_price() -> dict:
    data = json.loads(PRICING_PATH.read_text(encoding="utf-8"))
    for record in data["catalog"]["prices"]:
        if record.get("key") == "deepseek-v4-flash" and record.get("source") == "deepseek_official":
            return record
    return {}


def _cost_usd(record: dict, prompt: int, cached: int, completion: int) -> float:
    if not record:
        return 0.0
    uncached = max(0, prompt - cached)
    return (
        uncached * float(record.get("input") or 0)
        + cached * float(record.get("cache_read") or 0)
        + completion * float(record.get("output") or 0)
    )


async def _run_scope(
    scope: str, items: list, *, show_summaries: bool, summary_chars: int, stats: dict
) -> None:
    prefix = build_offline_role_prefix(scope)
    perspective = perspective_for_scope(scope)
    print(
        f"\n[{scope}] 角色={perspective.get('role_name') or '?'} "
        f"人设前缀={len(prefix)} 字 样本={len(items)}"
    )
    grouped = defaultdict(list)
    for item in items:
        grouped[policy.provider_for(scope, item.segment.started_at)].append(item)

    for provider, group in grouped.items():
        route = policy.model_route_for(scope, provider)
        scheduler = DirectScheduler(provider)
        extractor = EpisodeExtractor(
            scheduler_provider=lambda s=scheduler: s,
            model_hint=route,
            perspective_for_scope=perspective_for_scope,
            persona_prefix_for_scope=lambda _scope: prefix,
            fallback_for_scope=policy.fallback_route_for,
        )
        for index, item in enumerate(group, start=1):
            before = {k: scheduler.usage[k] for k in ("calls", "prompt", "cached", "completion")}
            started = time.perf_counter()
            error = ""
            result = None
            try:
                result = await extractor.extract(item)
            except Exception as exc:  # noqa: BLE001 - 抽样只记录类型，不输出异常正文
                error = type(exc).__name__
            elapsed = time.perf_counter() - started
            delta = {
                key: scheduler.usage[key] - before[key]
                for key in ("calls", "prompt", "cached", "completion")
            }
            last = scheduler.usage.get("last") or {}
            label = f"{last.get('provider', provider)}:{last.get('alias', 'default')}"
            bucket = stats[label]
            bucket["calls"] += 1
            bucket["prompt"] += delta["prompt"]
            bucket["cached"] += delta["cached"]
            bucket["completion"] += delta["completion"]
            bucket["seconds"] += elapsed

            hit = delta["cached"] / delta["prompt"] if delta["prompt"] else 0.0
            print(
                f"  {index}. {item.segment_id[:10]} 事件={len(item.events)} "
                f"正文={item.char_count}字 输入={delta['prompt']}tok "
                f"缓存={delta['cached']}tok({hit:.0%}) 输出={delta['completion']}tok "
                f"{elapsed:.1f}s"
            )
            if error:
                print(f"     失败：{error}")
            elif result and result.notes:
                if show_summaries:
                    text = result.notes[0].text
                    if summary_chars and len(text) > summary_chars:
                        text = text[:summary_chars] + "…"
                    print(f"     梗概：{text}")
            else:
                print(f"     跳过：{result.skip_reason if result else ''}")


def _report(stats: dict) -> None:
    price = _deepseek_price()
    print("\n=== 分 key 汇总（MiniMax Token Plan 为订阅制，边际成本按 0 计） ===")
    total = 0.0
    for label in sorted(stats):
        bucket = stats[label]
        calls = max(1, bucket["calls"])
        hit = bucket["cached"] / bucket["prompt"] if bucket["prompt"] else 0.0
        provider = label.split(":", 1)[0]
        cost = (
            0.0
            if provider == "minimax"
            else _cost_usd(price, bucket["prompt"], bucket["cached"], bucket["completion"])
        )
        total += cost
        print(
            f"  {label}: 调用={bucket['calls']} 输入={bucket['prompt']}tok "
            f"缓存={bucket['cached']}tok({hit:.0%}) 输出={bucket['completion']}tok "
            f"耗时={bucket['seconds']:.1f}s 成本=${cost:.4f} "
            f"(每千段≈${cost / calls * 1000:.2f})"
        )
    print(f"  合计估算成本 ${total:.4f}（按 deepseek-v4-flash 官方价，含缓存读价）")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scope", action="append", default=None)
    parser.add_argument("--sample", type=int, default=3)
    parser.add_argument("--min-chars", type=int, default=80)
    parser.add_argument("--no-summaries", action="store_true")
    parser.add_argument(
        "--summary-chars", type=int, default=0, help="终端只打印前 N 字梗概（0=全文）"
    )
    args = parser.parse_args()

    versions = set(EpisodeExtractor.accepted_versions)
    stats = defaultdict(
        lambda: {"calls": 0, "prompt": 0, "cached": 0, "completion": 0, "seconds": 0.0}
    )
    allowed = policy.persona_scopes()
    scopes = args.scope or allowed
    chosen = {}
    for scope in scopes:
        if scope not in allowed:
            print(f"[{scope}] 不在人设里，跳过")
            continue
        pending = _pending(scope, versions)
        items = _pick(pending, args.sample, args.min_chars)
        print(f"[{scope}] 未处理段 {len(pending)}，抽 {len(items)}")
        if items:
            chosen[scope] = items
    for scope, items in chosen.items():
        asyncio.run(
            _run_scope(
                scope,
                items,
                show_summaries=not args.no_summaries,
                summary_chars=max(0, args.summary_chars),
                stats=stats,
            )
        )
    _report(stats)
    print("\n（仅终端预览：未写笔记、未写任何文件）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
