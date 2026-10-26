#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""拿**原始聊天记录**跑一遍当前蒸馏 prompt，看看新口吻的实际产出。

与夜间蒸馏共用同一条链路：同一套分组（按时间间隔 + 批大小）、同一个
`build_batch_distillation_prompt`（system 稳定段 + user 动态段）、同一个解析器。
区别只是输入来自 `{scope}_data/chat_history/YYYY/MM/DD/**/*.jsonl`，
而不是已落盘的加权记忆，因此可以反复重跑、不依赖旧梗概。

默认只预览；加 `--apply` 才会回写。回写目标按
`event_ref.event_id → (role, conversation_id, message_id)` 两级解析，
整批解析不出唯一目标就整批拒写（详见 `memory/maintenance/redistill_apply.py`）。
预览报告里带同样的解析结果，因此"预览说会改哪条"与"实际改了哪条"一致。

角色白名单默认继承 nightly：不在名单里的角色只做预览，`--allow-role` 才写，
且必须用 `--reason` 记录原因。

运行：
    venv_cpu\\Scripts\\python.exe scripts\\maintenance\\redistill_from_chat_history.py --days 1 --max-batches 4
    venv_cpu\\Scripts\\python.exe scripts\\maintenance\\redistill_from_chat_history.py --days 3 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.utils.data.data_paths import get_role_data_dir  # noqa: E402
from core.utils.logger import get_module_logger  # noqa: E402
from core.utils.time.time_utils import get_current_time  # noqa: E402
from memory.maintenance.redistill_apply import (  # noqa: E402
    MemoryTargetIndex,
    SourceEvent,
    apply_plan,
    build_apply_plan,
)
from memory.nightly.config import (  # noqa: E402
    DEFAULT_NIGHTLY_CONFIG,
    get_memory_distillation_model,
    is_distillation_role_allowed,
)
from memory.nightly.distillation_service import MemoryDistillationService  # noqa: E402

logger = get_module_logger(__name__, "nightly_processor.log")

_VISIBLE_ROLES = {"user", "assistant"}


class _ScopeProbe:
    """只带归属信息的探针，用于解析角色视角（不加载记忆管理器）。"""

    def __init__(self, scope: str) -> None:
        self.user_id = f"shared__scope__{scope}"
        self.storage_scope = scope


def _load_history(scope: str, days: int) -> List[Dict[str, Any]]:
    """读取角色自己的原始聊天（user/assistant），按时间升序。

    带上 event_id / conversation_id / 相对路径：它们才是回写时的消歧键，
    ``message_id`` 只是 turn 级标识，同轮 user 与 assistant 共用一个值。
    """
    chat_dir = get_role_data_dir(scope) / "chat_history"
    if not chat_dir.exists():
        return []
    now = get_current_time()
    window_start = (now - timedelta(days=max(1, days))).timestamp()
    messages: List[Dict[str, Any]] = []
    for jsonl_file in sorted(chat_dir.rglob("*.jsonl")):
        try:
            with jsonl_file.open(encoding="utf-8") as file_obj:
                for line in file_obj:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        message = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    role = str(message.get("role") or "").strip().lower()
                    if role not in _VISIBLE_ROLES:
                        continue
                    content = str(message.get("content") or "").strip()
                    if not content:
                        continue
                    try:
                        timestamp = float(message.get("timestamp") or 0)
                    except (TypeError, ValueError):
                        continue
                    if timestamp < window_start:
                        continue
                    messages.append(
                        {
                            "id": str(message.get("message_id") or ""),
                            "event_id": str(message.get("event_id") or ""),
                            "conversation_id": str(message.get("conversation_id") or ""),
                            "relative_path": jsonl_file.relative_to(chat_dir).as_posix(),
                            "storage_scope": str(message.get("storage_scope") or scope),
                            "role": role,
                            "content": content,
                            "timestamp": timestamp,
                        }
                    )
        except Exception as exc:
            logger.warning("读取 %s 失败: %s", jsonl_file, exc)
    messages.sort(key=lambda item: item["timestamp"])
    return messages


def _resolve_apply_permission(scope: str, role_id: str, args: argparse.Namespace) -> bool:
    """白名单默认与 nightly 一致；显式覆盖必须带原因。"""
    if is_distillation_role_allowed(DEFAULT_NIGHTLY_CONFIG, role_id):
        return True
    if not args.allow_role:
        print(f"[白名单] scope={scope} 角色={role_id or '未识别'} 不在 nightly 白名单，只预览不写")
        return False
    if not str(args.reason or "").strip():
        raise SystemExit("[拒绝] --allow-role 必须同时提供 --reason 记录覆盖原因")
    print(f"[白名单] 显式覆盖：角色={role_id}，原因={args.reason}")
    return True


