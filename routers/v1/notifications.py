# -*- coding: utf-8 -*-
"""通知（notifications）域。

客户端通知中心的统一入口。历史实现只有 ``/tutor/notifications`` 一个
「拉一次就消费」的推送端点，通知中心刷新后列表即变空，安卓端也一直是
``TODO: 后端暂无此端点``。本模块提供非破坏性的列表、已读标记与手工投递。

GET  /notifications
POST /notifications
POST /notifications/read
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Query
from pydantic import BaseModel, Field

from core.api.contract import error_response, success_response
from core.api.error_response import ErrorCode
from core.managers.notification_manager import get_notification_manager
from core.utils.logger import get_logger

logger = get_logger("NOTIFICATION_ROUTER")

router = APIRouter(prefix="/notifications", tags=["通知中心"])

_DEFAULT_USER_ID = "default_user"
_MAX_TITLE_LENGTH = 120
_MAX_CONTENT_LENGTH = 4000


class NotificationCreateRequest(BaseModel):
    """手工投递一条通知（调试、运营或端内提醒）。"""

    title: str = Field(default="", description="通知标题")
    content: str = Field(default="", description="通知正文")
    type: str = Field(default="text", description="通知类型：text/image/voice/vocabulary")
    user_id: str = Field(default=_DEFAULT_USER_ID, description="接收者 ID")
    payload: Dict[str, Any] = Field(default_factory=dict, description="附加数据")


class NotificationReadRequest(BaseModel):
    """标记通知已读；``ids`` 为空表示全部已读。"""

    user_id: str = Field(default=_DEFAULT_USER_ID, description="接收者 ID")
    ids: Optional[List[str]] = Field(default=None, description="要标记的通知 ID 列表")


@router.get("", summary="获取通知列表（不消费队列）")
async def list_notifications(user_id: str = Query(_DEFAULT_USER_ID, description="接收者 ID")):
    try:
        manager = get_notification_manager()
        items = manager.peek_notifications(user_id)
        items.sort(key=lambda item: float(item.get("timestamp") or 0), reverse=True)
        return {
            "status": "success",
            "data": {
                "items": items,
                "total": len(items),
                "unread": manager.unread_count(user_id),
            },
            "timestamp": time.time(),
        }
    except Exception as exc:  # pragma: no cover - 兜底分支
        logger.error(f"获取通知列表失败: {exc}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(exc))


@router.post("", summary="投递一条通知")
async def create_notification(payload: NotificationCreateRequest):
    title = str(payload.title or "").strip()
    content = str(payload.content or "").strip()
    if not title and not content:
        return error_response(ErrorCode.INVALID_PARAMETER, message="标题与正文不能同时为空")

    try:
        manager = get_notification_manager()
        notification = manager.add_notification(
            user_id=str(payload.user_id or _DEFAULT_USER_ID),
            type=str(payload.type or "text"),
            title=title[:_MAX_TITLE_LENGTH],
            content=content[:_MAX_CONTENT_LENGTH],
            payload=payload.payload or {},
        )
        return success_response(data={"notification": notification}, message="通知已投递")
    except Exception as exc:  # pragma: no cover - 兜底分支
        logger.error(f"投递通知失败: {exc}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(exc))


@router.post("/read", summary="标记通知已读")
async def mark_notifications_read(payload: NotificationReadRequest):
    try:
        manager = get_notification_manager()
        user_id = str(payload.user_id or _DEFAULT_USER_ID)
        marked = manager.mark_read(user_id, payload.ids)
        return success_response(
            data={"marked": marked, "unread": manager.unread_count(user_id)},
            message="已标记已读",
        )
    except Exception as exc:  # pragma: no cover - 兜底分支
        logger.error(f"标记通知已读失败: {exc}")
        return error_response(ErrorCode.INTERNAL_ERROR, message=str(exc))


__all__ = ["router"]
