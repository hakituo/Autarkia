package com.aveline.ai.mobile.utils.text

/**
 * 聊天文本清洗：时间戳剥离、句尾标点清理。
 *
 * 对应 Python 端 `core/utils/text_segmenter.py` 的
 * `strip_ai_timestamp` / `strip_trailing_punctuation` / `clean_chat_text`，
 * QQ 端与安卓端共用同一套规则。
 */
object TextCleaners {

    /** 整段只由「省略号与空白」构成的判定正则（`……` / `...` / `. . .`）。 */
    private val ELLIPSIS_ONLY_REGEX = Regex("^[\\s.…]+$")

    /**
     * 判断整段是否只由省略号与空白构成（`……` / `...`）。
     *
     * 只由省略号构成的一段**不是**"拖尾标点"，必须保留：断句会把句首的省略号切成
     * 独立一段，若再按拖尾标点清掉，这段就变成空串被丢弃，用户看到的就是
     * "以省略号开头的回复没有省略号"。
     */
    fun isEllipsisOnly(text: String): Boolean {
        val stripped = text.trim()
        if (stripped.isEmpty() || !ELLIPSIS_ONLY_REGEX.matches(stripped)) return false
        // `…` 任意个数都算；ASCII 点要至少 3 个（`.`/`..` 只算普通拖尾标点）
        return stripped.contains('…') || stripped.count { it == '.' } >= 3
    }

    /** 剥离模型模仿历史消息格式输出的时间戳（全局匹配，不只行首）。 */
    fun stripAiTimestamp(text: String): String {
        if (text.isEmpty()) return text
        return TextSegmentRules.AI_TIMESTAMP_REGEX.replace(text, "").trim()
    }

    /**
     * 去除句尾多余标点，让消息结尾更自然：
     * - "。（" → "（"（括号前的句号）
     * - "（xxx。）" → "（xxx）"（括号内部末尾的句号）
     * - "好呀好呀。" → "好呀好呀"、"好呀好呀，" → "好呀好呀"
     *
     * 只清结尾拖尾，句中的逗号/句号保留，不影响语义。
     * **省略号不清**：`…` 不在 [TextSegmentRules.TRAILING_PUNCT_CHARS] 里；
     * 整段只有省略号的（`……` / `...`）直接原样返回。
     */
    fun stripTrailingPunctuation(text: String): String {
        if (text.isEmpty()) return text
        if (isEllipsisOnly(text)) return text.trim()
        var t = TextSegmentRules.PERIOD_BEFORE_BRACKET_REGEX.replace(text, "")
        t = TextSegmentRules.PERIOD_INSIDE_BRACKET_REGEX.replace(t) { m -> m.groupValues[1] }
        t = t.trimEnd { it in TextSegmentRules.TRAILING_PUNCT_CHARS }
        t = t.trim()
        t = TextSegmentRules.TRAILING_DOTS_REGEX.replace(t, "")
        return t.trim()
    }

    /** 展示/发送前的统一清洗：剥时间戳 + 去句尾多余标点。 */
    fun cleanText(text: String): String = stripTrailingPunctuation(stripAiTimestamp(text))
}
