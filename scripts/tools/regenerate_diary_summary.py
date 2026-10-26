"""重新生成指定日期的日记摘要 (diary_summary.json)

用法:
    python scripts/tools/regenerate_diary_summary.py              # 默认重新生成昨天
    python scripts/tools/regenerate_diary_summary.py 2026-06-17   # 指定日期

角色来自注册表（get_diary_persona_ids），不再写死 aveline / ling。
"""
import asyncio
import os
import sys
import json

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT_DIR, ".env"))
except Exception:  # noqa: BLE001 - 缺 dotenv 时退回进程环境变量
    pass

from datetime import datetime, timedelta  # noqa: E402
from core.utils.time_utils import get_diary_target_date  # noqa: E402


async def main(date_str: str) -> int:
    from core.services.journal.service import get_journal_service
    from core.services.journal.storage import JournalStorage
    from core.services.journal.diary_personas import get_diary_persona_ids

    service = get_journal_service()
    storage: JournalStorage = service.storage
    persona_ids = get_diary_persona_ids() or ("aveline",)

    # 清除摘要缓存，确保真正重新生成
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    scopes = set(persona_ids) | {"user", "any"}
    for scope in scopes:
        cache_key = f"{dt.strftime('%Y-%m-%d')}:{scope}"
        storage._summary_cache.pop(cache_key, None)  # noqa: SLF001

    print(f"=== 重新生成日记摘要: {date_str} 角色={list(persona_ids)} ===")

    # 先看看当天有多少日记条目
    entries = await storage.get_entries(dt)
    print(f"当天日记条目数: {len(entries)}")
    for entry in entries:
        print(f"  [{entry.time_str}] ({entry.type}) {entry.content[:60]}...")

    # 清理旧的 daily_summary 类型日记条目：
    # 历史 bug 曾把Ling的每日总结写成 source=aveline 落进 aveline 目录，
    # 或把Ling的条目跨 persona 去重掉。若不清除，force 重生成后 _append_daily_summary_diary_entry
    # 的按 persona 去重会命中旧条目而跳过写入，导致内容仍停留在旧版本。
    from core.utils.data_paths import get_aveline_data_dir, get_ling_data_dir, get_user_data_dir

    cleaned = 0
    for scope_dir in (get_aveline_data_dir(), get_ling_data_dir(), get_user_data_dir()):
        diary_dir = (
            scope_dir / "daily" / dt.strftime("%Y") / dt.strftime("%m") / dt.strftime("%d") / "diary"
        )
        if not diary_dir.exists():
            continue
        for entry_file in diary_dir.glob("entry_*.json"):
            try:
                payload = json.loads(entry_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            if str(payload.get("type") or "") == "daily_summary":
                entry_file.unlink(missing_ok=True)
                cleaned += 1
    if cleaned:
        print(f"已清理 {cleaned} 条旧的 daily_summary 日记条目")
        for scope in scopes:
            storage._summary_cache.pop(f"{dt.strftime('%Y-%m-%d')}:{scope}", None)  # noqa: SLF001

    # 逐角色强制重新生成
    summaries = {}
    for persona in persona_ids:
        print(f"\n=== {persona} 日记 ===")
        summary = await service.generate_daily_summary(date_str, force=True, persona=persona)
        summaries[persona] = summary
        print(f"日期: {summary.date}")
        print(f"摘要: {str(summary.summary or '')[:200]}...")
        print(f"明日基调: {summary.tomorrow_tone}")
        stats = summary.stats or {}
        reason = stats.get("reason") or stats.get("error") or ""
        if reason:
            print(f"失败原因: {reason}")

    # 去重保险：任意两角色摘要逐字相同时，对后者换温度重试一次
    #（8/14 曾出现两个角色摘要逐字相同，疑似 LLM 重复输出）
    seen: dict[str, str] = {}
    for persona, summary in summaries.items():
        text = str(summary.summary or "").strip()
        if not text:
            continue
        if text in seen:
            print(f"警告: {persona} 与 {seen[text]} 摘要逐字相同，换温度重试...")
            summaries[persona] = await service.generate_daily_summary(
                date_str, force=True, persona=persona, temperature=0.8
            )
        else:
            seen[text] = persona

    # 验证文件是否写入
    for persona in persona_ids:
        filepath = storage.get_daily_dir(dt, scope=persona) / "diary_summary.json"
        if filepath.exists():
            print(f"\n[{persona}] 文件已写入: {filepath}")
            data = json.loads(filepath.read_text(encoding="utf-8"))
            gen_time = datetime.fromtimestamp(data.get("generated_at", 0))
            print(f"  generated_at 对应时间: {gen_time.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            print(f"\n[{persona}] 警告: 未找到 {filepath}")

    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = sys.argv[1]
    else:
        # 默认昨天
        target = (get_diary_target_date() - timedelta(days=1)).strftime("%Y-%m-%d")
    raise SystemExit(asyncio.run(main(target)))
