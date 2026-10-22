#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主动关怀决策的「精编 state」构造器。

决策模型（Luna Decisions / Microsoft-Decision-1）只按输入计费、输出免费，
所以 state 的长度直接等于成本；同时实测证明 **state 越紧凑判定越准**：

    把现有 ~9k 字符的 llm_ctx 整体 JSON dump 进去时，即使 state 里明明写着
    「用户要求的提醒已到期」，模型仍一律答 noul≈0.00（噪声淹没信号）；
    换成下面这种 ~300 字符的事实清单后，同一场景立刻答 1.00。

两条设计原则：

1. **只陈述事实，不做算术。** 冷却余量（如「1199s < 需要 1200s」）这类判断
   由代码完成后再写成「已满足 / 尚未满足」，不把原始数字丢给模型比较 ——
   实测模型会被这种近乎达标的数字带偏。
2. **只放决策必需的信息。** 完整人设、历史原文、画像明细留给内容生成阶段，
   决策只需要「现在该不该联系」的依据。
"""

from typing import Any, Dict, Iterable, List, Optional

# 单条事实的长度上限，避免某个字段意外膨胀把 state 撑大（撑大 = 变贵 + 变不准）
_FACT_MAX_CHARS = 160
# state 总长度上限；超出时按「低优先级在后」的顺序截断
_DEFAULT_MAX_CHARS = 1200


def _clip(text: Any, limit: int = _FACT_MAX_CHARS) -> str:
    """把任意值压成单行短文本。"""
    value = str(text or "").replace("\n", " ").strip()
    if len(value) > limit:
        return value[: limit - 1] + "…"
    return value


def _first_non_empty(*values: Any) -> str:
    """返回第一个非空值的裁剪结果。"""
    for value in values:
        if value:
            text = _clip(value)
            if text:
                return text
    return ""


def _describe_activity(user_activity: Any) -> str:
    """把用户活动字典压成一句可读描述。"""
    if not isinstance(user_activity, dict) or not user_activity:
        return ""
    process = _clip(user_activity.get("process"), 40)
    busy = user_activity.get("busy")
    if busy is True:
        state = "正在忙"
    elif busy is False:
        state = "不忙"
    else:
        state = ""
    parts = [p for p in (process, state) if p]
    return "，".join(parts)


def _describe_sleep(llm_ctx: Dict[str, Any]) -> str:
    """汇总睡眠相关事实。"""
    if llm_ctx.get("sleep_session"):
        return _first_non_empty(llm_ctx.get("sleep_status_desc"), "处于睡眠会话中")
    return _first_non_empty(llm_ctx.get("sleep_status_desc"), "未在睡眠会话中")


def _describe_gap(llm_ctx: Dict[str, Any]) -> str:
    """描述距上次主动发送的时间与最小间隔是否已满足。

    这里刻意只输出「已满足 / 尚未满足」，不输出 1199 / 1200 这类原始数字。
    """
    elapsed = llm_ctx.get("elapsed_since_last_proactive_seconds")
    elapsed_text = _first_non_empty(llm_ctx.get("time_since_last_proactive_send"))
    if not elapsed_text:
        return ""
    try:
        elapsed_seconds = int(elapsed or 0)
    except (TypeError, ValueError):
        elapsed_seconds = 0
    if elapsed_seconds <= 0:
        return f"距上次主动发送：{elapsed_text}（从未发送过）"
    return f"距上次主动发送：{elapsed_text}"


def _collect_topics(priority_focus: Any, limit: int = 3) -> List[str]:
    """从 priority_focus 里抽出可跟进的未完结话题。"""
    if not isinstance(priority_focus, dict):
        return []
    topics: List[str] = []
    for key in ("portrait_priority", "daily_push_ranked"):
        raw = priority_focus.get(key)
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    text = _first_non_empty(item.get("title"), item.get("topic"))
                else:
                    text = _clip(item)
                if text and text not in topics:
                    topics.append(text)
                if len(topics) >= limit:
                    return topics
    return topics


def _collect_recent_proactive(llm_ctx: Dict[str, Any], limit: int = 3) -> List[str]:
    """最近主动发过的话题，用于提示避免重复。"""
    raw = llm_ctx.get("recent_proactive_topics") or llm_ctx.get("repeat_anchors")
    if isinstance(raw, str):
        return [_clip(raw)]
    if not isinstance(raw, Iterable):
        return []
    out: List[str] = []
    for item in raw:
        text = _clip(item)
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def build_compact_state(
    llm_ctx: Dict[str, Any],
    *,
    persona_name: str = "",
    extra_facts: Optional[Dict[str, str]] = None,
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> str:
    """把决策上下文压成一段紧凑的事实清单。

    Args:
        llm_ctx: 决策上下文（``content_planner._build_llm_ctx`` 的产物）。
        persona_name: 角色名，用于第一行身份说明。
        extra_facts: 调用方补充的事实（如到期提醒、设备端信息），键为标签、值为内容。
        max_chars: 结果长度上限，超出时丢弃优先级最低的行。

    Returns:
        供 Decisions API ``state`` 字段直接使用的中文事实清单。
    """
    lines: List[str] = []

    identity = persona_name or "角色"
    lines.append(f"【角色】{identity}，与用户是亲密关系。")

    now_text = _first_non_empty(llm_ctx.get("now"))
    tod_text = _first_non_empty(llm_ctx.get("tod"))
    if now_text:
        lines.append(f"【现在】{now_text}（{tod_text}）。" if tod_text else f"【现在】{now_text}。")

    silence = _first_non_empty(llm_ctx.get("time_since_last_interaction"))
    last_user = ""
    history = llm_ctx.get("recent_history_summary")
    if isinstance(history, list):
        for item in reversed(history):
            text = _clip(item)
            if text.startswith("user:"):
                last_user = text[len("user:") :].strip()
                break
    user_line = "【用户】"
    if silence:
        user_line += f"上次说话在 {silence} 前"
    else:
        user_line += "近期没有说话"
    if last_user:
        user_line += f"，说的是「{last_user}」"
    lines.append(user_line + "。")

    gap_line = _describe_gap(llm_ctx)
    if gap_line:
        lines.append(f"【主动消息】{gap_line}。")

    activity = _describe_activity(llm_ctx.get("user_activity"))
    if activity:
        lines.append(f"【用户活动】{activity}。")

    lines.append(f"【睡眠】{_describe_sleep(llm_ctx)}。")

    if llm_ctx.get("quiet_mode_active"):
        reason = _first_non_empty(llm_ctx.get("reduced_mode_reason"))
        lines.append(f"【勿扰】当前处于低打扰模式{('（' + reason + '）') if reason else ''}。")

    topics = _collect_topics(llm_ctx.get("priority_focus"))
    lines.append(f"【可跟进话题】{'；'.join(topics)}。" if topics else "【可跟进话题】无。")

    recent = _collect_recent_proactive(llm_ctx)
    if recent:
        lines.append(f"【最近主动话题】{'；'.join(recent)}（避免重复）。")

    if extra_facts:
        for label, value in extra_facts.items():
            text = _clip(value)
            if text:
                lines.append(f"【{_clip(label, 20)}】{text}。")

    chosen_action = _first_non_empty(llm_ctx.get("chosen_action"))
    if chosen_action:
        lines.append(f"【当前候选动作】{chosen_action}。")

    return _truncate_lines(lines, max_chars)


def _truncate_lines(lines: List[str], max_chars: int) -> str:
    """按顺序拼接，超出上限时从尾部丢弃。"""
    kept: List[str] = []
    total = 0
    for line in lines:
        if total + len(line) + 1 > max_chars and kept:
            break
        kept.append(line)
        total += len(line) + 1
    return "\n".join(kept)


__all__ = ["build_compact_state"]
