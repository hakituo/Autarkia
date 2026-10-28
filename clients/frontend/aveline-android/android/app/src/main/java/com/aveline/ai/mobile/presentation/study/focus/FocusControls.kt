package com.aveline.ai.mobile.presentation.study.focus

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.presentation.theme.Background
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary

/**
 * 专注控制条。
 *
 * M3 的 FilledTonalIconButton ×2 + FilledIconButton 换成两个 52dp 描边圆按钮
 * 加一个 76dp 浅色实心按钮：整页只有一个实心件，和「一屏一个主动作」一致。
 */
@Composable
internal fun FocusControls(
    isRunning: Boolean,
    onToggle: () -> Unit,
    onReset: () -> Unit,
    onSkip: () -> Unit,
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically
    ) {
        CircleAction(
            icon = Icons.Default.Refresh,
            contentDescription = "重置",
            onClick = onReset
        )
        Spacer(modifier = Modifier.width(28.dp))
        Box(
            modifier = Modifier
                .size(76.dp)
                .clip(CircleShape)
                .background(TextPrimary)
                .clickable(onClick = onToggle),
            contentAlignment = Alignment.Center
        ) {
            Icon(
                imageVector = if (isRunning) Icons.Default.Pause else Icons.Default.PlayArrow,
                contentDescription = if (isRunning) "暂停" else "开始",
                tint = Background,
                modifier = Modifier.size(34.dp)
            )
        }
        Spacer(modifier = Modifier.width(28.dp))
        CircleAction(
            icon = Icons.Default.SkipNext,
            contentDescription = "跳过",
            onClick = onSkip
        )
    }
}

@Composable
private fun CircleAction(
    icon: ImageVector,
    contentDescription: String,
    onClick: () -> Unit
) {
    Box(
        modifier = Modifier
            .size(52.dp)
            .clip(CircleShape)
            .border(1.dp, Color(0x24FFFFFF), CircleShape)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center
    ) {
        Icon(
            imageVector = icon,
            contentDescription = contentDescription,
            tint = TextSecondary,
            modifier = Modifier.size(22.dp)
        )
    }
}
