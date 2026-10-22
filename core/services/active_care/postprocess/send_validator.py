"""主动消息发送层硬 Gate（defense-in-depth）

2026-09-04 改造：即使决策层已经有了工具出口（send/defer），发送前仍保留
最后一层确定性校验，防止三类内容漏进用户消息链路：

    1. reject_internal_meta   — prompt 内部控制标记 / 决策过程表述泄漏
                                 （[GOODNIGHT_GUARD] / "先不发了" / "按优先级" 等）
    2. reject_prompt_leak     — 整段 prompt / 推理过程泄漏（复用 LeakDetector）
    3. reject_excessive_length— 超长兜底（> poke_max_chars 的普通 poke 压缩一次，
                                 仍超长就 DROP，不进发送链路）

这层不做"语义纠错"，只做"该拦的坚决拦"。拦截后的压缩/丢弃由 pipeline 步骤负责。

判定用的阈值 / 标记词 / 正则 / 豁免集合统一放在 send_validator_rules.py。
"""

from dataclasses import dataclass
from typing import Optional

from core.utils.logger import get_module_logger
from core.services.active_care.postprocess.leak_detector import LeakDetector
from core.services.active_care.postprocess.send_validator_rules import (
    DEFAULT_POKE_MAX_CHARS,
    POKE_LENGTH_EXEMPT_TYPES,
    POKE_STYLE_EXEMPT_TYPES,
    _INTERROGATIVE_MARKERS,
    _INTERNAL_META_MARKERS,
    _PADDED_TRANSITION_RE,
    _PREFIX_SELF_QUESTION_RE,
    _SLEEP_WAKE_PHRASES,
    _STATE_REPORT_PREFIX_RE,
    ABSOLUTE_MESSAGE_MAX_CHARS,
)

logger = get_module_logger("ACTIVE_CARE_SEND_VALIDATOR", "active_care_messages.log")


@dataclass
class ValidationResult:
    """校验结果。allowed=False 表示不得进入发送链路。"""

    allowed: bool
    reason: str = ""
    text: str = ""

    @classmethod
    def ok(cls, text: str) -> "ValidationResult":
        return cls(allowed=True, text=text)

    @classmethod
    def reject(cls, reason: str) -> "ValidationResult":
        return cls(allowed=False, reason=reason)


