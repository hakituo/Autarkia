package com.aveline.ai.mobile.presentation.study

/**
 * 把背单词累计秒数格式化成复习页顶部展示的计时文案。
 *
 * - 不足 1 小时：`mm:ss`（如 `04:12`）
 * - 超过 1 小时：`h:mm:ss`（如 `1:03:20`）
 *
 * 分钟固定补零，等宽字体下计时宽度不跳。纯函数，便于单测；不依赖 Android / Compose。
 */
internal fun formatVocabularyElapsed(seconds: Int): String {
    val safe = seconds.coerceAtLeast(0)
    val hours = safe / 3600
    val minutes = (safe % 3600) / 60
    val secs = safe % 60
    if (hours > 0) {
        return "$hours:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}"
    }
    return "${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}"
}
