#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiniMax客户端

继承OpenAIClient，提供MiniMax API的默认配置
支持 reasoning_split=True 将推理内容分离到 reasoning_details 字段
"""

from typing import Dict, Any, Optional

from core.llm.openai_compat.client import OpenAIClient
from core.utils.logger import get_logger

logger = get_logger("minimax_client")


MINIMAX_BASE_URL = "https://api.minimax.chat/v1/chat/completions"
MINIMAX_DEFAULT_MODEL = "MiniMax-M3.1-Flash"


class MiniMaxClient(OpenAIClient):
    """MiniMax专用客户端"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        super().__init__(
            api_key=api_key,
            base_url=base_url or MINIMAX_BASE_URL,
            model=model or MINIMAX_DEFAULT_MODEL,
        )

    def _strip_names(self, messages):
        """MiniMax 不支持 group chat，强制移除所有的 name 字段"""
        for msg in messages:
            if "name" in msg:
                del msg["name"]

    def _build_payload(self, messages: list, stream: bool, **kwargs) -> Dict[str, Any]:
        # 单次调用传 thinking_enabled=False 关思考（离线提取用；MiniMax-M3 认顶层
        # thinking:disabled，10-27 实测）。不传时保持默认思考，主对话行为不变。
        thinking = kwargs.pop("thinking_enabled", None)
        payload = super()._build_payload(messages, stream, **kwargs)
        if thinking is False:
            payload["thinking"] = {"type": "disabled"}
        payload["reasoning_split"] = True
        payload.pop("max_tokens", None)
        # MiniMax 被动 prompt 缓存只回 usage.prompt_tokens_details.cached_tokens，
        # 流式默认不带 usage；必须显式开启才能统计缓存命中率（对齐 deepseek_client）。
        if stream:
            payload.setdefault("stream_options", {"include_usage": True})
        return payload

    async def chat(self, messages, **kwargs):
        self._strip_names(messages)
        return await super().chat(messages, **kwargs)

    async def stream_chat(self, messages, **kwargs):
        self._strip_names(messages)
        async for chunk in super().stream_chat(messages, **kwargs):
            yield chunk

    def get_status(self) -> Dict[str, Any]:
        return self._build_base_status(provider="MiniMax")
