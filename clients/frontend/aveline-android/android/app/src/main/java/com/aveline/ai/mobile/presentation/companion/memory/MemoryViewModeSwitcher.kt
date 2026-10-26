package com.aveline.ai.mobile.presentation.companion.memory

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.Share
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.TextSecondary

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
            .clip(RoundedCornerShape(10.dp))
            .background(Color(0x1A000000))
            .padding(3.dp),
        horizontalArrangement = Arrangement.spacedBy(3.dp)
    ) {
        ModeSegment(
            label = "聊天树",
            icon = Icons.AutoMirrored.Filled.List,
            selected = mode == MemoryViewMode.CONVERSATION,
            modifier = Modifier.weight(1f),
            onClick = { onModeChange(MemoryViewMode.CONVERSATION) }
        )
        ModeSegment(
            label = "加权记忆",
            icon = Icons.Default.Star,
            selected = mode == MemoryViewMode.WEIGHTED,
            modifier = Modifier.weight(1f),
            onClick = { onModeChange(MemoryViewMode.WEIGHTED) }
        )
        ModeSegment(
            label = "记忆网络",
            icon = Icons.Default.Share,
            selected = mode == MemoryViewMode.GRAPH,
            modifier = Modifier.weight(1f),
            onClick = { onModeChange(MemoryViewMode.GRAPH) }
        )
    }
}

@Composable
private fun ModeSegment(
    label: String,
    icon: ImageVector,
    selected: Boolean,
    modifier: Modifier = Modifier,
    onClick: () -> Unit
) {
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(8.dp))
            .background(if (selected) Accent.copy(alpha = 0.18f) else Color.Transparent)
            .clickable(onClick = onClick)
            .padding(vertical = 8.dp),
        contentAlignment = Alignment.Center
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = if (selected) Accent else TextSecondary,
                modifier = Modifier.size(16.dp)
            )
            Spacer(modifier = Modifier.size(5.dp))
            Text(
                text = label,
                style = MaterialTheme.typography.labelLarge,
                color = if (selected) Accent else TextSecondary,
                fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal
            )
        }
    }
}