async def _run(scope: str, args: argparse.Namespace) -> int:
    from core.services.scheduler.task.task_scheduler import get_global_scheduler
    from memory.nightly.perspective import resolve_distillation_perspective

    perspective = resolve_distillation_perspective(_ScopeProbe(scope))
    if not perspective:
        print(f"[跳过] scope={scope} 认不出角色，不走第一人称蒸馏")
        return 0
    print(f"[视角] {perspective['role_name']}（对话者 {perspective['user_name']}）")

    can_write = _resolve_apply_permission(scope, perspective.get("role_id") or "", args)
    apply_enabled = bool(args.apply and can_write)

    messages = _load_history(scope, args.days)
    print(f"[原始聊天] 近 {args.days} 天 user/assistant 消息 {len(messages)} 条")
    if not messages:
        return 0
    if args.limit:
        messages = messages[-args.limit :]

    service = MemoryDistillationService(dict(DEFAULT_NIGHTLY_CONFIG), get_global_scheduler)
    groups = service.group_memories_by_time(
        messages,
        float(args.gap_minutes) * 60,
        int(args.batch_size),
    )
    groups = [group for group in groups if len(group) > 1][: args.max_batches]
    print(f"[批次] 按 {args.gap_minutes} 分钟间隔 / 每批 {args.batch_size} 条，取 {len(groups)} 批")
    if not groups:
        return 0

    manager = None
    target_index = None
    if not args.no_resolve:
        from memory.weighted_memory_manager import get_weighted_memory_manager

        manager = get_weighted_memory_manager(f"shared__scope__{scope}")
        target_index = MemoryTargetIndex.from_manager(manager)

    scheduler = get_global_scheduler()
    model = get_memory_distillation_model()
    report: List[Dict[str, Any]] = []
    for index, group in enumerate(groups, start=1):
        prompt = service.generate_batch_distillation_prompt(group, perspective)
        llm_kwargs: Dict[str, Any] = {
            "max_tokens": max(4096, len(group) * 300),
            "temperature": 0.3,
        }
        if model:
            llm_kwargs["model_hint"] = model
        text = await service._stream_llm_text(scheduler, prompt, llm_kwargs)
        parsed = service.parse_batch_distillation_response(text)
        plan = None
        if target_index is not None:
            plan = build_apply_plan(
                target_index,
                [SourceEvent.from_mapping(item) for item in group],
                parsed,
            )
            if plan.blocked:
                print(f"\n[阻断] 批次 {index} 解析不唯一，本批不写：")
                for reason in plan.reasons:
                    print(f"  - {reason}")
        print(f"\n===== 批次 {index}（{len(group)} 条）=====")
        entry_reports = _report_plan(plan) if plan is not None else {}
        for item_index, message in enumerate(group, start=1):
            summary, keywords = parsed.get(item_index, ("", []))
            print(f"  [原话] {message['role']}: {message['content'][:60]}")
            print(f"  [新梗概] {summary or '（解析失败）'}")
            if keywords:
                print(f"  [关键词] {'，'.join(keywords)}")
            target = entry_reports.get(item_index, {})
            if target:
                print(
                    f"  [目标] {target.get('memory_id') or '未解析'}"
                    f" ({target.get('status')}/{target.get('resolved_by') or '-'})"
                )
            report.append(
                {
                    "batch": index,
                    "event_id": message.get("event_id"),
                    "conversation_id": message.get("conversation_id"),
                    "message_id": message.get("id"),
                    "role": message["role"],
                    "content": message["content"],
                    "summary": summary,
                    "keywords": keywords,
                    "target": target,
                }
            )
        if apply_enabled and plan is not None and manager is not None:
            result = apply_plan(manager, plan)
            status = "已提交" if result.get("committed") else "未提交"
            print(f"  [回写] {status}，{result.get('updated', 0)} 条")
            for reason in result.get("reasons") or []:
                print(f"    - {reason}")
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n[报告] 已写入 {out_path}")
    return len(report)


def _report_plan(plan: Any) -> Dict[int, Dict[str, Any]]:
    """把计划转成按条目号索引的报告，供预览打印与 --out 复用。"""
    if plan is None:
        return {}
    return {
        item.index: {
            "memory_id": item.resolution.memory_id,
            "status": item.resolution.status,
            "resolved_by": item.resolution.resolved_by,
            "candidate_count": item.resolution.candidate_count,
            "detail": item.resolution.detail,
        }
        for item in plan.items
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="用原始聊天记录重跑蒸馏 prompt")
    parser.add_argument("--scope", default="aveline", help="记忆 scope（默认 aveline）")
    parser.add_argument("--days", type=int, default=1, help="读取最近多少天的聊天记录")
    parser.add_argument("--limit", type=int, default=0, help="最多取最近多少条消息")
    parser.add_argument("--max-batches", type=int, default=4, help="最多跑多少批")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--gap-minutes", type=float, default=30)
    parser.add_argument("--apply", action="store_true", help="整批回写梗概（解析不唯一即拒写）")
    parser.add_argument(
        "--no-resolve",
        action="store_true",
        help="只预览 prompt 输出，不加载记忆池解析回写目标",
    )
    parser.add_argument(
        "--allow-role",
        action="store_true",
        help="角色不在 nightly 白名单时仍允许回写，必须配 --reason",
    )
    parser.add_argument("--reason", default="", help="覆盖白名单的原因（写入预览输出）")
    parser.add_argument("--out", default="", help="把结果写成 JSON 报告")
    args = parser.parse_args()
    started = time.time()
    total = asyncio.run(_run(args.scope, args))
    print(f"\n[完成] {total} 条，用时 {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
