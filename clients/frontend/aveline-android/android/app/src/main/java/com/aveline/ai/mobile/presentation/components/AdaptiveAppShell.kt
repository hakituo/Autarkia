package com.aveline.ai.mobile.presentation.components

import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/**
 * 应用外壳：平板与手机统一使用可滑动的侧边栏。
 *
 * 右滑从左边拉出、左滑收起；宽度在宽窗口（平板）为窗口三分之一，
 * 窄窗口（手机）保留原来的近全屏抽屉。手势逻辑见 [PullableNavigationDrawer]。
 *
 * @param drawerContent 侧栏内容（纯导航：消息 / 学习 / 生活 / 商城 / 数字健康 / 设置）
 */
@Composable
fun AdaptiveAppShell(
    drawerState: PullableDrawerState,
    onDismissRequest: () -> Unit,
    drawerContent: @Composable () -> Unit,
    content: @Composable () -> Unit
) {
    PullableNavigationDrawer(
        state = drawerState,
        scrimColor = Color(0xCC020617),
        onDismissRequest = onDismissRequest,
        drawerContent = drawerContent,
        content = content
    )
}
