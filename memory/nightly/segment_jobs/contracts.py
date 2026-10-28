"""按段提取的共享契约（v3 F3，WP1 创建，WP2 / WP3 只 import）。

字段与 ``.trae/specs/weighted_memory_v3_f3_work_packages.md`` 第 1 节一致；改名或增删字段
要先改那份文档并写明原因。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from memory.topology.segments import Segment

SKIP_NO_REUSABLE_INFO = "no_reusable_info"
SKIP_CONTENT_REJECTED = "content_rejected"
#: 整段都是没聊完的话题，全部交给下一段接力整理（本段零产出但已处理）
SKIP_CARRIED_FORWARD = "carried_forward"
#: 提取器零产出却没给原因：编排层补上，避免出现「无原因的空结果」
SKIP_UNSPECIFIED = "unspecified"


@dataclass(frozen=True)
class SegmentInput:
    """一段待提取的输入。

    ``events`` 是本段事件 payload（dict），已按主线过滤、去重、去掉不进提炼的事件，
    顺序 = 时间序；只有 ``closed=True`` 的段才允许提取。

    ``aliases`` 是契约之外的附加字段（有默认值，不影响按第 1 节写的代码）：
    被合并掉的重复用户提交 ``(被合并 event_id, 保留 event_id)``，供证据映射用。
    """

    scope: str
    conversation_id: str
    segment: Segment
    events: tuple
    closed: bool
    aliases: tuple = ()
    #: 分段器 v2：会话内话题切点之后的段附带的上一段末尾事件（只供理解，不是来源）
    context_events: tuple = ()
    #: 接力（v10）：同一次对话里紧挨着的上一段（本段是话题切点之后的段时才有）
    previous_segment_id: str = ""
    #: 接力：上一段没聊完、交给本段一起整理的往来（已并进 ``events`` 开头，也算本段来源）
    carried_event_ids: tuple = ()

    @property
    def segment_id(self) -> str:
        return self.segment.segment_id

    @property
    def continues(self) -> bool:
        """本段之后同一次对话还在继续（本段结束于话题切点）。"""
        return self.segment.boundary_reason == "topic"

    @property
    def allowed_sources(self) -> tuple:
        """证据校验口径：本段来源 + 接力来的往来。"""
        return (*self.segment.source_event_ids, *self.carried_event_ids)

    @property
    def char_count(self) -> int:
        return int(self.segment.char_count or 0)


@dataclass(frozen=True)
class NoteDraft:
    """提取器产物（形态待实验定，字段先按 spec §8.1 留全）。"""

    kind: str  # "episode" | "fact" | "preference" | "plan"
    text: str
    source_event_ids: tuple  # 必须是本段 source_event_ids 的子集
    importance: float = 0.5
    #: 附带的结构化信号（v6：profile_signal_analyzed / people_mentions / role_update_candidates）
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractionResult:
    notes: tuple  # tuple[NoteDraft, ...]；可为空
    skip_reason: str = ""  # 零产出时必填（如 "no_reusable_info" / "content_rejected"）
    extractor_version: str = ""
    #: 接力：最后一个话题没聊完，交给下一段一起整理的往来（事件 ID）；这些往来本段不写梗概
    carry_event_ids: tuple = ()


@runtime_checkable
class Extractor(Protocol):
    version: str

    async def extract(self, item: SegmentInput) -> ExtractionResult: ...


__all__ = [
    "SKIP_CARRIED_FORWARD",
    "SKIP_CONTENT_REJECTED",
    "SKIP_NO_REUSABLE_INFO",
    "SKIP_UNSPECIFIED",
    "ExtractionResult",
    "Extractor",
    "NoteDraft",
    "SegmentInput",
]
