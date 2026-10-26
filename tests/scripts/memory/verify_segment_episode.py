"""验证生产按段提取器（v3 F3：每段一条梗概，C8 结论的 B 形态）。

默认：临时目录造一段聊天，假调度器跑「输入管线 → 提取器 → 编排 → 笔记库」端到端两晚，
不调用模型、不碰真实数据：

    venv_cpu/bin/python tests/scripts/memory/verify_segment_episode.py

``--live``：对本机真实主线**只读**取最近 N 个已封口段，直连 DeepSeek 跑生产提取器（MiniMax
Token Plan 用尽时也能跑）。梗概只写到 ``output/evaluation/segment_episode_live_sample.jsonl``
（不入库），终端只打印计数与长度分布，不输出正文：

    venv_cpu/bin/python tests/scripts/memory/verify_segment_episode.py --live --sample 10
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from memory.nightly.segment_jobs import run as seg_run
from memory.nightly.segment_jobs.episode import EpisodeExtractor
from memory.nightly.segment_jobs.inputs import (
    SegmentParams,
    build_conversation_inputs,
    collect_segment_inputs,
)
from memory.notes import NoteStore, paths

LIVE_OUT = ROOT_DIR / "output" / "evaluation" / "segment_episode_live_sample.jsonl"
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"


class _ScriptedScheduler:
    def __init__(self, text: str) -> None:
        self.text, self.calls = text, 0

    async def submit_llm_task(self, prompt, **kwargs):
        self.calls += 1
        yield self.text


class _DeepSeekScheduler:
    """把调度器接口直连 DeepSeek（非流式一次返回），统计 token 与耗时。"""

    def __init__(self, model: str) -> None:
        from dotenv import load_dotenv

        load_dotenv(ROOT_DIR / ".env")
        self.key = str(os.getenv("DEEPSEEK_API_KEY") or "").strip()
        self.model = model
        self.usage = {"prompt": 0, "completion": 0, "seconds": 0.0}

    async def submit_llm_task(self, prompt, **kwargs):
        import httpx

        started = time.time()
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(
                DEEPSEEK_URL,
                headers={"Authorization": f"Bearer {self.key}"},
                json={
                    "model": self.model,
                    "messages": prompt,
                    "max_tokens": int(kwargs.get("max_tokens") or 4096),
                    "temperature": float(kwargs.get("temperature") or 0.2),
                },
            )
        self.usage["seconds"] += time.time() - started
        if response.status_code != 200:
            yield {"error": f"HTTP {response.status_code}"}
            return
        data = response.json()
        usage = data.get("usage") or {}
        self.usage["prompt"] += int(usage.get("prompt_tokens") or 0)
        self.usage["completion"] += int(usage.get("completion_tokens") or 0)
        yield str(((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")


class _Manager:
    def __init__(self, history_dir: Path) -> None:
        import threading

        self.user_id = "shared__scope__aveline"
        self.storage_scope = "aveline"
        self._memory_layout = {"history_dir": str(history_dir)}
        self.lock = threading.RLock()


def _extractor(scheduler) -> EpisodeExtractor:
    perspective = {
        "role_id": "aveline",
        "role_name": "Aveline",
        "user_name": "用户",
        "role_profile": "",
    }
    return EpisodeExtractor(
        scheduler_provider=lambda: scheduler,
        perspective_for_scope=lambda _s: perspective,
        persona_prefix_for_scope=lambda _s: "你是Aveline，安静、嘴硬心软。和你说话的人是用户。",
    )


def run_offline() -> int:
    cid, night = "web_role_aveline", 10_000_000.0
    events = []
    for index in range(3):
        ts = 1000.0 + index * 60
        for role, text in (("user", f"我把早上的茶换成乌龙了{index}"), ("assistant", "记住了")):
            events.append(
                {
                    "event_id": f"{role}-{index}",
                    "conversation_id": cid,
                    "role": role,
                    "content": text,
                    "timestamp": ts,
                    "event_type": "chat_message",
                    "message_id": f"m{index}",
                }
            )
    segments = build_conversation_inputs(
        "aveline", cid, events, params=SegmentParams(), now=night, tree_reader=lambda _c: events
    )
    scheduler = _ScriptedScheduler(json.dumps({"summary": "用户把早上的茶换成了乌龙。"}))
    config = {
        "segment_extraction_enabled": True,
        "distillation_role_whitelist": ["aveline"],
        "segment_max_per_night": 0,
        "segment_max_chars_per_night": 0,
        "segment_max_seconds_per_night": 0,
    }
    checks = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        paths.notes_dir = lambda scope: root / "notes" / scope  # type: ignore[assignment]
        seg_run.resolve_distillation_perspective = lambda _m: {"role_id": "aveline"}
        manager, store = _Manager(root / "memories"), NoteStore("aveline")

        def night_run():
            return asyncio.run(
                seg_run.run_segment_jobs(
                    manager.user_id,
                    manager,
                    config,
                    extractor=_extractor(scheduler),
                    note_store=store,
                    segments=segments,
                    now=night,
                )
            )

        first, second = night_run(), night_run()
        notes = store.list_notes(cid)
        checks.append(("第一晚写入 1 条梗概", first.get("done") == 1 and len(notes) == 1))
        checks.append(("梗概来源 = 整段 6 条事件", len(notes[0]["source_event_ids"]) == 6))
        checks.append(("第二晚不重跑、不调模型", second.get("done") == 0 and scheduler.calls == 1))
    for label, ok in checks:
        print(f"[{'OK' if ok else 'FAIL'}] {label}")
    return 0 if all(ok for _l, ok in checks) else 1


async def _extract_all(extractor, items):
    results = []
    for item in items:
        try:
            results.append((item, await extractor.extract(item), ""))
        except Exception as exc:  # noqa: BLE001 - 只计数
            results.append((item, None, type(exc).__name__))
    return results


def run_live(scope: str, conversation: str, sample: int, model: str) -> int:
    from memory.nightly.perspective import perspective_for_scope

    items = collect_segment_inputs(scope, conversations=[conversation])
    picked = items[-sample:]
    scheduler = _DeepSeekScheduler(model)
    extractor = EpisodeExtractor(
        scheduler_provider=lambda: scheduler, perspective_for_scope=perspective_for_scope
    )
    results = asyncio.run(_extract_all(extractor, picked))
    LIVE_OUT.parent.mkdir(parents=True, exist_ok=True)
    lengths, counts = [], {"done": 0, "skipped": 0, "failed": 0}
    with LIVE_OUT.open("w", encoding="utf-8") as handle:
        for item, result, error in results:
            row = {"segment_id": item.segment_id, "events": len(item.events), "error": error}
            if result and result.notes:
                counts["done"] += 1
                lengths.append(len(result.notes[0].text))
                row["summary"] = result.notes[0].text
                row["source_event_ids"] = list(result.notes[0].source_event_ids)
            elif result:
                counts["skipped"] += 1
                row["skip"] = result.skip_reason
            else:
                counts["failed"] += 1
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"封口段 {len(items)}，抽样 {len(picked)}：{counts}")
    if lengths:
        print(f"梗概字数 p50={statistics.median(lengths)} min={min(lengths)} max={max(lengths)}")
    usage = scheduler.usage
    print(
        f"用量 prompt={usage['prompt']} completion={usage['completion']} 耗时={usage['seconds']:.0f}s"
    )
    print(f"梗概已写到 {LIVE_OUT.relative_to(ROOT_DIR)}（不入库）")
    return 0 if counts["failed"] == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--scope", default="aveline")
    parser.add_argument("--conversation", default="web_role_aveline")
    parser.add_argument("--sample", type=int, default=10)
    parser.add_argument("--model", default="deepseek-v4-flash")
    args = parser.parse_args()
    if args.live:
        return run_live(args.scope, args.conversation, args.sample, args.model)
    return run_offline()


if __name__ == "__main__":
    raise SystemExit(main())
