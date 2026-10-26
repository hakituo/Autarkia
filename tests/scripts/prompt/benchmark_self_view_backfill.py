"""主人卡历史回填 + 双路提取质量 benchmark。

用真实历史聊天记录跑一遍 self-view 蒸馏（与夜间任务完全同款链路：
_SYSTEM_PROMPT + PeopleProfileExtractor.call_llm + _parse_facts_response），
同时输出「实时正则 vs 夜间 LLM」双路提取对比指标：

1. 回填：LLM 提取且 confidence>=0.7 的事实写入真实 user_data/self_views/{scope}.json
2. benchmark：
   - LLM 层：提取条数、key 分布、置信度分布、失败批次数
   - 正则层：命中 (key, value) 去重清单
   - 对比：key 覆盖交集 / LLM 独有（正则盲区）/ 正则独有；同 key value 冲突
   - 目检清单：LLM 高置信度事实逐条列出（人工核 precision）

用法：
    venv_cpu/bin/python -u tests/scripts/prompt/benchmark_self_view_backfill.py \
        [--days 36500] [--concurrency 4] [--batch-chars 2000] [--dry-run] [--model ...]

注意：MiniMax 内容审核拦长上下文（见 model_routing.yaml 注释），批次须短（默认 2000 字）。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT))

_BATCH_CHARS = 2000
_MAX_LINE_CHARS = 1500
_NIGHTLY_CONFIDENCE = 0.7
_DEFAULT_MODEL = "cloud:minimax:plan:MiniMax-M3"
# 批级断点缓存：每行 {"key": sha1(scope+batch), "facts": [...]}，重跑跳过已完成批次
_CACHE_PATH = _PROJECT_ROOT / "logs" / "self_view_backfill_cache.jsonl"


def _load_user_messages(scope: str, days: int) -> List[str]:
    """读取某角色最近 N 天的用户消息（夜间任务同源读取链路）。"""
    from core.character.people.conversation_source import PeopleConversationSource

    messages = PeopleConversationSource.load_scope_messages(scope, 0.0, window_days=days)
    lines: List[str] = []
    for message in messages:
        if str(message.get("role") or "").strip().lower() != "user":
            continue
        content = str(message.get("content") or "").strip()
        if content:
            lines.append(content[:_MAX_LINE_CHARS])
    return lines


def _split_batches(lines: List[str], limit: int) -> List[str]:
    """按字符数上限切批，单批拼成一段对话记录。"""
    batches: List[str] = []
    cur: List[str] = []
    size = 0
    for line in lines:
        if cur and size + len(line) > limit:
            batches.append("\n".join(cur))
            cur, size = [], 0
        cur.append(line)
        size += len(line)
    if cur:
        batches.append("\n".join(cur))
    return batches


def _regex_hits(lines: List[str]) -> List[Tuple[str, str]]:
    """实时正则提取（self_view_capture 同款纯函数），去重后返回 (key, value) 清单。"""
    from core.character.people.self_view_capture import extract_facts_from_text

    hits: List[Tuple[str, str]] = []
    seen: set = set()
    for line in lines:
        for key, value in extract_facts_from_text(line):
            if (key, value) not in seen:
                seen.add((key, value))
                hits.append((key, value))
    return hits


def _load_batch_cache() -> Dict[str, List[Dict[str, Any]]]:
    """加载批级断点缓存（key → 已解析 facts）。"""
    cache: Dict[str, List[Dict[str, Any]]] = {}
    if _CACHE_PATH.exists():
        for line in _CACHE_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                if isinstance(item.get("key"), str):
                    cache[item["key"]] = item.get("facts") or []
            except Exception:
                continue
    return cache


def _append_batch_cache(key: str, facts: List[Dict[str, Any]]) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _CACHE_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"key": key, "facts": facts}, ensure_ascii=False) + "\n")
    except Exception:
        pass


async def _llm_extract(
    scope: str,
    batches: List[str],
    model_hint: str,
    sem: asyncio.Semaphore,
    cache: Dict[str, List[Dict[str, Any]]],
) -> Tuple[List[Dict[str, Any]], int]:
    """并发逐批调 LLM 蒸馏（夜间任务同款 prompt 与解析），返回 (facts, 失败批数)。

    - model_hint 通过 patch memory.nightly.config.get_memory_distillation_model 生效
      （extractor 在调用时动态 import 该函数，patch 模块属性即可）；
    - sem 为跨角色共享的全局并发闸；命中断点缓存的批次直接跳过。
    """
    import memory.nightly.config as nightly_config
    from core.character.people.extractor import PeopleProfileExtractor
    from core.character.people.self_view_distill import _SYSTEM_PROMPT, _parse_facts_response

    nightly_config.get_memory_distillation_model = lambda: model_hint
    extractor = PeopleProfileExtractor()
    facts: List[Dict[str, Any]] = []
    failed = 0
    done = 0

    async def one(index: int, batch: str) -> None:
        nonlocal failed, done
        key = hashlib.sha1(f"{scope}::{batch}".encode("utf-8")).hexdigest()
        if key in cache:
            facts.extend(cache[key])
            done += 1
            print(f"    [{scope}] 批 {done}/{len(batches)} 命中缓存跳过", flush=True)
            return
        user_prompt = (
            f"以下是与角色 {scope} 聊天的用户最近说过的话：\n\n{batch}\n\n"
            "请提取其中用户本人明确陈述的长期事实，输出 JSON。"
        )
        parsed: List[Dict[str, Any]] = []
        async with sem:
            try:
                response = await extractor.call_llm(
                    [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ]
                )
                parsed = _parse_facts_response(response)
                if not parsed:
                    failed += 1
                facts.extend(parsed)
                cache[key] = parsed
                _append_batch_cache(key, parsed)
            except Exception as exc:  # noqa: BLE001 - 单批失败继续下一批
                failed += 1
                parsed = []
                print(f"    [{scope}] 批 {index} 异常: {exc}", flush=True)
        done += 1
        print(f"    [{scope}] 批 {done}/{len(batches)} 完成，提取 {len(parsed)} 条", flush=True)

    await asyncio.gather(*(one(i, b) for i, b in enumerate(batches, 1)))
    return facts, failed


def _compare(regex_hits: List[Tuple[str, str]], llm_facts: List[Tuple[str, str, float]]) -> Dict[str, Any]:
    """双路对比：key 覆盖与 value 冲突。"""
    regex_keys = {k for k, _ in regex_hits}
    llm_keys = {k for k, _, _ in llm_facts}
    regex_values = {k: sorted({v for kk, v in regex_hits if kk == k}) for k in regex_keys}
    llm_values = {k: sorted({v for kk, v, _ in llm_facts if kk == k}) for k in llm_keys}
    conflicts = [
        (k, regex_values[k], llm_values[k])
        for k in sorted(regex_keys & llm_keys)
        if regex_values[k] != llm_values[k]
    ]
    return {
        "regex_keys": sorted(regex_keys),
        "llm_keys": sorted(llm_keys),
        "llm_only_keys": sorted(llm_keys - regex_keys),
        "regex_only_keys": sorted(regex_keys - llm_keys),
        "conflicts": conflicts,
    }


def _normalize_llm_facts(raw: List[Dict[str, Any]]) -> List[Tuple[str, str, float]]:
    """原始解析结果 → (key, value, confidence)，过滤空条目。"""
    normalized: List[Tuple[str, str, float]] = []
    for item in raw:
        key = str(item.get("key") or "").strip()
        value = str(item.get("value") or "").strip()
        if not key or not value:
            continue
        try:
            confidence = float(item.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        normalized.append((key, value, min(confidence, 1.0)))
    return normalized


def _print_scope_report(scope: str, stats: Dict[str, Any]) -> None:
    print(f"\n{'=' * 62}")
    print(f"角色 [{scope}]  消息 {stats['msg_count']} 条 / {stats['msg_chars']} 字 → {stats['batch_count']} 批"
          f"（{stats['elapsed']:.1f}s，LLM 失败批 {stats['llm_failed']}）")
    print(f"  LLM 层: 原始 {stats['llm_raw']} 条 | 有效 {stats['llm_valid']} 条 | ≥0.7 入库 "
          f"{stats['llm_ge07']} 条")
    if stats["llm_valid"]:
        dist = Counter(f"{k}({'H' if c >= 0.7 else 'L'})" for k, _, c in stats["llm_facts"])
        print(f"  LLM key 分布: {dict(dist.most_common())}")
    print(f"  正则层: 命中 {len(stats['regex_hits'])} 组 (key, value)")
    if stats["regex_hits"]:
        for key, value in stats["regex_hits"]:
            print(f"      [正则] {key}: {value}")
    cmp = stats["compare"]
    print(f"  key 覆盖: 双方共 {len(cmp['regex_keys']) + len(cmp['llm_keys']) - len(set(cmp['regex_keys']) & set(cmp['llm_keys']))} 个 key | "
          f"重合 {len(set(cmp['regex_keys']) & set(cmp['llm_keys']))} | "
          f"LLM 独有(正则盲区) {cmp['llm_only_keys']} | 正则独有 {cmp['regex_only_keys']}")
    if cmp["conflicts"]:
        print(f"  value 冲突 {len(cmp['conflicts'])} 组:")
        for key, rv, lv in cmp["conflicts"]:
            print(f"      {key}: 正则={rv} vs LLM={lv}")
    if stats["llm_ge07_facts"]:
        print("  高置信度事实（人工目检 precision）:")
        for key, value, conf in stats["llm_ge07_facts"]:
            print(f"      [LLM {conf:.1f}] {key}: {value}")


async def _run_scope(
    scope: str,
    days: int,
    write: bool,
    model_hint: str,
    sem: asyncio.Semaphore,
    cache: Dict[str, List[Dict[str, Any]]],
    batch_chars: int,
) -> Dict[str, Any]:
    started = time.monotonic()
    lines = _load_user_messages(scope, days)
    stats: Dict[str, Any] = {
        "msg_count": len(lines),
        "msg_chars": sum(len(x) for x in lines),
        "batch_count": 0,
        "llm_raw": 0,
        "llm_valid": 0,
        "llm_ge07": 0,
        "llm_failed": 0,
        "llm_facts": [],
        "llm_ge07_facts": [],
        "regex_hits": [],
        "compare": {},
        "written": False,
    }
    if not lines:
        stats["elapsed"] = time.monotonic() - started
        return stats

    batches = _split_batches(lines, batch_chars)
    stats["batch_count"] = len(batches)
    stats["regex_hits"] = _regex_hits(lines)
    print(f"  [{scope}] 消息 {len(lines)} 条 / {stats['msg_chars']} 字 → {len(batches)} 批，"
          f"模型 {model_hint}", flush=True)
    raw_facts, failed = await _llm_extract(scope, batches, model_hint, sem, cache)
    facts = _normalize_llm_facts(raw_facts)
    stats["llm_raw"] = len(raw_facts)
    stats["llm_valid"] = len(facts)
    stats["llm_failed"] = failed
    stats["llm_facts"] = facts
    ge07 = [(k, v, c) for k, v, c in facts if c >= _NIGHTLY_CONFIDENCE]
    stats["llm_ge07"] = len(ge07)
    stats["llm_ge07_facts"] = ge07
    stats["compare"] = _compare(stats["regex_hits"], facts)

    if write and ge07:
        from core.character.people.models import KnownFact
        from core.character.people.self_view_store import upsert_facts

        written = upsert_facts(
            scope,
            [KnownFact(key=k, value=v, confidence=c, source="nightly_extracted") for k, v, c in ge07],
            source="nightly_extracted",
        )
        stats["written"] = written
    stats["elapsed"] = time.monotonic() - started
    return stats


async def main() -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="主人卡历史回填 + benchmark")
    parser.add_argument("--days", type=int, default=36500, help="回看天数（默认全量）")
    parser.add_argument("--concurrency", type=int, default=4, help="LLM 并发数（默认 4）")
    parser.add_argument("--batch-chars", type=int, default=_BATCH_CHARS, help="单批字符上限")
    parser.add_argument("--model", default=_DEFAULT_MODEL, help=f"模型路由（默认 {_DEFAULT_MODEL}）")
    parser.add_argument("--dry-run", action="store_true", help="只评估不写盘")
    args = parser.parse_args()

    from core.services.journal.diary_personas import get_diary_persona_ids

    scopes = list(get_diary_persona_ids())
    cache = _load_batch_cache()
    if cache:
        print(f"断点缓存: 已有 {len(cache)} 批结果将跳过")
    print(f"注册角色: {scopes} | 回看 {args.days} 天 | 模型: {args.model} | "
          f"并发: {args.concurrency} | 写盘模式: {'DRY-RUN' if args.dry_run else '写入'}")

    sem = asyncio.Semaphore(max(1, args.concurrency))
    stats_list = await asyncio.gather(*(
        _run_scope(
            scope, args.days, write=not args.dry_run,
            model_hint=args.model, sem=sem, cache=cache, batch_chars=args.batch_chars,
        )
        for scope in scopes
    ))

    total_ge07 = 0
    for scope, stats in zip(scopes, stats_list):
        _print_scope_report(scope, stats)
        total_ge07 += stats["llm_ge07"]
        if stats["written"]:
            print(f"  ✓ 已写入 user_data/self_views/{scope}.json")
        elif stats["llm_ge07"] and not args.dry_run:
            print("  (同值节流或落盘失败，未产生新写入)")

    print(f"\n=== 回填完成：共 {total_ge07} 条高置信度事实"
          f"{'（dry-run 未写盘）' if args.dry_run else ''} ===")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
