package com.aveline.ai.mobile.presentation.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.services.endpoint.resolver.EndpointCandidateProbe
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.Danger
import com.aveline.ai.mobile.presentation.theme.Edge
import com.aveline.ai.mobile.presentation.theme.LifeHealth
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 网络页的一条候选地址：序号 / 名称 / 地址 / 当前网络下的探测结论。
 *
 * 结论来自 [SettingsUiState.candidateProbes]，不缓存跨网络的旧结果；探测中保留
 * 「探测中…」，避免点进页面时三条都短暂显示「待探测」。
 */
@Composable
internal fun CandidateRow(
    slot: SettingsAddressSlot,
    url: String,
    state: SettingsUiState,
    onClick: () -> Unit
) {
    val probe = state.candidateProbes.firstOrNull { sameAddress(it.url, url) }
    val active = url.isNotBlank() && sameAddress(url, state.activeUrl)
    val statusText = candidateStatusText(url, probe, state.isProbingCandidates)
    val statusColor = candidateStatusColor(active, url, probe, state.isProbingCandidates)

    SettingsRowDivider()
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .defaultMinSize(minHeight = 64.dp)
            .padding(vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Box(
            modifier = Modifier
                .size(22.dp)
                .clip(CircleShape)
                .border(1.dp, if (active) Accent.copy(alpha = 0.5f) else Edge, CircleShape),
            contentAlignment = Alignment.Center
        ) {
            Text(
                text = slot.number?.toString() ?: "·",
                style = settingsMonoStyle(
                    size = 11,
                    color = if (active) Accent else TextTertiary
                )
            )
        }
        Spacer(modifier = Modifier.width(12.dp))
        Column(modifier = Modifier.weight(1f)) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Text(text = slot.title, style = SettingsTitleStyle)
                if (active) ActiveTag()
            }
            Spacer(modifier = Modifier.height(2.dp))
            Text(
                text = url.ifBlank { "未设置" },
                style = settingsMonoStyle(
                    size = 11,
                    color = if (url.isBlank()) TextTertiary else TextSecondary
                ),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
        }
        Spacer(modifier = Modifier.width(12.dp))
        Text(
            text = statusText,
            fontSize = 12.5.sp,
            lineHeight = 18.sp,
            color = statusColor,
            maxLines = 1
        )
    }
}

private fun candidateStatusText(
    url: String,
    probe: EndpointCandidateProbe?,
    probing: Boolean
): String = when {
    url.isBlank() -> "—"
    probing -> "探测中…"
    probe == null -> "待探测"
    !probe.reachable -> "不可达"
    probe.latencyMs != null -> "可达 · ${probe.latencyMs}ms"
    else -> "可达"
}

private fun candidateStatusColor(
    active: Boolean,
    url: String,
    probe: EndpointCandidateProbe?,
    probing: Boolean
): Color = when {
    url.isBlank() || probing || probe == null -> TextTertiary
    !probe.reachable -> Danger
    active -> Accent
    else -> LifeHealth
}

@Composable
internal fun ActiveTag() {
    Text(
        text = "当前",
        fontSize = 10.5.sp,
        lineHeight = 14.sp,
        color = Accent,
        modifier = Modifier
            .clip(RoundedCornerShape(5.dp))
            .background(Accent.copy(alpha = 0.12f))
            .padding(horizontal = 5.dp, vertical = 1.dp)
    )
}
