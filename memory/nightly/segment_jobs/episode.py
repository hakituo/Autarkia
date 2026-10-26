"""生产按段提取器：每段 0..1 条 episode 梗概（v3 F3，按 C8 结论的 B 形态）。

- 来源取整段可提炼事件：梗概概括的是整段，不要求模型逐条标证据（少一类失败）；
- system 用与主对话同源的离线角色前缀（v5），提取指令接在其后；同一角色前缀逐字节稳定；
- 模型走 nightly 蒸馏模型，422 内容审核拒绝由 ``core.llm.sensitivity_fallback`` 换 DeepSeek，
  按角色分 key 的链路降级到该角色自己的 DeepSeek 路由；
- 推理模型的思考 token 计入 ``max_tokens``（C8 第一次实跑就栽在这），预算按段长放大；
- 空响应 / 解析失败抛异常，由编排层记 failed 可重试；模型明确说没信息才记 skipped。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from core.llm.sensitivity_fallback import stream_text_with_sensitivity_fallback

from .contracts import SKIP_NO_REUSABLE_INFO, ExtractionResult, NoteDraft, SegmentInput
from .prompts import build_messages

#: 换提示词 / 模型 / 解析规则时改这里，编排层会按新版本重算
#: 2：角色的知识性解释只留一句主题，篇幅留给用户自己的事实（试跑发现 p50 402 字、多在复述科普）
#: 3：固定长前缀（规则 + 合成示例）放 system、角色名与对话放末尾，命中供应商前缀缓存
#: 4：改用用户原有的人设回想写法（公平对比与客观写法 21/44 持平，保留角色主观感受）
#: 5：system 换成与主对话同源的离线角色静态人设前缀，提取指令接在后面；DeepSeek 按角色分 key
EPISODE_EXTRACTOR_VERSION = "segment-episode-5"
#: 仍算「已完成」的旧版本：v3 / v4 已回填的段，用户决定不为改写法重花钱
ACCEPTED_EPISODE_VERSIONS = (
    EPISODE_EXTRACTOR_VERSION,
    "segment-episode-4",
    "segment-episode-3",
)
MIN_MAX_TOKENS = 4096
TOKENS_PER_INPUT_CHAR = 1.0
MAX_MAX_TOKENS = 12288
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class EpisodeParseError(ValueError):
    """模型输出既不是梗概也不是明确的 skip。"""


def parse_episode(text: str) -> tuple[str, str]:
    """返回 (梗概, skip 原因)；两者都没有就抛错。"""
    raw = _FENCE.sub("", str(text or "").strip()).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise EpisodeParseError("no_json")
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise EpisodeParseError("bad_json") from exc
    if not isinstance(data, dict):
        raise EpisodeParseError("not_object")
    summary = str(data.get("summary") or "").strip()
    skip = str(data.get("skip") or "").strip()
    if summary:
        return summary, ""
    if skip:
        return "", skip
    raise EpisodeParseError("empty_summary_without_skip")


def _budget(item: SegmentInput) -> int:
    estimate = int(item.char_count * TOKENS_PER_INPUT_CHAR) + MIN_MAX_TOKENS
    return max(MIN_MAX_TOKENS, min(MAX_MAX_TOKENS, estimate))


class EpisodeExtractor:
    version = EPISODE_EXTRACTOR_VERSION
    accepted_versions = ACCEPTED_EPISODE_VERSIONS

    def __init__(
        self,
        *,
        scheduler_provider: Callable[[], Any],
        model_hint: str = "",
        perspective_for_scope: Callable[[str], dict[str, str]],
        persona_prefix_for_scope: Callable[[str], str] | None = None,
        fallback_for_scope: Callable[[str], str] | None = None,
    ) -> None:
        self._scheduler_provider = scheduler_provider
        self._model_hint = model_hint
        self._perspective_for_scope = perspective_for_scope
        self._persona_prefix_for_scope = persona_prefix_for_scope
        self._fallback_for_scope = fallback_for_scope

    def _persona_prefix(self, scope: str) -> str:
        if self._persona_prefix_for_scope is not None:
            return str(self._persona_prefix_for_scope(scope) or "")
        from core.agents.chat_agent_components.persona_system.prompt.offline_persona_prefix import (
            build_offline_role_prefix,
        )

        return build_offline_role_prefix(scope)

    async def extract(self, item: SegmentInput) -> ExtractionResult:
        events = [event for event in item.events if str(event.get("content") or "").strip()]
        if not events:
            return ExtractionResult(
                notes=(), skip_reason=SKIP_NO_REUSABLE_INFO, extractor_version=self.version
            )
        prompt = build_messages(
            events,
            self._perspective_for_scope(item.scope),
            persona_prefix=self._persona_prefix(item.scope),
        )
        llm_kwargs: dict[str, Any] = {"max_tokens": _budget(item), "temperature": 0.2}
        if self._model_hint:
            llm_kwargs["model_hint"] = self._model_hint
        fallback = self._fallback_for_scope(item.scope) if self._fallback_for_scope else ""
        text = await stream_text_with_sensitivity_fallback(
            self._scheduler_provider(), prompt, llm_kwargs, fallback_model_hint=fallback
        )
        if not str(text or "").strip():
            raise EpisodeParseError("empty_response")
        summary, skip = parse_episode(text)
        if not summary:
            return ExtractionResult(notes=(), skip_reason=skip, extractor_version=self.version)
        sources = tuple(
            str(event.get("event_id")) for event in events if str(event.get("event_id") or "")
        )
        note = NoteDraft(kind="episode", text=summary, source_event_ids=sources)
        return ExtractionResult(notes=(note,), extractor_version=self.version)


def default_episode_extractor(config: dict[str, Any]) -> EpisodeExtractor:
    """生产工厂：调度器、蒸馏模型与视角解析都在运行时取。"""
    from core.agents.chat_agent_components.persona_system.prompt.offline_persona_prefix import (
        build_offline_role_prefix,
    )
    from core.services.scheduler.task.task_scheduler import get_global_scheduler
    from memory.nightly.config import get_memory_distillation_model
    from memory.nightly.model_routes import fallback_route_for_scope
    from memory.nightly.perspective import perspective_for_scope

    return EpisodeExtractor(
        scheduler_provider=get_global_scheduler,
        model_hint=str(
            config.get("segment_extraction_model") or get_memory_distillation_model() or ""
        ),
        perspective_for_scope=perspective_for_scope,
        persona_prefix_for_scope=build_offline_role_prefix,
        fallback_for_scope=fallback_route_for_scope,
    )


__all__ = [
    "ACCEPTED_EPISODE_VERSIONS",
    "EPISODE_EXTRACTOR_VERSION",
    "EpisodeExtractor",
    "EpisodeParseError",
    "default_episode_extractor",
    "parse_episode",
]