class ActiveCareSendValidator:
    """发送前最后一层确定性校验。"""

    def __init__(self, max_poke_chars: int = DEFAULT_POKE_MAX_CHARS):
        self.max_poke_chars = int(max_poke_chars or DEFAULT_POKE_MAX_CHARS)

    # ==================== 单条检查 ====================

    @staticmethod
    def reject_internal_meta(text: str) -> Optional[str]:
        """拦截内部控制标记/内部字段名泄漏。返回拦截原因；通过返回 None。"""
        raw = str(text or "")
        if not raw:
            return None
        for marker in _INTERNAL_META_MARKERS:
            if marker in raw:
                return f"internal_meta_marker:{marker[:30]}"
        return None

    @staticmethod
    def reject_prompt_leak(text: str) -> Optional[str]:
        """拦截整段 prompt / 推理过程泄漏。返回拦截原因；通过返回 None。"""
        if LeakDetector.looks_like_prompt_or_reasoning_dump(text):
            return "prompt_or_reasoning_leak"
        return None

    def reject_excessive_length(self, text: str, sys_prompt_type: str = "") -> Optional[str]:
        """拦截超出长度兜底的普通 poke。返回拦截原因；通过返回 None。"""
        text_len = len(str(text or ""))
        if text_len > ABSOLUTE_MESSAGE_MAX_CHARS:
            return f"excessive_length_absolute:{text_len}>{ABSOLUTE_MESSAGE_MAX_CHARS}"
        if str(sys_prompt_type or "").strip() in POKE_LENGTH_EXEMPT_TYPES:
            return None
        if text_len > self.max_poke_chars:
            return f"excessive_length:{text_len}>{self.max_poke_chars}"
        return None

    @staticmethod
    def reject_padded_style(text: str, sys_prompt_type: str = "") -> Optional[str]:
        """拦截『报备自己在做什么 → 转场 → 追问』的铺垫结构。

        案例 4："浇花呢，刚看到阳台上的绿萝又抽新芽了。你英语复习开始了没？"
        ——命中"转场词（刚看到）+ 提问"，属于 prompt 层禁止的"为了弱化查岗感
        先写两句生活铺垫"结构。命中后交给压缩（把核心意思压成一句话），
        而不是直接丢弃（内容本身可以挽救）。
        """
        raw = str(text or "")
        if not raw:
            return None
        if str(sys_prompt_type or "").strip() in POKE_STYLE_EXEMPT_TYPES:
            return None
        # 只拦截"同时含转场词 + 提问意图"的文本
        if not _PADDED_TRANSITION_RE.search(raw):
            return None
        if not any(m in raw for m in _INTERROGATIVE_MARKERS):
            return None
        return "padded_poke_style"

    @staticmethod
    def reject_state_report_prefix(text: str, sys_prompt_type: str = "") -> Optional[str]:
        """拦截『状态自陈前缀 + 提问』结构（无转场词版本）。

        实测案例："在炒菜。你中午一般自己做饭还是点外卖？"
        ——前半句报备自己正在做的事、后半句才是真正的问题，没有"对了/话说"
        等转场词，reject_padded_style 抓不到。命中后同样走压缩一步：
        删掉报备前缀，只保留口语化的问题。
        """
        raw = str(text or "")
        if not raw:
            return None
        if str(sys_prompt_type or "").strip() in POKE_STYLE_EXEMPT_TYPES:
            return None
        match = _STATE_REPORT_PREFIX_RE.match(raw)
        if not match:
            return None
        # 前缀本身是问句（"在干嘛，你呢？"）时不是报备，放行
        prefix_activity = match.group(0)
        if _PREFIX_SELF_QUESTION_RE.search(prefix_activity):
            return None
        # 前缀之后必须还有实质内容，且含疑问特征，才算"报备完再追问"
        remainder = raw[match.end() :].strip()
        if len(remainder) < 3:
            return None
        if not any(m in remainder for m in _INTERROGATIVE_MARKERS):
            return None
        return "padded_status_report"

    @staticmethod
    def reject_sleep_wake_phrases(text: str, sleep_session_active: bool = False) -> Optional[str]:
        """睡眠语境的唤醒类硬禁短语（P1 硬约束的确定性兜底）。"""
        if not sleep_session_active:
            return None
        raw = str(text or "")
        for phrase in _SLEEP_WAKE_PHRASES:
            if phrase in raw:
                return f"sleep_wake_phrase:{phrase[:20]}"
        return None

    # ==================== 汇总 ====================

    def validate(
        self, text: str, sys_prompt_type: str = "", sleep_session_active: bool = False
    ) -> ValidationResult:
        """对发送前文本做完整校验。

        Args:
            sys_prompt_type: 任务类型（用于长度/风格豁免判断）。
            sleep_session_active: 睡眠会话是否活跃（P1 硬校验开关）。

        Returns:
            ValidationResult：allowed=False 携带原因；allowed=True 携带原文本。
        """
        cleaned = str(text or "").strip()
        if not cleaned:
            return ValidationResult.reject("empty_content")

        meta_hit = self.reject_internal_meta(cleaned)
        if meta_hit:
            logger.warning(
                "Active Care: 发送门拦截内部控制标记泄漏 (%s): %s",
                meta_hit, cleaned[:80],
            )
            return ValidationResult.reject(meta_hit)

        leak_hit = self.reject_prompt_leak(cleaned)
        if leak_hit:
            logger.warning(
                "Active Care: 发送门拦截 prompt/推理泄漏 (%s): %s",
                leak_hit, cleaned[:80],
            )
            return ValidationResult.reject(leak_hit)

        sleep_hit = self.reject_sleep_wake_phrases(cleaned, sleep_session_active)
        if sleep_hit:
            logger.warning(
                "Active Care: 发送门拦截睡眠唤醒短语 (%s): %s",
                sleep_hit, cleaned[:80],
            )
            return ValidationResult.reject(sleep_hit)

        length_hit = self.reject_excessive_length(cleaned, sys_prompt_type)
        if length_hit:
            return ValidationResult.reject(length_hit)

        padded_hit = self.reject_padded_style(cleaned, sys_prompt_type)
        if padded_hit:
            return ValidationResult.reject(padded_hit)

        status_report_hit = self.reject_state_report_prefix(cleaned, sys_prompt_type)
        if status_report_hit:
            return ValidationResult.reject(status_report_hit)

        return ValidationResult.ok(cleaned)


__all__ = [
    "ActiveCareSendValidator",
    "ValidationResult",
    "POKE_LENGTH_EXEMPT_TYPES",
    "POKE_STYLE_EXEMPT_TYPES",
    "DEFAULT_POKE_MAX_CHARS",
]
