"""CloseAgendaTool — 结束 Active Care 开场议程。

轻问候开场后，「想跟他聊的那件事」以议程形式注入主聊天；模型判断这件事聊到了、
他说去做了 / 做完了、他不想聊或现在不适合再提时调用本工具清掉，之后不再注入。
本工具只在有未结束议程的轮次挂上（见 ``context_persona.prepare_active_tools``）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from core.tools.base import BaseTool
from core.utils.logger import get_logger

logger = get_logger("CloseAgendaTool")

CloseReason = Literal["done", "doing", "declined", "not_now"]

MSG_CLOSED = "已结束这件事，后面不会再提醒你带这个话题。照常回复他就好，不要提到这次调用。"
MSG_NONE = "现在没有要带的话题，不需要调用。照常回复他。"
MSG_NO_USER = "Error: 缺少会话信息，无法结束议程。"


class CloseAgendaInput(BaseModel):
    reason: CloseReason = Field(
        description=(
            "done：这件事已经聊到了 / 他做完了；doing：他说去做了；"
            "declined：他不想聊或在忙；not_now：你判断现在不适合再提"
        )
    )


class CloseAgendaTool(BaseTool):
    name = "close_agenda"
    description = (
        "结束你心里想跟他聊的那件事（上下文里【心里想跟他聊的事】那一条）。"
        "这件事已经聊到了、他说去做了或做完了、他明确不想聊、或你判断现在不适合再提时调用；"
        "调用后照常回复他，不要提到这次调用。没有那一条时不要调用。"
    )
    short_description = "结束想跟他聊的那件事（聊到了 / 他去做了 / 不想聊）"
    args_schema = CloseAgendaInput
    category = "active_care"
    enabled_by_default = True

    async def _run(self, reason: str = "done") -> str:
        user_id = self._get_ctx("user_id")
        if not user_id:
            return MSG_NO_USER
        from core.services.active_care.agenda import close_agenda, scope_for_conversation

        try:
            closed = await close_agenda(scope_for_conversation(str(user_id)), reason)
        except Exception as exc:  # noqa: BLE001 - 工具不向模型抛异常
            logger.warning(f"结束议程失败: {type(exc).__name__}: {exc}")
            return MSG_NONE
        return MSG_CLOSED if closed is not None else MSG_NONE


async def close_agenda_tool_names(conversation_id: object) -> list[str]:
    """本轮要不要挂 close_agenda：只有主人私聊、且该角色有未结束议程时才挂。"""
    try:
        from core.services.active_care.agenda import (
            get_active_agenda,
            is_agenda_conversation,
            scope_for_conversation,
        )

        cid = str(conversation_id or "")
        if not is_agenda_conversation(cid):
            return []
        agenda = await get_active_agenda(scope_for_conversation(cid))
    except Exception as exc:  # noqa: BLE001 - 读不到议程就当没有
        logger.warning(f"检查开场议程失败: {type(exc).__name__}: {exc}")
        return []
    return [CloseAgendaTool.name] if agenda is not None else []


__all__ = ["CloseAgendaTool", "close_agenda_tool_names"]
