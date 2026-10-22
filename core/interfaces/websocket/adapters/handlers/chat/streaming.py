#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
流式回复任务

把聊天/问候的流式输出封装成独立任务，含超时与异常兜底。
"""

import asyncio
import time

from core.utils.logger import get_logger

logger = get_logger(__name__)

_CHAT_TASK_TIMEOUT = 180


def _error_payload(
    message: str,
    *,
    msg_id: str,
    conversation_id: str,
    request_id: str,
    error_code: str,
) -> dict:
    """构造统一错误帧。

    用 ``type: "error"`` 而不是 ``type: "message" / subtype: "response"``：
    后者各端会当成普通 AI 回复插进聊天记录，超时/失败时用户看到的是
    "一条文字"而不是"出错了"。``content`` 供 iOS 的 BaseMessage 读取。
    """
    return {
        "type": "error",
        "subtype": "error",
        "message": message,
        "error": message,
        "content": message,
        "error_code": error_code,
        "message_id": msg_id,
        "timestamp": time.time(),
        "conversation_id": conversation_id,
        "request_id": request_id,
    }


async def run_chat_stream_task(
    adapter,
    *,
    websocket,
    streaming_handler,
    content: str,
    msg_id: str,
    conversation_id: str,
    request_id: str,
    model: str,
    profile_filename: str,
    service_dynamic_context: str,
    api_key_env: str,
    user_name,
):
    """执行一次流式聊天回复，注册到 adapter 的任务表并等待完成。"""
    content_preview = (
        str(content)[:50] if not isinstance(content, list) else "[多模态消息]"
    )

    async def _handle_chat_task():
        try:
            from core.core_engine.service_singletons import get_aveline_service

            svc = get_aveline_service()
            if svc is None:
                raise RuntimeError("AvelineService could not be initialized")

            try:
                await asyncio.wait_for(
                    streaming_handler.handle_stream(
                        websocket=websocket,
                        svc=svc,
                        content=content,
                        msg_id=msg_id,
                        conversation_id=conversation_id,
                        request_id=request_id,
                        model=model,
                        user_name=user_name,
                        profile_filename=profile_filename,
                        service_dynamic_context=service_dynamic_context,
                        api_key_env=api_key_env,
                        platform=str(getattr(websocket, "platform", "") or "").strip().lower()
                        or None,
                    ),
                    timeout=_CHAT_TASK_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.error(
                    f"Chat task timed out ({_CHAT_TASK_TIMEOUT}s) for "
                    f"cid={conversation_id}, msg={content_preview}"
                )
                await websocket.send_json(
                    _error_payload(
                        "响应超时，请重试",
                        msg_id=msg_id,
                        conversation_id=conversation_id,
                        request_id=request_id,
                        error_code="CHAT_TIMEOUT",
                    )
                )
        except asyncio.CancelledError:
            logger.info(f"Chat task cancelled for cid={conversation_id}")
        except Exception as e:
            logger.error(f"Chat task error: {e}")
            try:
                await websocket.send_json(
                    _error_payload(
                        f"处理消息时出错: {e}",
                        msg_id=msg_id,
                        conversation_id=conversation_id,
                        request_id=request_id,
                        error_code="SYSTEM_INTERNAL_ERROR",
                    )
                )
            except Exception:
                pass

    task = asyncio.create_task(_handle_chat_task())
    await adapter._register_chat_task(websocket, msg_id, task)


async def run_greeting_stream_task(
    adapter,
    *,
    websocket,
    msg_id: str,
    conversation_id: str,
    request_id: str,
    user_name,
):
    """执行一次流式问候，注册到 adapter 的任务表并等待完成。"""
    async def _handle_greeting_task():
        try:
            from core.core_engine.service_singletons import get_aveline_service

            svc = get_aveline_service()
            if svc is None:
                raise RuntimeError("AvelineService could not be initialized")

            # 使用 generate_proactive_message 生成流式问候
            async for chunk in svc.generate_proactive_message(
                conversation_id=conversation_id,
                save_to_history=True,
                user_name=user_name,
            ):
                if isinstance(chunk, dict):
                    chunk["message_id"] = msg_id
                    chunk["conversation_id"] = conversation_id
                    chunk["request_id"] = request_id
                    await websocket.send_json(chunk)

        except Exception as e:
            logger.error(f"Greeting task error: {e}")
            await websocket.send_json(
                _error_payload(
                    f"生成问候时出错: {e}",
                    msg_id=msg_id,
                    conversation_id=conversation_id,
                    request_id=request_id,
                    error_code="GREETING_FAILED",
                )
            )

    task = asyncio.create_task(_handle_greeting_task())
    await adapter._register_chat_task(websocket, msg_id, task)
