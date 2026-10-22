# -*- coding: utf-8 -*-
"""背单词前台学习计时上报。

从 ``vocab.py`` 拆出的独立子路由，避免继续膨胀已超行数上限的聚合文件。

计时口径由客户端决定：只统计**前台可见**时间（切后台、离开学习页即暂停）。
``seconds`` 是本次会话的累计值，服务端按 ``session_id`` 覆盖同一条每日记录，
因此重复上报（周期性 / 切后台 / 结束时各报一次）不会叠加。

写入两处：
- ``daily_record.study.sessions``：显式 ``minutes``，供「今日学习时长」汇总；
- 当日词汇计划项 ``actual_minutes``：替换式投影，供计划卡展示实际用时。
"""

import asyncio
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body

from core.api.contract import error_response
from core.api.error_response import ErrorCode
from core.utils.logger import get_logger
from core.utils.time_utils import today_str

logger = get_logger("VOCAB_STUDY_TIME")

router = APIRouter(prefix="/vocab", tags=["背单词"])

#: 单次上报的最大秒数（12 小时），防止客户端异常值污染当天时长。
MAX_STUDY_SECONDS = 12 * 3600


def _vocab_plan_actual_minutes(plan: Any) -> Optional[float]:
    """取当日词汇计划项的实际用时，用于回给客户端即时刷新。"""
    if plan is None:
        return None
    for item in getattr(plan, "items", []) or []:
        key = str(getattr(item, "source_key", "") or "")
        title = str(getattr(item, "title", "") or "")
        # 与 plan_crud._find_vocab_item 保持同一套识别口径
        if (
            key == "vocab:due_review"
            or "复习到期英语词汇" in title
            or "复核昨日词汇复习线索" in title
        ):
            return round(float(getattr(item, "actual_minutes", 0.0) or 0.0), 2)
    return None


@router.post("/study-time", summary="上报背单词前台学习时长")
async def report_vocab_study_time(data: Dict[str, Any] = Body(...)):
    """Body: {"session_id": "abc", "seconds": 720, "mode": "review"|"new_words"}"""
    session_id = str(data.get("session_id") or "").strip()
    if not session_id:
        return error_response(ErrorCode.MISSING_PARAMETER, message="Missing session_id")

    try:
        seconds = int(float(data.get("seconds") or 0))
    except (TypeError, ValueError):
        seconds = 0
    seconds = max(0, min(seconds, MAX_STUDY_SECONDS))

    mode = str(data.get("mode") or "review")
    minutes = int(round(seconds / 60.0))
    if seconds >= 30 and minutes <= 0:
        minutes = 1

    today = today_str()
    day_total = 0
    try:
        from core.services.daily.manager import get_daily_manager
        from core.services.daily.study_minutes import (
            VOCAB_TIMER_SOURCE,
            extract_study_total_minutes,
        )

        daily = get_daily_manager()
        if minutes > 0:
            label = "新词" if mode == "new_words" else "复习"
            await asyncio.to_thread(
                daily.record_study,
                "英语词汇",
                f"背单词 {minutes}分钟（{label}）",
                session_id=f"vocab_timer:{today}:{session_id}",
                minutes=minutes,
                source=VOCAB_TIMER_SOURCE,
            )
        record = await asyncio.to_thread(daily.get_record, None)
        day_total, _ = extract_study_total_minutes(record)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"写入背单词学习时长失败: {e}")

    plan_actual: Optional[float] = None
    if minutes > 0:
        try:
            from core.services.journal.service import get_journal_service

            plan = await get_journal_service().apply_vocab_study_time(today, minutes)
            plan_actual = _vocab_plan_actual_minutes(plan)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"投影背单词时长到计划项失败: {e}")

    return {
        "status": "success",
        "data": {
            "session_id": session_id,
            "mode": mode,
            "seconds": seconds,
            "minutes": minutes,
            "day_total_minutes": day_total,
            "plan_actual_minutes": plan_actual,
        },
    }
