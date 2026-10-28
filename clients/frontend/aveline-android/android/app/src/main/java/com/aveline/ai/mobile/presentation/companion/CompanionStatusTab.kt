package com.aveline.ai.mobile.presentation.companion

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.aveline.ai.mobile.domain.models.Emotion
import com.aveline.ai.mobile.presentation.status.ui.StatusUiState
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.Danger
import com.aveline.ai.mobile.presentation.theme.Line
import com.aveline.ai.mobile.presentation.theme.Sand
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import kotlinx.coroutines.flow.StateFlow

/** 分段情绪条由亮到暗的四档灰阶（设计稿用同色系渐变代替多色糖果条） */
private val EmotionRamp = listOf(
    TextPrimary,
    TextSecondary,
    Color(0xFF5C5B57),
    Color(0xFF3A3A3C)
)

/**
 * Companion 状态 Tab。
 *
 * 三块内容，都没有卡片外壳：生命状态四条细线、情绪一句话 + 分段灰阶条、
 * 页底一行连接状态。原来四张 SectionCard 的标题和副标题（「WebSocket 连接状态」
 * 这类开发视角的说明）全部去掉，信息本身一个没少。
 *
 * @param uiState 状态页 UI 状态
 * @param clockFlow 系统时钟流（只在页底那一行订阅，避免每秒把整页重组）
 * @param onRefresh 刷新 / 重试回调
 */
@Composable
fun CompanionStatusTab(
    uiState: StatusUiState,
    clockFlow: StateFlow<String>,
    onRefresh: () -> Unit
) {
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = CompanionGutter),
        contentPadding = PaddingValues(top = 22.dp, bottom = 24.dp)
    ) {
        uiState.error?.takeIf { it.isNotBlank() }?.let { message ->
            item(key = "status-error") {
                ErrorBanner(message = message, onRetry = onRefresh)
                Spacer(modifier = Modifier.height(20.dp))
            }
        }

        item(key = "life-status") {
            LifeStatusBlock(uiState)
        }

        item(key = "emotion") {
            EmotionBlock(emotion = uiState.emotion, mix = uiState.emotionMix)
        }

        item(key = "connection") {
            ConnectionLine(
                connected = uiState.connected,
                clockFlow = clockFlow,
                onRetry = onRefresh
            )
        }
    }
}

/**
 * 错误提示横幅,带重试按钮。
 */
@Composable
private fun ErrorBanner(
    message: String,
    onRetry: () -> Unit
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = Danger.copy(alpha = 0.1f),
        shape = RoundedCornerShape(12.dp)
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Icon(
                imageVector = Icons.Default.Warning,
                contentDescription = null,
                tint = Danger,
                modifier = Modifier.size(20.dp)
            )
            Text(
                text = message,
                style = MaterialTheme.typography.bodySmall,
                color = Danger,
                modifier = Modifier.weight(1f)
            )
            Button(
                onClick = onRetry,
                colors = ButtonDefaults.buttonColors(
                    containerColor = Danger.copy(alpha = 0.2f),
                    contentColor = Danger
                ),
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 4.dp)
            ) {
                Icon(
                    Icons.Default.Refresh,
                    contentDescription = "重试",
                    modifier = Modifier.size(16.dp)
                )
                Spacer(modifier = Modifier.width(4.dp))
                Text("重试", style = MaterialTheme.typography.labelMedium)
            }
        }
    }
}

/** 生命状态：四条 3dp 细线，任何一种低于 30% 时数字和线一起变沙金 */
@Composable
private fun LifeStatusBlock(uiState: StatusUiState) {
    if (uiState.isLoading && uiState.lifeStatus == null) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 32.dp),
            contentAlignment = Alignment.Center
        ) {
            CircularProgressIndicator(color = Accent, modifier = Modifier.size(22.dp), strokeWidth = 2.dp)
        }
        return
    }

    Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
        LifeMetricRow(label = "健康", value = uiState.lifeStatus?.health ?: 0f)
        LifeMetricRow(label = "饥饿", value = uiState.lifeStatus?.hunger ?: 0f)
        LifeMetricRow(label = "幸福", value = uiState.lifeStatus?.happiness ?: 0f)
        LifeMetricRow(label = "能量", value = uiState.lifeStatus?.energy ?: 0f)
    }
}

@Composable
private fun LifeMetricRow(label: String, value: Float) {
    val fraction = value.coerceIn(0f, 1f)
    val percent = (fraction * 100).toInt()
    val ink = if (percent < CompanionLowStatusPercent) Sand else TextPrimary

    Column(verticalArrangement = Arrangement.spacedBy(7.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = label,
                style = MaterialTheme.typography.bodyMedium.copy(fontSize = 14.sp),
                color = TextSecondary
            )
            Text(
                text = "$percent%",
                style = MaterialTheme.typography.bodyMedium.copy(
                    fontSize = 14.sp,
                    fontWeight = FontWeight.Medium,
                    fontFeatureSettings = "tnum"
                ),
                color = ink
            )
        }
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(3.dp)
                .clip(RoundedCornerShape(2.dp))
                .background(Color.White.copy(alpha = 0.08f))
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth(fraction)
                    .fillMaxHeight()
                    .background(ink)
            )
        }
    }
}

