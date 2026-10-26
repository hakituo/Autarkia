package com.aveline.ai.mobile.presentation.adaptive

import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.presentation.navigation.Routes

/** 普通模块页（学习 / 生活 / 设置等）在大屏上的最大内容宽度，避免文字卡片被拉得过长。 */
private val ReadableContentMaxWidth = 900.dp

/**
 * 各路由在大屏上的最大内容宽度。
 *
 * 消息页与聊天页自己处理消息宽度，这里返回 `Dp.Unspecified` 表示不额外限宽；
 * 其余模块页居中限宽，保持可读的行长。
 */
fun readableContentMaxWidth(route: String): Dp = when (route) {
    Routes.CONVERSATIONS, Routes.CHAT -> Dp.Unspecified
    else -> ReadableContentMaxWidth
}
