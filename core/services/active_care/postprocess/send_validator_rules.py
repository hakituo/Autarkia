"""发送门硬 Gate 的规则常量（阈值 / 标记词 / 正则 / 豁免集合）。

只放"判定规则数据"，判定流程见 send_validator.py。
"""

import re

# 长消息兜底上限（普通 poke 类型硬上限；超出先压缩一次，仍超就 DROP）
DEFAULT_POKE_MAX_CHARS = 40
# 任何任务类型都不得突破的绝对上限。固定提醒可豁免短消息上限，
# 但不能允许数千字推理过程借“完整传达”之名穿透发送门。
ABSOLUTE_MESSAGE_MAX_CHARS = 1200

# 控制标记 / 内部字段名：正常用户消息里不应出现
_INTERNAL_META_MARKERS = (
    # 内部控制区块
    "[GOODNIGHT_GUARD]",
    "[CONTINUATION_RULE]",
    "[ANTI_SELF_QA]",
    "[ACTIVE_CARE_PROACTIVE_TRIGGER]",
    "[ACTIVE_CARE_CONTEXT_CONTINUATION]",
    "[LAST_ASSISTANT_MESSAGE]",
    "[LAST_USER_MESSAGE]",
    "[TOOL_CALL]",
    # 决策协议字段 / 内部类型名
    "send_active_care",
    "defer_active_care",
    "defer_reason",
    "reason_code",
    "retry_after_seconds",
    "retry_after_minutes",
    "should_send",
    "next_check_seconds",
    "specific_instruction",
    "curious_question",
    "share_thought",
    "planned_topic",
    # 决策过程表述（模型把"不发的理由"当消息发出来）
    "先不发了",
    "先不发",
    "不发了",
    "等他回复",
    "等他回",
    "稍后再看",
    "稍后再说",
    "这轮不适合发",
    "这轮不发",
    "这轮跳过",
    "系统判定",
    "按优先级",
    "冲突检测",
    "我就不打扰",
    "不打扰你",
    "我决定不打扰",
)

# "长铺垫转场词"：prompt 层明令禁止的无意义转场。短 poke 若含这些词又带提问，
# 几乎必然是『报备自己在做什么 → 突然想到 → 追问』的铺垫结构（案例 4），硬拦。
# 只匹配"行首或标点之后"的位置，避免误伤"话说得有点多"这类普通表达。
_PADDED_TRANSITION_RE = re.compile(
    r"(^|[，,。！？!?：:\s])"
    r"(?:话说|对了|刚好|突然想到|刚看到|我刚看到|我刚发现|突然想起来|刚好看到)"
)

# "状态报备前缀"：没有转场词，但句首先自陈"我在/刚做某事"再追问用户。
# 实测案例："在炒菜。你中午一般自己做饭还是点外卖？"——前缀与提问之间只有句号，
# 转场词正则抓不到。形态：（我）在/正在/刚 + 1~8 字活动短语 + 句读标点。
_STATE_REPORT_PREFIX_RE = re.compile(
    r"^(?:我|咱|俺)?(?:正在|刚在|正好在|在|刚)"
    r"[\u4e00-\u9fa5A-Za-z]{1,8}"
    r"[，,。！!、]"
)
# 前缀活动短语里若本身含疑问词，说明前半句是在问对方（"在干嘛，你呢？"），
# 不是状态报备，不得误拦。
_PREFIX_SELF_QUESTION_RE = re.compile(r"[吗嘛么啥怎哪谁]")

# 疑问句特征（用于确认是否在"带铺垫地问用户"）
_INTERROGATIVE_MARKERS = ("？", "?", "吗", "么", "没？", "呢？")


# 短 poke 类型：自由聊天 / 轻量陪伴，需应用"一句话短消息"长度与风格约束。
SHORT_POKE_INTENTS = frozenset({
    "proactive_chat",
    "curious_question",
    "share_thought",
    "emotional_support",
    "gossip_share",
    "weather_complaint",
    "share_peer_chat",
    "planned_topic",
    "checking",
})


# 压缩/长度校验豁免的任务类型：固定任务内容（通知转述/提醒/数字健康等）
# 以"完整准确传达关键信息"为优先，不为凑短丢信息，只做元信息/泄漏硬拦。
POKE_LENGTH_EXEMPT_TYPES = frozenset({
    "reminder",
    "notification_assistant",
    "usage_limit_exceeded",
    "focus_nudge",
    "morning_report",
    "wake_up_greeting",
    "sleep_again_proactive",
    "activity_return_proactive",
    "goodnight_proactive",
    "good_morning_proactive",
    "insomnia",
    "bio_complaint",
    "user_health_reminder",
})

# 风格 gate（长铺垫/状态报备前缀）豁免：活动回归消息允许较长的告别表达，
# 但它同样禁止"报备状态 + 追问用户"（模板已要求不提问），故不豁免风格检查。
POKE_STYLE_EXEMPT_TYPES = frozenset(
    POKE_LENGTH_EXEMPT_TYPES - {"activity_return_proactive"}
)


# 睡眠语境下的唤醒类硬禁短语（Prompt v2：sleep-safe 是 P1 硬约束）
_SLEEP_WAKE_PHRASES = (
    "醒了没", "起床了没", "还在睡吧", "该起了", "该起床了",
    "怎么还不睡", "又熬夜", "你怎么还没醒", "快起来",
)
