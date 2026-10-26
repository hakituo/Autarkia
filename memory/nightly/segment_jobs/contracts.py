"""按段提取的共享契约（v3 F3，WP1 创建，WP2 / WP3 只 import）。

字段与 ``.trae/specs/weighted_memory_v3_f3_work_packages.md`` 第 1 节一致；改名或增删字段
要先改那份文档并写明原因。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from memory.topology.segments import Segment

SKIP_NO_REUSABLE_INFO = "no_reusable_info"
SKIP_CONTENT_REJECTED = "content_rejected"
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

    @property
    def segment_id(self) -> str:
        return self.segment.segment_id

    @property
    def char_count(self) -> int:
        return int(self.segment.char_count or 0)


@dataclass(frozen=True)
class NoteDraft:
    """提取器产物（形态待实验定，字段先按 spec §8.1 留全）。"""

    kind: str  # "episode" | "fact" | "preference"
    text: str
    source_event_ids: tuple  # 必须是本段 source_event_ids 的子集
    importance: float = 0.5


@dataclass(frozen=True)
class ExtractionResult:
    notes: tuple  # tuple[NoteDraft, ...]；可为空
    skip_reason: str = ""  # 零产出时必填（如 "no_reusable_info" / "content_rejected"）
    extractor_version: str = ""


@runtime_checkable
class Extractor(Protocol):
    version: str

    async def extract(self, item: SegmentInput) -> ExtractionResult: ...


__all__ = [
    "SKIP_CONTENT_REJECTED",
    "SKIP_NO_REUSABLE_INFO",
    "SKIP_UNSPECIFIED",
    "ExtractionResult",
    "Extractor",
    "NoteDraft",
    "SegmentInput",
]
