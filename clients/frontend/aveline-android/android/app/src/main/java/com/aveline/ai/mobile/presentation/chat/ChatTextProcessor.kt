package com.aveline.ai.mobile.presentation.chat

import com.aveline.ai.mobile.utils.text.ReplySegmenter

/**
 * 文本处理工具（薄壳）：把 AI 回复切成"正文段 / 括号内撤回段"。
 *
 * 断句与括号判定都不在本文件：
 * - 断句走 `utils/text/TextSegmenter`（QQ 端 `core/utils/text_segmenter.py` 的 Kotlin 等价实现）；
 * - "哪一段算括号内容"走 `utils/text/ReplySegmenter`（聊天页唯一口径）。
 *
 * 本文件只做类型适配，避免这里再养出第二套括号正则 —— 历史上正是因为有三套
 * （本文件的正则、`ChatFlushManager` 的括号计数、`MessageBubble` 的首尾字符判断），
 * 同一条回复才会一半居中一半靠左。
 */
object ChatTextProcessor {

    /** 单个分段：文本内容 + 是否为括号内撤回段 */
    data class TextSegment(val text: String, val isRetraction: Boolean)

    /**
     * 智能分段：剥时间戳 → 按 Markdown 结构分组 → 括号内标成撤回段、括号外按断句规则切分。
     *
     * @param text 原始文本
     * @return 分段列表，空文本返回空列表
     */
    fun smartSegmentText(text: String): List<TextSegment> {
        if (text.isBlank()) return emptyList()
        return ReplySegmenter.segment(text).map { segment ->
            TextSegment(segment.text, segment.isStageDirection)
        }
    }
}
