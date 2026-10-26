"""测试 / 验证脚本用的假提取器（不进生产注册点，不调用任何模型）。"""

from __future__ import annotations

from collections.abc import Callable

from .contracts import SKIP_NO_REUSABLE_INFO, ExtractionResult, NoteDraft, SegmentInput


class FakeExtractor:
    """每段产一条 episode（引用段内第一条事件），可配置失败 / 零产出 / 越界证据。

    ``calls`` 记下被提取的 segment_id，单测用来断言「没有调用」「没有重跑」。
    """

    def __init__(
        self,
        version: str = "fake-1",
        *,
        fail_on: Callable[[SegmentInput], bool] | None = None,
        empty_on: Callable[[SegmentInput], bool] | None = None,
        out_of_range_on: Callable[[SegmentInput], bool] | None = None,
    ) -> None:
        self.version = version
        self.calls: list[str] = []
        self._fail_on = fail_on
        self._empty_on = empty_on
        self._out_of_range_on = out_of_range_on

    async def extract(self, item: SegmentInput) -> ExtractionResult:
        self.calls.append(item.segment_id)
        if self._fail_on and self._fail_on(item):
            raise ValueError("fake_parse_error")
        if self._empty_on and self._empty_on(item):
            return ExtractionResult(
                notes=(), skip_reason=SKIP_NO_REUSABLE_INFO, extractor_version=self.version
            )
        evidence = (item.segment.source_event_ids[0],)
        if self._out_of_range_on and self._out_of_range_on(item):
            evidence = ("evt-not-in-segment",)
        draft = NoteDraft(
            kind="episode",
            text=f"段 {item.segment_id} 共 {len(item.segment.turn_ids)} 轮",
            source_event_ids=evidence,
        )
        return ExtractionResult(notes=(draft,), extractor_version=self.version)


__all__ = ["FakeExtractor"]
