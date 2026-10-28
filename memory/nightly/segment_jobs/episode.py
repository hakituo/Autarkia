"""生产按段提取器：每段 0..n 条按话题的 episode 梗概 + 0..5 条短事实（v3 F3；v7 起按话题分条）。

- 来源取整段可提炼事件：梗概概括的是整段，不要求模型逐条标证据（少一类失败）；
- system 用与主对话同源的离线角色前缀（v5），提取指令接在其后；同一角色前缀逐字节稳定；
- 模型走 nightly 蒸馏模型，422 内容审核拒绝由 ``core.llm.sensitivity_fallback`` 换 DeepSeek，
  按角色分 key 的链路降级到该角色自己的 DeepSeek 路由；
- 推理模型的思考 token 计入 ``max_tokens``（C8 第一次实跑就栽在这），预算按段长放大；
- 空响应 / 解析失败抛异常，由编排层记 failed 可重试；模型明确说没信息才记 skipped。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.llm.sensitivity_fallback import stream_text_with_sensitivity_fallback

from .contracts import (
    SKIP_CARRIED_FORWARD,
    SKIP_NO_REUSABLE_INFO,
    ExtractionResult,
    NoteDraft,
    SegmentInput,
)
from .episode_parse import (
    EpisodeParseError,
    parse_episode,
    parse_fact_items,
    parse_open_ids,
    parse_signals,
    parse_topic_items,
)
from .prompts import build_messages, group_exchanges
from .relay import carry_start

#: 换提示词 / 模型 / 解析规则时改这里，编排层会按新版本重算
#: 2：角色的知识性解释只留一句主题，篇幅留给用户自己的事实（试跑发现 p50 402 字、多在复述科普）
#: 3：固定长前缀（规则 + 合成示例）放 system、角色名与对话放末尾，命中供应商前缀缓存
#: 4：改用用户原有的人设回想写法（公平对比与客观写法 21/44 持平，保留角色主观感受）
#: 5：system 换成与主对话同源的离线角色静态人设前缀，提取指令接在后面；DeepSeek 按角色分 key
#: 6：字数随段长、附前文（分段器 v2）、同次输出画像信号（people / role_updates）、单条上限 4000
#: 7：按话题分条（往来编号 → 每条梗概只挂自己依据的往来），每条 40–150 字
#: 8：每条梗概带重要度；同次摘关于对方的短事实 / 偏好 / 计划（kind=fact|preference|plan）
#: 9：短事实也带重要度；plan 带 status（open / done / cancelled），自动注入据此去掉已完成的计划
#: 10：接力切分（没聊完的话题交给下一段）；DeepSeek / MiniMax 默认不思考，两次解析失败再开思考补一次
#: 10.1：时间说法和关键词照原话写；往来标日期，相对时间括号注明具体日期（时间题问的是具体日期）。
#: 小改动只升小版本；大版本留给输出结构 / 分条方式这类变化
#: 10.2：写入前由代码给「今天 / 明天 / 昨晚」等补「（X月X日）」（提示词不变；模型自己注明率约 5%）
#: （plan 由代码算到期日写进 valid_to，不改版本：不需要重跑，旧段用 backfill_plan_due.py 回填）
EPISODE_EXTRACTOR_VERSION = "segment-episode-10.2"
#: 仍算「已完成」的旧版本：v3 / v4 已回填的段，用户决定不为改写法重花钱
ACCEPTED_EPISODE_VERSIONS = (
    EPISODE_EXTRACTOR_VERSION,
    "segment-episode-10.1",
    "segment-episode-10",
    "segment-episode-9",
    "segment-episode-8",
    "segment-episode-7",
    "segment-episode-6",
    "segment-episode-5",
    "segment-episode-4",
    "segment-episode-3",
)
MIN_MAX_TOKENS = 4096
TOKENS_PER_INPUT_CHAR = 1.0
MAX_MAX_TOKENS = 12288
#: DeepSeek / MiniMax 路由每次尝试的思考开关：不思考 → 不思考 → 思考
THINKING_ATTEMPTS = (False, False, True)


def _span(events: list[Any]) -> dict[str, float]:
    """这条梗概自己依据的往来的起止时间（一段多条时各条时间不同，时间类问题靠它）。"""
    stamps = []
    for event in events:
        try:
            stamps.append(float(event.get("timestamp") or 0))
        except (TypeError, ValueError):
            continue
    stamps = [value for value in stamps if value > 0]
    return {"occurred_from": min(stamps), "occurred_to": max(stamps)} if stamps else {}


def _dated(text: str, events: list[Any]) -> str:
    """相对时间补具体日期（10.2，不调模型），参照这条依据的第一次往来的时间。"""
    from memory.notes.dates import annotate

    return annotate(text, _span(events).get("occurred_from"))


def _due(text: str, said_at: float | None) -> dict[str, float]:
    """plan 的到期日（不调模型，见 ``memory.notes.plan_due``）；认不出日期时为空。"""
    from memory.notes.plan_due import due_timestamp

    due = due_timestamp(text, said_at)
    return {"valid_to": due} if due else {}


def _sources(events: list[Any]) -> tuple[str, ...]:
    return tuple(str(e.get("event_id")) for e in events if str(e.get("event_id") or ""))


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
        carried = set(item.carried_event_ids)
        prompt = build_messages(
            events,
            self._perspective_for_scope(item.scope),
            persona_prefix=self._persona_prefix(item.scope),
            context_events=getattr(item, "context_events", ()) or (),
            source_chars=item.char_count,
            carried_exchanges=len(
                group_exchanges([e for e in events if e.get("event_id") in carried])
            ),
            continues=item.continues,
        )
        exchanges = group_exchanges(events)
        # DeepSeek / MiniMax：先不思考跑两次，都解析失败再开思考补一次（10-27 aveline 83 段四组对比：
        # 两家开思考都不提升质量，只慢 3–8 倍、输出多 3–13 倍；MiniMax 思考在默认上限下 31% 截断）。
        # 其它路由只跑一次。
        attempts = THINKING_ATTEMPTS if _has_thinking_switch(self._model_hint) else (None,)
        for index, thinking in enumerate(attempts):
            try:  # 空响应（接口报错 / 被拦）和格式不对一样走重试
                text = await self._call(item, prompt, thinking)
                return self._result(text, exchanges, item.continues)
            except EpisodeParseError:
                if index == len(attempts) - 1:
                    raise
        raise EpisodeParseError("no_attempt")

    async def _call(self, item: SegmentInput, prompt: list, thinking: bool | None) -> str:
        llm_kwargs: dict[str, Any] = {"max_tokens": _budget(item), "temperature": 0.2}
        # 只对 DeepSeek 路由传思考开关：其它客户端不一定认这个参数，可能原样发给接口
        if thinking is not None:
            llm_kwargs["thinking_enabled"] = thinking
        if self._model_hint:
            llm_kwargs["model_hint"] = self._model_hint
        fallback = self._fallback_for_scope(item.scope) if self._fallback_for_scope else ""
        text = await stream_text_with_sensitivity_fallback(
            self._scheduler_provider(), prompt, llm_kwargs, fallback_model_hint=fallback
        )
        if not str(text or "").strip():
            raise EpisodeParseError("empty_response")
        return str(text)

    def _result(self, text: str, exchanges: list, continues: bool) -> ExtractionResult:
        topics, skip = parse_topic_items(text, len(exchanges))
        if not topics:
            return ExtractionResult(notes=(), skip_reason=skip, extractor_version=self.version)
        # 接力：最后一个话题没聊完就交给下一段，这几次往来本段不写梗概 / 短事实
        start = carry_start(parse_open_ids(text, len(exchanges)), exchanges) if continues else None
        tail = set(range(start, len(exchanges))) if start is not None else set()
        signals = parse_signals(text)
        notes = []
        for ids, summary, importance in topics:
            if tail and set(ids) <= tail:
                continue
            picked = [event for index in ids for event in exchanges[index]]
            notes.append(
                NoteDraft(
                    kind="episode",
                    text=_dated(summary, picked),
                    source_event_ids=_sources(picked),
                    importance=importance,
                    metadata={**signals, **_span(picked)},
                )
            )
        # 短事实不带画像信号：信号按段算一次，挂在梗概上即可
        for kind, ids, fact, importance, status in parse_fact_items(text, len(exchanges)):
            if tail and set(ids) <= tail:
                continue
            picked = [event for index in ids for event in exchanges[index]]
            metadata = {**_span(picked), **({"status": status} if status else {})}
            text = _dated(fact, picked)
            if kind == "plan":
                metadata.update(_due(text, metadata.get("occurred_from")))
            notes.append(
                NoteDraft(
                    kind=kind,
                    text=text,
                    source_event_ids=_sources(picked),
                    importance=importance,
                    metadata=metadata,
                )
            )
        carry = _sources([event for index in sorted(tail) for event in exchanges[index]])
        return ExtractionResult(
            notes=tuple(notes),
            skip_reason="" if notes else SKIP_CARRIED_FORWARD,
            extractor_version=self.version,
            carry_event_ids=carry,
        )


def _has_thinking_switch(model_hint: str) -> bool:
    """DeepSeek / MiniMax 路由认顶层 ``thinking`` 开关（10-27 实测）；空路由（走默认模型）不传。"""
    hint = str(model_hint or "").lower()
    return "deepseek" in hint or "minimax" in hint


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
    "parse_signals",
]
