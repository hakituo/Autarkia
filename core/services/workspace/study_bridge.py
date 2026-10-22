import asyncio
from typing import Any, Dict


async def collect_study_overview(workspace_service: Any) -> Dict[str, Any]:
    from core.services.daily.manager import get_daily_manager
    from core.services.daily.study_minutes import extract_study_total_minutes
    from core.services.study.service import get_study_service

    service = get_study_service()
    session_stats = await asyncio.to_thread(service.get_session_stats)
    daily_summary = await asyncio.to_thread(service.get_daily_study_summary_data)
    tools = await asyncio.to_thread(service.list_tools)
    study_root = await workspace_service.get_study_root_path()
    recent_files = await workspace_service._get_recent_study_files(limit=10)
    streak_days = await workspace_service._get_study_streak_days()

    # 「今日学习时长」的唯一口径：每日记录 study.sessions。
    # 客户端背单词计时器会把真实前台分钟写进同一份记录（显式 minutes 字段），
    # 因此这里直接汇总即可，不再依赖已废弃的 portrait 快照路径。
    today_record = await asyncio.to_thread(get_daily_manager().get_record, None)
    today_minutes, today_sessions = extract_study_total_minutes(today_record)

    return {
        "study_root": study_root,
        "session_stats": session_stats,
        "daily_summary": daily_summary,
        "today": {
            "date": str((today_record or {}).get("date") or ""),
            "total_minutes": today_minutes,
            "sessions": today_sessions[-20:],
        },
        "tool_categories": list((tools or {}).keys()),
        "study_data_tools": (tools or {}).get("study_data", []),
        "recent_files": recent_files,
        "study_streak_days": streak_days,
    }
