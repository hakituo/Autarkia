"""Nightly 蒸馏的 Prompt、响应解析（人物线索判定见 people_filter）。"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from core.services.dual_role.personas import resolve_role_id
from core.utils.logger import get_module_logger

from .people_filter import (
    build_excluded_people_names as _build_excluded_people_names,
    detect_profile_signals_locally as _detect_profile_signals_locally,
    empty_profile_signals as _empty_profile_signals,
    filter_people_mentions as _filter_people_mentions,
    filter_profile_signals as _filter_profile_signals,
)

logger = get_module_logger(__name__, "nightly_processor.log")


class DistillationCodec:
    """蒸馏服务使用的无状态文本转换能力。

    人物线索的排除/本地信号逻辑在 ``people_filter``，这里保留同名入口，
    既有调用方（service / task_runner / 测试）不用改。
    """

    @staticmethod
    def group_memories_by_time(
        messages: List[Dict[str, Any]],
        gap_seconds: float,
        max_group_size: int,
    ) -> List[List[Dict[str, Any]]]:
        """按时间连续性分组，组内超限时切分。"""
        ordered = sorted(
            messages,
            key=lambda item: float(item.get("timestamp", 0) or 0),
        )
        groups: List[List[Dict[str, Any]]] = []
        current: List[Dict[str, Any]] = []
        previous_ts: float | None = None
        for message in ordered:
            timestamp = float(message.get("timestamp", 0) or 0)
            if previous_ts is not None and (
                timestamp - previous_ts > gap_seconds
                or len(current) >= max_group_size
            ):
                if current:
                    groups.append(current)
                current = []
            current.append(message)
            previous_ts = timestamp
        if current:
            groups.append(current)
        return groups

    @staticmethod
    def _split_by_length(
        group: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """把无需 LLM 的短内容和批量 LLM 内容分开。"""
        short_items = [
            item
            for item in group
            if not item.get("content") or len(str(item.get("content", ""))) < 20
        ]
        long_items = [
            item
            for item in group
            if item.get("content") and len(str(item.get("content", ""))) >= 20
        ]
        return short_items, long_items

    @staticmethod
    def generate_distillation_prompt(
        content: str,
        perspective: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, str]]:
        """生成稳定 system + 动态 user 的单条蒸馏 Prompt。

        perspective 为空（scope 解析不出角色）时退回中立模板。
        """
        from .perspective import build_single_distillation_prompt

        return build_single_distillation_prompt(content, perspective or {})

    @staticmethod
    def generate_batch_distillation_prompt(
        messages: List[Dict[str, Any]],
        perspective: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, str]]:
        """生成稳定 system + 编号动态条目的批量蒸馏 Prompt。"""
        from .perspective import build_batch_distillation_prompt

        return build_batch_distillation_prompt(messages, perspective or {})

    @classmethod
    def parse_batch_distillation_response(
        cls,
        response: str,
    ) -> Dict[int, Tuple[str, List[str]]]:
        """解析批量蒸馏响应。"""
        results: Dict[int, Tuple[str, List[str]]] = {}
        if not response:
            return results
        pattern = re.compile(r"【条目(\d+)】")
        matches = list(pattern.finditer(response))
        if not matches:
            logger.warning(
                "批量蒸馏响应未匹配到任何【条目N】，原始响应: %s",
                response[:200],
            )
            return results
        for position, match in enumerate(matches):
            try:
                index = int(match.group(1))
            except (TypeError, ValueError):
                continue
            start = match.end()
            end = (
                matches[position + 1].start()
                if position + 1 < len(matches)
                else len(response)
            )
            segment = response[start:end].strip()
            summary, keywords = cls.parse_distillation_response(segment)
            if summary:
                results[index] = (summary, keywords)
            else:
                logger.warning(
                    "批量蒸馏条目 %d 解析为空，跳过（segment='%s'）",
                    index,
                    segment[:100],
                )
        return results

    # ---- 人物线索门控（委托 people_filter） ------------------------------

    @staticmethod
    def empty_profile_signals(*, analyzed: bool) -> Dict[str, Any]:
        return _empty_profile_signals(analyzed=analyzed)

    @staticmethod
    def build_excluded_people_names(
        perspective: Optional[Dict[str, str]] = None,
    ) -> List[str]:
        return _build_excluded_people_names(perspective)

    @staticmethod
    def filter_people_mentions(
        values: List[str],
        excluded_names: Optional[List[str]] = None,
    ) -> List[str]:
        return _filter_people_mentions(values, excluded_names)

    @classmethod
    def filter_profile_signals(
        cls,
        metadata: Dict[str, Any],
        perspective: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        return _filter_profile_signals(metadata, perspective)

    @classmethod
    def detect_profile_signals_locally(
        cls,
        content: str,
        *,
        role: str = "",
        owner_role_id: str = "",
    ) -> Dict[str, Any]:
        return _detect_profile_signals_locally(
            content,
            role=role,
            owner_role_id=owner_role_id,
        )

    # ---- 线索解析 -------------------------------------------------------

    @staticmethod
    def _parse_profile_signal_values(raw_value: str) -> List[str]:
        """解析线索值，过滤空标记。"""
        empty_values = {"无", "none", "null", "nil", "没有", "无人物", "无更新"}
        values: List[str] = []
        for item in re.split(r"[,，、;/；|]", str(raw_value or "")):
            value = item.strip().strip("[]【】")
            if not value or value.lower() in empty_values:
                continue
            if value not in values:
                values.append(value)
        return values

    @classmethod
    def parse_profile_signals(cls, response: str) -> Dict[str, Any]:
        """从单条蒸馏响应中解析人物与角色演化线索。"""
        metadata = cls.empty_profile_signals(analyzed=False)
        if not response:
            return metadata
        people_match = re.search(
            r"【人物线索】\s*[：:]\s*(.*?)(?=\n|【|$)",
            response,
            re.S,
        )
        role_match = re.search(
            r"【角色演化】\s*[：:]\s*(.*?)(?=\n|【|$)",
            response,
            re.S,
        )
        metadata["profile_signal_analyzed"] = bool(people_match and role_match)
        if people_match:
            metadata["people_mentions"] = cls._parse_profile_signal_values(
                people_match.group(1)
            )
        if role_match:
            metadata["role_update_candidates"] = cls._parse_role_candidates(
                role_match.group(1)
            )
        return metadata

    @classmethod
    def _parse_role_candidates(cls, raw_value: str) -> List[str]:
        """角色演化只保留角色名，模型多写的「：习惯……」说明一律丢掉。"""
        values: List[str] = []
        for item in cls._parse_profile_signal_values(raw_value):
            name = re.split(r"[：:]", item, 1)[0].strip()
            if resolve_role_id(name) and name not in values:
                values.append(name)
        return values

    @classmethod
    def parse_batch_profile_signals(
        cls,
        response: str,
    ) -> Dict[int, Dict[str, Any]]:
        """按条目号解析批量蒸馏中的人物门控线索。"""
        parsed: Dict[int, Dict[str, Any]] = {}
        pattern = re.compile(r"【条目(\d+)】")
        matches = list(pattern.finditer(response or ""))
        for position, match in enumerate(matches):
            try:
                index = int(match.group(1))
            except (TypeError, ValueError):
                continue
            start = match.end()
            end = (
                matches[position + 1].start()
                if position + 1 < len(matches)
                else len(response)
            )
            parsed[index] = cls.parse_profile_signals(response[start:end].strip())
        return parsed

    @staticmethod
    def parse_distillation_response(response: str) -> Tuple[str, List[str]]:
        """解析 LLM 返回的梗概与关键词。"""
        summary = ""
        keywords: List[str] = []
        try:
            summary_match = re.search(
                r"【梗概】[：:](.*?)(?=\n|【|$)",
                response,
                re.S,
            )
            if summary_match:
                summary = summary_match.group(1).strip()
            keywords_match = re.search(
                r"【关键词】[：:](.*?)(?=\n|【|$)",
                response,
                re.S,
            )
            if keywords_match:
                keywords = [
                    keyword.strip()
                    for keyword in re.split(
                        r"[,，、\s]+",
                        keywords_match.group(1).strip(),
                    )
                    if keyword.strip()
                ]
        except Exception as exc:
            logger.error("解析蒸馏响应出错: %s, 原始响应: %s", exc, response)
        return summary, keywords
