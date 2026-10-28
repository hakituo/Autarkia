package com.aveline.ai.mobile.presentation.companion.memory

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/** 切换器外框：10% 白描边，2dp 内边距刚好让选中块不贴边 */
private val SwitcherBorder = Color(0x1AFFFFFF)

/** 选中块的底色：比页面背景亮一档，不带任何彩色 */
private val SwitcherSelected = Color(0xFF232325)

/**
 * 记忆页的三种视图。
 *
 * - [CONVERSATION]：完整聊天记录树（含重新生成 / 编辑产生的平行分支）
 * - [WEIGHTED]：后端加权记忆（按时间 / 话题归组）
 * - [GRAPH]：记忆网络（地标 → 邻域，按关系扩散而不是按时间分桶）
 */
enum class MemoryViewMode {
    CONVERSATION,
    WEIGHTED,
    GRAPH
}

/**
 * 顶部模式切换：分段按钮，点一下即可切换，不做页面跳转。
 *
 * 去掉了三个图标（列表 / 星 / 分享）：三个词本身就是最准确的标签，
 * 图标只是把 32dp 高的点击区挤得更满。
 */
@Composable
internal fun MemoryViewModeSwitcher(
    mode: MemoryViewMode,
    onModeChange: (MemoryViewMode) -> Unit,
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .border(BorderStroke(1.dp, SwitcherBorder), RoundedCornerShape(12.dp))
            .padding(2.dp),
        horizontalArrangement = Arrangement.spacedBy(2.dp)
    ) {
        ModeSegment(
            label = "聊天树",
            selected = mode == MemoryViewMode.CONVERSATION,
            onClick = { onModeChange(MemoryViewMode.CONVERSATION) }
        )
        ModeSegment(
            label = "加权记忆",
            selected = mode == MemoryViewMode.WEIGHTED,
            onClick = { onModeChange(MemoryViewMode.WEIGHTED) }
        )
        ModeSegment(
            label = "记忆网络",
            selected = mode == MemoryViewMode.GRAPH,
            onClick = { onModeChange(MemoryViewMode.GRAPH) }
        )
    }
}

@Composable
private fun RowScope.ModeSegment(
    label: String,
    selected: Boolean,
    onClick: () -> Unit
) {
    Box(
        modifier = Modifier
            .weight(1f)
            .height(32.dp)
            .clip(RoundedCornerShape(10.dp))
            .background(if (selected) SwitcherSelected else Color.Transparent)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.labelMedium.copy(fontSize = 13.sp),
            color = if (selected) TextPrimary else TextTertiary,
            fontWeight = if (selected) FontWeight.Medium else FontWeight.Normal,
            maxLines = 1
        )
    }
}
