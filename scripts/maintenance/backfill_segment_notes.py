"""回填历史段梗概到派生笔记库（v3 F3 / G 的前置）。默认只统计，``--apply`` 才调用模型。

    venv_cpu/bin/python scripts/maintenance/backfill_segment_notes.py            # 全部人设 scope 预览
    venv_cpu/bin/python scripts/maintenance/backfill_segment_notes.py --apply
    venv_cpu/bin/python scripts/maintenance/backfill_segment_notes.py --scope ye --limit 4 --apply

- 只做人设里的角色，跳过认不出人设的历史 scope；路由见 ``segment_backfill/policy.py``
  （aveline 与 ling 2026 年 1–2 月用 MiniMax，其余 DeepSeek）；
- DeepSeek 按角色分 key（``cloud:deepseek:<alias>:<model>``），MiniMax 走订阅 key；
- 只处理已封口段，当前及已接受的旧版本（v3 / v4 / v5）已有梗概的段跳过；
- 模型明确说没有可记内容的段记进 ``<memories>/nightly/segment_backfill_jobs.json``，
  重跑不再调用模型；失败只计数、下次重跑继续补；
- v5 的 system 是角色静态人设前缀，同一角色逐字节固定，``cached`` 计数可核对；
- 写完梗概顺手算好向量旁挂缓存；终端只打印计数，不输出任何聊天正文。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.agents.chat_agent_components.persona_system.prompt.offline_persona_prefix import (
    build_offline_role_prefix,
)
from core.utils.data.data_paths import get_role_memories_dir
from memory.nightly.job_ledger import DistillJobLedger
from memory.nightly.perspective import perspective_for_scope
from memory.nightly.segment_jobs import relay
from memory.nightly.segment_jobs.episode import EpisodeExtractor
from memory.nightly.segment_jobs.inputs import collect_segment_inputs
from memory.notes import NoteStore, embeddings
from scripts.maintenance.segment_backfill import policy
from scripts.maintenance.segment_backfill.scheduler import DirectScheduler

#: 每个供应商的并发：MiniMax Token Plan 有限流，DeepSeek 基本不限
CONCURRENCY = {policy.MINIMAX: 8, policy.DEEPSEEK: 24}
#: 模型明确说「没有可记内容」的段记进这个账本，重跑时不再调用模型
LEDGER_FILENAME = "segment_backfill_jobs.json"


def _open_ledger(scope: str) -> DistillJobLedger:
    path = Path(get_role_memories_dir(scope)) / "nightly" / LEDGER_FILENAME
    ledger = DistillJobLedger(path, extractor_version=EpisodeExtractor.version)
    ledger.forget_other_versions()
    return ledger


def _pending(scope: str, args: argparse.Namespace, versions: set) -> dict:
    conversations = [args.conversation] if args.conversation else None
    items = collect_segment_inputs(scope, conversations=conversations)
    if args.since_days:
        cutoff = time.time() - args.since_days * 86400
        items = [item for item in items if item.segment.ended_at >= cutoff]
    ledger = _open_ledger(scope)
    ledger.forget_missing(item.segment_id for item in items)
    store, done_by_cid, pending, skipped_before = NoteStore(scope), {}, [], 0
    for item in items:
        if item.conversation_id not in done_by_cid:
            done_by_cid[item.conversation_id] = {
                note.get("source_segment_id")
                for note in store.list_notes(item.conversation_id)
                if note.get("extractor_version") in versions
            }
        if item.segment_id in done_by_cid[item.conversation_id]:
            continue
        if not ledger.is_eligible(item.segment_id):
            skipped_before += 1
            continue
        pending.append(item)
    pending.sort(key=lambda item: -item.segment.ended_at)  # 新的先补：检索最常问近事
    done = len(items) - len(pending) - skipped_before
    if args.limit:
        pending = pending[: args.limit]
    by_provider: dict[str, int] = {}
    by_key: dict[str, int] = {}
    for item in pending:
        name = policy.provider_for(scope, item.segment.started_at)
        by_provider[name] = by_provider.get(name, 0) + 1
        alias = policy.key_alias_for(scope, name)
        label = f"{name}:{alias or 'default'}"
        by_key[label] = by_key.get(label, 0) + 1
    return {
        "items": pending,
        "by_id": {item.segment_id: item for item in items},  # 接力找上一段用（含已完成的段）
        "total": len(items),
        "done": done,
        "skipped_before": skipped_before,
        "by_provider": by_provider,
        "by_key": by_key,
    }


async def _run(scope: str, pending: list, by_id: dict | None = None) -> dict:
    schedulers = {
        name: DirectScheduler(
            name,
            quota_fallback=policy.fallback_route_for(scope)
            if name == policy.MINIMAX
            else "",
        )
        for name in CONCURRENCY
    }
    gates = {name: asyncio.Semaphore(limit) for name, limit in CONCURRENCY.items()}
    extractors = {
        name: EpisodeExtractor(
            scheduler_provider=lambda s=scheduler: s,
            model_hint=policy.model_route_for(scope, name),
            perspective_for_scope=perspective_for_scope,
            persona_prefix_for_scope=build_offline_role_prefix,
            fallback_for_scope=policy.fallback_route_for,
        )
        for name, scheduler in schedulers.items()
    }
    store = NoteStore(scope)
    ledger = _open_ledger(scope)
    counts = {"done": 0, "skipped": 0, "failed": 0}

    def record(outcome: str) -> None:
        counts[outcome] += 1
        processed = sum(counts.values())
        if processed % 100 == 0:
            ledger.save()
            print(f"  [{scope}] 进度 {processed}/{len(pending)} {counts}", flush=True)

    async def one(item) -> bool:
        """处理一段；返回是否已处理完（失败时同一条接力链后面的段先不跑）。"""
        name = policy.provider_for(scope, item.segment.started_at)
        item = relay.with_carry(item, store, by_id or {})
        async with gates[name]:
            try:
                result = await extractors[name].extract(item)
            except Exception:  # noqa: BLE001 - 只计数，下次重跑会再试
                record("failed")
                return False
        carry = tuple(result.carry_event_ids or ())
        if result.notes or carry:
            await asyncio.to_thread(
                store.replace_segment,
                item.conversation_id,
                item.segment_id,
                EpisodeExtractor.version,
                result.notes,
                segment_source_event_ids=item.allowed_sources,
                occurred_from=item.segment.started_at,
                occurred_to=item.segment.ended_at,
                carry_event_ids=carry,
            )
        if not result.notes:
            ledger.mark_skipped(item.segment_id, result.skip_reason or "unspecified")
            record("skipped")
            return True
        ledger.mark_done(item.segment_id)
        record("done")
        return True

    async def chain(items) -> None:
        for item in items:  # 同一次对话的几段按顺序跑，接力才接得上
            if not await one(item):
                break

    # 预热前缀缓存：每个供应商先单独跑完一段建好缓存，再并发（同时发出的首批请求都吃不到缓存）
    try:
        chains = relay.ordered_chains(pending)
        chains.sort(key=lambda c: -c[-1].segment.ended_at)  # 新的先补：检索最常问近事
        first_by_provider: dict[str, list] = {}
        for links in chains:
            first_by_provider.setdefault(policy.provider_for(scope, links[0].segment.started_at), links)
        for links in first_by_provider.values():
            await chain(links)
        warmed = {id(links) for links in first_by_provider.values()}
        await asyncio.gather(*(chain(links) for links in chains if id(links) not in warmed))
    finally:
        ledger.save()
    return {**counts, **{name: s.usage for name, s in schedulers.items() if s.usage["calls"]}}


def _warm_vectors(scope: str) -> int:
    store, embedder, total = NoteStore(scope), embeddings.default_embedder(), 0
    for cid in store.list_conversations():
        notes = store.list_notes(cid)
        total += len(embeddings.load_vectors(scope, cid, notes, embedder, max_new=10**9))
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scope", action="append", default=None, help="缺省 = 全部人设 scope")
    parser.add_argument("--conversation", default="")
    parser.add_argument("--since-days", type=float, default=0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--segmenter", choices=("v1", "v2"), default="",
                        help="只对本次运行生效的分段器（v2 写 notes_v2/）；缺省读 settings")
    parser.add_argument("--provider", choices=(policy.MINIMAX, policy.DEEPSEEK), default="",
                        help="本次全部走这个供应商（MiniMax 额度用完自动换该角色的 DeepSeek）")
    args = parser.parse_args()
    if args.segmenter:  # 进程内覆盖，不改 settings：主程序读哪个库仍由 notes_segmenter 决定
        from memory.notes import paths as notes_paths

        notes_paths.active_segmenter = lambda: args.segmenter
    if args.provider:
        policy.provider_for = lambda _scope, _started_at: args.provider
    version = set(EpisodeExtractor.accepted_versions)  # v3 已回填的不重跑
    allowed = policy.persona_scopes()
    for scope in args.scope or allowed:
        if scope not in allowed:
            print(f"[{scope}] 不在人设里（legacy scope），跳过")
            continue
        plan = _pending(scope, args, version)
        chars = sum(item.char_count for item in plan["items"])
        print(
            f"[{scope}] 封口段 {plan['total']}，已有梗概 {plan['done']}，"
            f"此前无内容 {plan['skipped_before']}，"
            f"待回填 {len(plan['items'])} {plan['by_provider']}，"
            f"key {plan['by_key']}，正文约 {chars} 字"
        )
        if not args.apply or not plan["items"]:
            continue
        started = time.time()
        report = asyncio.run(_run(scope, plan["items"], plan["by_id"]))
        print(f"[{scope}] 回填完成 {report}，用时 {time.time() - started:.0f}s")
        print(f"[{scope}] 向量缓存已就绪 {_warm_vectors(scope)} 条")
    if not args.apply:
        print("（预览模式，未调用模型；加 --apply 执行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
