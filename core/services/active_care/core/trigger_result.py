from dataclasses import dataclass
from enum import Enum


class TriggerOutcome(str, Enum):
    """主动关怀触发结果类型。"""

    DELIVERED = "delivered"
    OVERLAP_BLOCKED = "overlap_blocked"
    GENERATION_FAILED = "generation_failed"
    DISPATCH_FAILED = "dispatch_failed"
    EXECUTION_EXCEPTION = "execution_exception"
    ROLE_NOT_ENABLED = "role_not_enabled"
    CADENCE_POSTCHECK_BLOCKED = "cadence_postcheck_blocked"


@dataclass(frozen=True)
class TriggerMessageResult:
    """一次 trigger_message 调用的显式结果。"""

    delivered: bool
    outcome: TriggerOutcome
    detail: str = ""
    retry_after_minutes: int = 0
    #: 送达时实际发出的文本（开场议程要记下开场白用于去重）
    content: str = ""

    @property
    def is_interval_blocked(self) -> bool:
        return self.outcome is TriggerOutcome.OVERLAP_BLOCKED

    @property
    def legacy_skip_reason(self) -> str:
        if self.outcome is TriggerOutcome.OVERLAP_BLOCKED:
            return "overlap_guard"
        if self.outcome is TriggerOutcome.GENERATION_FAILED:
            return "generation_failed"
        if self.outcome is TriggerOutcome.DISPATCH_FAILED:
            return "dispatch_failed"
        if self.outcome is TriggerOutcome.EXECUTION_EXCEPTION:
            return "exception"
        if self.outcome is TriggerOutcome.CADENCE_POSTCHECK_BLOCKED:
            return "cadence_postcheck_blocked"
        return ""
