"""Nightly 记忆蒸馏执行服务。"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

from core.llm.sensitivity_fallback import stream_text_with_sensitivity_fallback
from core.utils.logger import get_module_logger

from .candidates import collect_candidates
from .config import get_memory_distillation_model, is_distillation_role_allowed
from .distill_run import leased_run, open_ledger, run_budget, settle
from .distillation_codec import DistillationCodec
from .perspective import format_speaker_item, resolve_distillation_perspective

logger = get_module_logger(__name__, "nightly_processor.log")
SchedulerProvider = Callable[[], Any]


class MemoryDistillationService(DistillationCodec):
    """执行单个记忆 scope 的候选筛选、批量请求与失败回退。"""

    def __init__(
        self,
        config: Dict[str, Any],
        scheduler_provider: SchedulerProvider,
    ) -> None:
        self.config = config
        self._scheduler_provider = scheduler_provider

    async def distill_memories_async(self, user_id: str, manager: Any) -> int:
        """筛选旧记忆并调用 LLM 进行蒸馏。"""
        perspective = resolve_distillation_perspective(manager)
        if not is_distillation_role_allowed(self.config, perspective.get("role_id") or ""):
            logger.info("跳过蒸馏：scope=%s 角色=%s 不在白名单", user_id, perspective.get("role_id") or "未识别")
            return 0
        threshold_hours = self.config.get("distillation_threshold_hours", 1)
        threshold_ts = time.time() - (threshold_hours * 3600)
        distillation_model = get_memory_distillation_model()
        budget = run_budget(self.config)
        ledger = open_ledger(manager, self.config)
        to_distill = collect_candidates(
            manager,
            threshold_ts,
            int(budget["max_items"]),
            ledger=ledger,
            max_chars=int(budget["max_chars"]),
        )
        if not to_distill:
            ledger.save()  # 显式 skipped 也要落账
            return 0

        logger.info(
            "发现 %d 条待蒸馏记忆（积压 %d），开始压缩...视角=%s",
            len(to_distill),
            to_distill.backlog_total,
            perspective.get("role_name") or "中立",
        )
        scheduler = self._scheduler_provider()
        gap_seconds = (
            float(self.config.get("distillation_group_gap_minutes") or 30) * 60
        )
        batch_size = int(self.config.get("distillation_batch_size") or 10)
        distilled_count = 0
        with leased_run(manager, ledger, to_distill, budget) as clock:
            for group in self.group_memories_by_time(
                to_distill.items,
                gap_seconds,
                batch_size,
            ):
                if clock.expired:
                    logger.info("蒸馏墙钟预算用完，剩余候选退回下一轮")
                    break
                short_items, long_items = self._split_by_length(group)
                distilled_count += self._persist_short_items(
                    manager,
                    short_items,
                    perspective,
                )
                if long_items:
                    distilled_count += await self._distill_batch(
                        scheduler,
                        manager,
                        long_items,
                        distillation_model,
                        perspective,
                    )
                clock.settled |= settle(manager, ledger, group)
        return distilled_count

    @classmethod
    def _persist_short_items(
        cls,
        manager: Any,
        messages: List[Dict[str, Any]],
        perspective: Dict[str, str],
    ) -> int:
        """短内容直接落盘，不消耗 LLM 请求。"""
        persisted = 0
        for message in messages:
            try:
                content = message.get("content", "")
                metadata = cls.filter_profile_signals(
                    cls.detect_profile_signals_locally(
                        str(content or ""),
                        role=str(message.get("role") or ""),
                        owner_role_id=str(perspective.get("role_id") or ""),
                    ),
                    perspective,
                )
                if manager.update_memory_distillation(
                    message["id"],
                    content,
                    [],
                    distillation_metadata=metadata,
                ):
                    persisted += 1
            except Exception as exc:
                logger.error("蒸馏短内容 %s 时出错: %s", message.get("id"), exc)
        return persisted

    @staticmethod
    async def _stream_llm_text(
        scheduler: Any,
        prompt: Any,
        llm_kwargs: Dict[str, Any],
    ) -> str:
        """收集一次流式调用的正文；422 内容审核拒绝时自动换降级型号重跑。"""
        return await stream_text_with_sensitivity_fallback(scheduler, prompt, llm_kwargs)

    async def _distill_batch(
        self,
        scheduler: Any,
        manager: Any,
        messages: List[Dict[str, Any]],
        distillation_model: Optional[str],
        perspective: Dict[str, str],
    ) -> int:
        """蒸馏一个时间连续批次，失败时逐条回退。"""
        # deepseek 思考模式的 reasoning 也占输出预算，预算太紧会把 JSON 截断成空结果，
        # 这里按条数放大并给一个足够大的下限。
        llm_kwargs: Dict[str, Any] = {
            "max_tokens": max(4096, len(messages) * 300),
            "temperature": 0.3,
        }
        if distillation_model:
            llm_kwargs["model_hint"] = distillation_model
        try:
            prompt = self.generate_batch_distillation_prompt(messages, perspective)
            full_response = await self._stream_llm_text(scheduler, prompt, llm_kwargs)
        except Exception as exc:
            logger.error("批量蒸馏失败（%d 条），回退逐条: %s", len(messages), exc)
            persisted = 0
            for message in messages:
                if await self.distill_one_async(
                    scheduler,
                    manager,
                    message,
                    distillation_model,
                    perspective,
                ):
                    persisted += 1
            return persisted
        return self._persist_batch_response(manager, messages, full_response, perspective)

    def _persist_batch_response(
        self,
        manager: Any,
        messages: List[Dict[str, Any]],
        response: str,
        perspective: Optional[Dict[str, str]] = None,
    ) -> int:
        """解析并落盘一个批量响应。"""
        results = self.parse_batch_distillation_response(response)
        profile_signals = self.parse_batch_profile_signals(response)
        persisted = 0
        for index, message in enumerate(messages, start=1):
            try:
                entry = results.get(index)
                if not entry:
                    logger.warning(
                        "批量蒸馏结果缺失条目 %d [%s]，原始响应长度=%s",
                        index,
                        message["id"][:8],
                        len(response),
                    )
                    continue
                summary, keywords = entry
                logger.info(
                    "蒸馏结果 [%s]: summary='%s', keywords=%s",
                    message["id"][:8],
                    summary,
                    keywords,
                )
                metadata = self.filter_profile_signals(
                    profile_signals.get(
                        index,
                        self.empty_profile_signals(analyzed=False),
                    ),
                    perspective,
                )
                if manager.update_memory_distillation(
                    message["id"],
                    summary,
                    keywords,
                    distillation_metadata=metadata,
                ):
                    persisted += 1
                else:
                    logger.warning("更新记忆失败 [%s]", message["id"][:8])
            except Exception as exc:
                logger.error("蒸馏单条记忆 %s 时出错: %s", message.get("id"), exc)
        return persisted

    async def distill_one_async(
        self,
        scheduler: Any,
        manager: Any,
        message: Dict[str, Any],
        distillation_model: Optional[str],
        perspective: Optional[Dict[str, str]] = None,
    ) -> bool:
        """单条记忆蒸馏，供批量失败时回退。"""
        perspective = perspective or resolve_distillation_perspective(manager)
        try:
            content = message.get("content", "")
            if not content or len(content) < 20:
                metadata = self.detect_profile_signals_locally(
                    str(content or ""),
                    role=str(message.get("role") or ""),
                    owner_role_id=str(perspective.get("role_id") or ""),
                )
                return bool(
                    manager.update_memory_distillation(
                        message["id"],
                        content,
                        [],
                        distillation_metadata=metadata,
                    )
                )
            role = str(message.get("role") or "unknown")
            prompt = self.generate_distillation_prompt(
                format_speaker_item(role, content, perspective),
                perspective,
            )
            # 单条蒸馏同样要给思考模式留出预算，否则正文被 reasoning 挤空。
            llm_kwargs: Dict[str, Any] = {
                "max_tokens": 2048,
                "temperature": 0.3,
            }
            if distillation_model:
                llm_kwargs["model_hint"] = distillation_model
            full_response = await self._stream_llm_text(scheduler, prompt, llm_kwargs)
            summary, keywords = self.parse_distillation_response(full_response)
            metadata = self.filter_profile_signals(
                self.parse_profile_signals(full_response),
                perspective,
            )
            if not summary:
                logger.warning(
                    "蒸馏结果为空 [%s]: response='%s'",
                    message["id"][:8],
                    full_response[:100],
                )
                return False
            if manager.update_memory_distillation(
                message["id"],
                summary,
                keywords,
                distillation_metadata=metadata,
            ):
                logger.info(
                    "蒸馏成功 [%s]: 梗概='%s...', 关键词=%s",
                    message["id"][:8],
                    summary[:30],
                    keywords[:3],
                )
                return True
            logger.warning("更新记忆失败 [%s]", message["id"][:8])
            return False
        except Exception as exc:
            logger.error("蒸馏单条记忆 %s 时出错: %s", message.get("id"), exc)
            return False