/** 情绪的分段：一条灰阶条最多四段，按占比从亮到暗 */
private data class EmotionSegment(val label: String, val ratio: Float, val color: Color)

/**
 * 情绪：一句话 + 一条分段灰阶条 + 百分比。
 *
 * 原来的做法是主情绪一条进度条，混合比例再来 N 条——同一个信息被画了两次，
 * 而且用了整套高饱和情绪色。这里合成一条，颜色只表示「占比从高到低」。
 */
@Composable
private fun EmotionBlock(emotion: Emotion, mix: Map<String, Float>) {
    val segments = remember(emotion, mix) { buildEmotionSegments(emotion, mix) }

    Column {
        HorizontalDivider(color = Line, thickness = 1.dp)
        Spacer(modifier = Modifier.height(16.dp))

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.Bottom
        ) {
            Text(
                text = "情绪",
                style = MaterialTheme.typography.labelMedium,
                color = TextTertiary
            )
            Text(
                text = emotionSummary(emotion, mix),
                style = MaterialTheme.typography.bodyLarge.copy(
                    fontSize = 15.sp,
                    fontWeight = FontWeight.Medium
                ),
                color = TextPrimary
            )
        }

        Spacer(modifier = Modifier.height(12.dp))

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(6.dp)
                .clip(RoundedCornerShape(3.dp)),
            horizontalArrangement = Arrangement.spacedBy(2.dp)
        ) {
            segments.forEach { segment ->
                EmotionSegmentBar(segment)
            }
        }

        Spacer(modifier = Modifier.height(10.dp))

        Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            segments.forEach { segment ->
                Text(
                    text = "${segment.label} ${(segment.ratio * 100).toInt()}%",
                    style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.5.sp),
                    color = TextTertiary,
                    maxLines = 1
                )
            }
        }
    }
}

@Composable
private fun RowScope.EmotionSegmentBar(segment: EmotionSegment) {
    Box(
        modifier = Modifier
            .weight(segment.ratio.coerceAtLeast(0.02f))
            .fillMaxHeight()
            .background(segment.color)
    )
}

private fun buildEmotionSegments(emotion: Emotion, mix: Map<String, Float>): List<EmotionSegment> {
    val ordered = mix.entries
        .filter { it.value > 0.02f }
        .sortedByDescending { it.value }
        .take(EmotionRamp.size)
    if (ordered.isEmpty()) {
        return listOf(
            EmotionSegment(
                label = companionEmotionLabel(emotion.primary),
                ratio = emotion.intensity.coerceIn(0.05f, 1f),
                color = TextPrimary
            )
        )
    }
    return ordered.mapIndexed { index, entry ->
        EmotionSegment(
            label = companionEmotionLabel(entry.key),
            ratio = entry.value.coerceIn(0.02f, 1f),
            color = EmotionRamp[index]
        )
    }
}

/** 「平静，带一点想念」：主情绪 + 占比够高的次情绪拼成一句话 */
private fun emotionSummary(emotion: Emotion, mix: Map<String, Float>): String {
    val primary = companionEmotionLabel(emotion.primary)
    val secondary = mix.entries
        .filter { !it.key.equals(emotion.primary, ignoreCase = true) && it.value >= 0.15f }
        .maxByOrNull { it.value }
        ?: return primary
    return "$primary，带一点${companionEmotionLabel(secondary.key)}"
}

/**
 * 连接状态：页底一行小字。
 *
 * 原来是一整张「WebSocket 连接状态」卡；连接正常时它不该占任何视觉重量，
 * 所以压到页底，断线才变危险色并给出重试。
 */
@Composable
private fun ConnectionLine(
    connected: Boolean,
    clockFlow: StateFlow<String>,
    onRetry: () -> Unit
) {
    val clock by clockFlow.collectAsStateWithLifecycle()
    val ink = if (connected) TextTertiary else Danger

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 24.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Box(
            modifier = Modifier
                .size(5.dp)
                .clip(CircleShape)
                .background(if (connected) Accent else Danger)
        )
        Spacer(modifier = Modifier.width(6.dp))
        Text(
            text = if (connected) "已连接" else "未连接",
            style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp),
            color = ink
        )
        if (!connected) {
            Text(
                text = " · 重试",
                style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp),
                color = Danger,
                modifier = Modifier
                    .clickable(onClick = onRetry)
                    .padding(vertical = 2.dp)
            )
        }
        Spacer(modifier = Modifier.weight(1f))
        Text(
            text = clock.ifBlank { "--:--:--" },
            style = MaterialTheme.typography.bodySmall.copy(
                fontSize = 11.5.sp,
                fontFeatureSettings = "tnum"
            ),
            color = TextTertiary.copy(alpha = 0.7f)
        )
    }
}
