package com.aveline.ai.mobile.presentation.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.components.controls.AvelineButton
import com.aveline.ai.mobile.presentation.components.controls.AvelineButtonVariant
import com.aveline.ai.mobile.presentation.theme.Danger
import com.aveline.ai.mobile.presentation.theme.LifeHealth
import com.aveline.ai.mobile.presentation.theme.Surface
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 网络二级页：状态卡 + 三条自动候选 + 手动锁定 / 访问令牌 + 测试与重探。
 *
 * 每次进入都主动重探一次候选：用户点进网络页通常就是「连不上」，此时旧结果
 * 没有参考价值，先让每一行显示当前网络下的真实状态。
 */
@Composable
internal fun SettingsNetworkScreen(
    state: SettingsUiState,
    onBack: () -> Unit,
    onSaveAddress: (SettingsAddressSlot, String) -> Unit,
    onSaveAccessToken: (String) -> Unit,
    onTestConnection: () -> Unit,
    onReprobeEndpoint: () -> Unit,
    onRefreshCandidates: () -> Unit,
    modifier: Modifier = Modifier
) {
    var editingSlot by remember { mutableStateOf<SettingsAddressSlot?>(null) }
    var editingToken by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) { onRefreshCandidates() }

    Column(
        modifier = modifier
            .fillMaxSize()
            .statusBarsPadding()
    ) {
        SettingsSubPageHeader(
            title = "网络",
            subtitle = "按顺序探测，第一个能连上的生效",
            onBack = onBack
        )

        Column(
            modifier = Modifier
                .weight(1f)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp)
        ) {
            Spacer(modifier = Modifier.height(20.dp))
            NetworkStatusCard(state)

            state.connectionTestResult?.let { result ->
                ConnectionResultLine(result)
            }

            SettingsSectionHeader("候选地址")
            CandidateRow(
                slot = SettingsAddressSlot.LAN,
                url = state.lanUrl,
                state = state,
                onClick = { editingSlot = SettingsAddressSlot.LAN }
            )
            CandidateRow(
                slot = SettingsAddressSlot.VPN,
                url = state.vpnUrl,
                state = state,
                onClick = { editingSlot = SettingsAddressSlot.VPN }
            )
            CandidateRow(
                slot = SettingsAddressSlot.TUNNEL,
                url = state.tunnelUrl,
                state = state,
                onClick = { editingSlot = SettingsAddressSlot.TUNNEL }
            )

            SettingsSectionHeader("其他")
            SettingsNavRow(
                title = "手动锁定",
                subtitle = "填了就固定用它，不再自动切换",
                onClick = { editingSlot = SettingsAddressSlot.MANUAL },
                valueContent = {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        if (state.backendUrl.isNotBlank() &&
                            sameAddress(state.backendUrl, state.activeUrl)
                        ) {
                            ActiveTag()
                        }
                        Text(
                            text = if (state.backendUrl.isBlank()) {
                                "未设置"
                            } else {
                                addressWithoutScheme(state.backendUrl)
                            },
                            style = settingsMonoStyle(
                                size = 12,
                                color = if (state.backendUrl.isBlank()) TextTertiary else TextSecondary
                            ),
                            maxLines = 1
                        )
                    }
                }
            )
            SettingsNavRow(
                title = "访问令牌",
                subtitle = "访问受保护接口时随请求带上",
                value = maskedToken(state.accessToken),
                valueMono = true,
                onClick = { editingToken = true }
            )

            Spacer(modifier = Modifier.height(24.dp))
        }

        NetworkActions(
            isTesting = state.isTestingConnection,
            isReprobing = state.isReprobing,
            onTestConnection = onTestConnection,
            onReprobeEndpoint = onReprobeEndpoint
        )
    }

    editingSlot?.let { slot ->
        SettingsAddressSheet(
            slot = slot,
            currentValue = when (slot) {
                SettingsAddressSlot.LAN -> state.lanUrl
                SettingsAddressSlot.VPN -> state.vpnUrl
                SettingsAddressSlot.TUNNEL -> state.tunnelUrl
                SettingsAddressSlot.MANUAL -> state.backendUrl
            },
            onDismiss = { editingSlot = null },
            onSave = { value ->
                onSaveAddress(slot, value)
                editingSlot = null
            }
        )
    }

    if (editingToken) {
        SettingsTokenSheet(
            currentToken = state.accessToken,
            onDismiss = { editingToken = false },
            onSave = { value ->
                onSaveAccessToken(value)
                editingToken = false
            }
        )
    }
}

@Composable
private fun NetworkStatusCard(state: SettingsUiState) {
    val hasAddress = state.activeUrl.isNotBlank()
    val unreachable = hasAddress && !state.activeReachable
    val shape = RoundedCornerShape(16.dp)
    val background = if (unreachable) Danger.copy(alpha = 0.08f) else Surface
    val border = if (unreachable) Danger.copy(alpha = 0.3f) else Color.White.copy(alpha = 0.08f)

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(shape)
            .background(background)
            .border(1.dp, border, shape)
            .padding(horizontal = 16.dp, vertical = 14.dp)
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Box(
                modifier = Modifier
                    .size(7.dp)
                    .clip(CircleShape)
                    .background(
                        when {
                            !hasAddress -> TextTertiary
                            unreachable -> Danger
                            else -> LifeHealth
                        }
                    )
            )
            Text(
                text = when {
                    !hasAddress -> "未连接"
                    unreachable -> "都连不上"
                    else -> "正在使用 · ${state.activeChannel}"
                },
                fontSize = 15.5.sp,
                lineHeight = 21.sp,
                color = TextPrimary
            )
        }
        Spacer(modifier = Modifier.height(4.dp))
        Text(
            text = when {
                !hasAddress -> "还没有填地址。先填一条局域网、组网或公网域名。"
                unreachable -> "所有候选地址都探不通。局域网地址只在家里的 WiFi 下有效；" +
                    "用流量或在外面时，需要填组网地址或公网域名。"
                else -> buildString {
                    append(state.activeAddress)
                    state.activeLatencyMs?.let { append(" · ${it}ms") }
                }
            },
            style = if (hasAddress && !unreachable) {
                settingsMonoStyle(size = 11, color = TextTertiary)
            } else {
                SettingsSubtitleStyle.copy(color = if (unreachable) Danger else TextSecondary)
            }
        )
    }
}

@Composable
private fun ConnectionResultLine(result: ConnectionTestResult) {
    Spacer(modifier = Modifier.height(10.dp))
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Box(
            modifier = Modifier
                .size(6.dp)
                .clip(CircleShape)
                .background(if (result.success) LifeHealth else Danger)
        )
        Text(
            text = result.message,
            fontSize = 12.5.sp,
            lineHeight = 18.sp,
            color = if (result.success) TextSecondary else Danger
        )
    }
}

@Composable
private fun NetworkActions(
    isTesting: Boolean,
    isReprobing: Boolean,
    onTestConnection: () -> Unit,
    onReprobeEndpoint: () -> Unit
) {
    val busy = isTesting || isReprobing

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .navigationBarsPadding()
            .padding(horizontal = 20.dp, vertical = 12.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        AvelineButton(
            text = "测试连接",
            onClick = onTestConnection,
            modifier = Modifier.weight(1f),
            variant = AvelineButtonVariant.Secondary,
            enabled = !busy,
            loading = isTesting
        )
        AvelineButton(
            text = "重新探测",
            onClick = onReprobeEndpoint,
            modifier = Modifier.weight(1f),
            variant = AvelineButtonVariant.Primary,
            enabled = !busy,
            loading = isReprobing
        )
    }
}
