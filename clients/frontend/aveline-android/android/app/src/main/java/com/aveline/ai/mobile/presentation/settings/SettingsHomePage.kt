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
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.domain.models.EmotionType
import com.aveline.ai.mobile.domain.models.PluginSettings
import com.aveline.ai.mobile.presentation.components.ModuleHeader
import com.aveline.ai.mobile.presentation.theme.Danger
import com.aveline.ai.mobile.presentation.theme.EmotionPalette
import com.aveline.ai.mobile.presentation.theme.LifeHealth
import com.aveline.ai.mobile.presentation.theme.Sand
import com.aveline.ai.mobile.presentation.theme.Surface
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 设置首页：连接状态一张小卡 + 分组列表。
 *
 * 这里不再有 SectionCard 与图标：开关直接作为行尾控件，复杂项点进二级页。
 */
@Composable
internal fun SettingsHomePage(
    state: SettingsUiState,
    deviceStatus: DevicePermissionStatus,
    pluginSettings: PluginSettings,
    onOpenNetwork: () -> Unit,
    onToggleAutoTts: (Boolean) -> Unit,
    onToggleStageDirection: (Boolean) -> Unit,
    onToggleAutoEmotion: () -> Unit,
    onOpenEmotionSelector: () -> Unit,
    onOpenUsageStatsSettings: () -> Unit,
    onOpenNotificationSettings: () -> Unit,
    onOpenAccessibilityWizard: () -> Unit,
    onOpenShizukuWizard: () -> Unit,
    onToggleContextSync: (Boolean) -> Unit,
    onToggleResidentMode: (Boolean) -> Unit,
    onOpenDeveloperTools: () -> Unit,
    onShowClearConfirm: () -> Unit,
    onDismissClearError: () -> Unit,
    modifier: Modifier = Modifier
) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .statusBarsPadding()
    ) {
        ModuleHeader(title = "设置")

        Column(
            modifier = Modifier
                .weight(1f)
                .verticalScroll(rememberScrollState())
                .navigationBarsPadding()
                .padding(horizontal = 20.dp)
        ) {
            Spacer(modifier = Modifier.height(4.dp))
            ConnectionStatusCard(state = state, onClick = onOpenNetwork)

            SettingsSectionHeader("对话")
            SettingsSwitchRow(
                title = "语音播报",
                subtitle = "收到回复自动朗读；音色在角色资料里设",
                checked = state.autoTtsEnabled,
                onCheckedChange = onToggleAutoTts
            )
            SettingsSwitchRow(
                title = "动作描写",
                subtitle = if (state.stageDirectionEnabled) {
                    "括号里的内容显示为居中旁白"
                } else {
                    "括号按原文显示"
                },
                checked = state.stageDirectionEnabled,
                onCheckedChange = onToggleStageDirection
            )

            SettingsSectionHeader("情绪与呼吸灯")
            SettingsSwitchRow(
                title = "自动情绪",
                subtitle = if (pluginSettings.autoEmotion) {
                    "呼吸灯跟着后端情绪变化"
                } else {
                    "使用下面的手动情绪"
                },
                checked = pluginSettings.autoEmotion,
                onCheckedChange = { onToggleAutoEmotion() }
            )
            ManualEmotionRow(
                settings = pluginSettings,
                onClick = onOpenEmotionSelector
            )

            val missingPermissions = listOf(
                state.hasUsageStatsPermission,
                state.hasNotificationPermission,
                deviceStatus.accessibilityReady,
                deviceStatus.shizukuReady
            ).count { !it }
            SettingsSectionHeader(
                title = "权限",
                status = if (missingPermissions > 0) {
                    "$missingPermissions 项未授予"
                } else {
                    "已全部授予"
                },
                statusColor = if (missingPermissions > 0) Sand else TextTertiary
            )
            SettingsNavRow(
                title = "使用情况访问",
                subtitle = "感知你在用哪些应用",
                value = if (state.hasUsageStatsPermission) "已授权" else "去授权",
                valueColor = permissionStateColor(!state.hasUsageStatsPermission),
                onClick = onOpenUsageStatsSettings
            )
            SettingsNavRow(
                title = "通知访问",
                subtitle = "主动提醒需要",
                value = if (state.hasNotificationPermission) "已授权" else "去授权",
                valueColor = permissionStateColor(!state.hasNotificationPermission),
                onClick = onOpenNotificationSettings
            )
            SettingsNavRow(
                title = "无障碍服务",
                subtitle = "点击、滑动等自动操作",
                value = if (deviceStatus.accessibilityReady) "已开启" else "去开启",
                valueColor = permissionStateColor(!deviceStatus.accessibilityReady),
                onClick = onOpenAccessibilityWizard
            )
            SettingsNavRow(
                title = "Shizuku",
                subtitle = "强制停止应用、截屏",
                value = if (deviceStatus.shizukuReady) {
                    "已就绪"
                } else {
                    "${deviceStatus.shizukuStepsDone} / 3 步"
                },
                valueColor = if (deviceStatus.shizukuReady) TextTertiary else TextSecondary,
                onClick = onOpenShizukuWizard
            )

            SettingsSectionHeader("隐私")
            SettingsSwitchRow(
                title = "上下文同步",
                subtitle = "把设备上下文和活动数据同步到后端",
                checked = state.isContextSyncEnabled,
                onCheckedChange = onToggleContextSync
            )
            SettingsSwitchRow(
                title = "常驻模式",
                subtitle = "后台保持运行以接收消息；需加入电池白名单",
                checked = state.residentModeEnabled,
                onCheckedChange = onToggleResidentMode
            )

            SettingsSectionHeader("数据与其他")
            SettingsNavRow(
                title = "开发者工具",
                value = "系统资源",
                onClick = onOpenDeveloperTools
            )
            SettingsDangerRow(
                title = "清除本地聊天记录",
                onClick = onShowClearConfirm
            )
            SettingsNavRow(
                title = "版本",
                value = "${state.appVersion} (${state.buildVersion})",
                valueMono = true,
                showChevron = false
            )

            state.clearError?.let { error ->
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = "$error · 点击关闭",
                    fontSize = 12.5.sp,
                    lineHeight = 18.sp,
                    color = Danger,
                    modifier = Modifier.clickable(onClick = onDismissClearError)
                )
            }

            Spacer(modifier = Modifier.height(32.dp))
        }
    }
}

@Composable
private fun ConnectionStatusCard(
    state: SettingsUiState,
    onClick: () -> Unit
) {
    val hasAddress = state.activeUrl.isNotBlank()
    val reachable = state.activeReachable
    val title = when {
        !hasAddress -> "未连接"
        !reachable -> "都连不上"
        else -> "已连接 · ${state.activeChannel}"
    }
    val dotColor = when {
        !hasAddress -> TextTertiary
        reachable -> LifeHealth
        else -> Danger
    }
    val background = if (hasAddress && !reachable) {
        Danger.copy(alpha = 0.08f)
    } else {
        Surface
    }
    val border = if (hasAddress && !reachable) {
        Danger.copy(alpha = 0.3f)
    } else {
        Color.White.copy(alpha = 0.08f)
    }

    Box(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 20.dp)
            .clip(RoundedCornerShape(16.dp))
            .background(background)
            .border(1.dp, border, RoundedCornerShape(16.dp))
            .clickable(onClick = onClick)
            .defaultMinSize(minHeight = 70.dp)
            .padding(horizontal = 16.dp, vertical = 14.dp)
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Box(
                        modifier = Modifier
                            .size(7.dp)
                            .clip(RoundedCornerShape(4.dp))
                            .background(dotColor)
                    )
                    Text(
                        text = title,
                        fontSize = 15.5.sp,
                        lineHeight = 21.sp,
                        fontWeight = FontWeight.Medium,
                        color = TextPrimary
                    )
                }
                Spacer(modifier = Modifier.height(3.dp))
                Text(
                    text = connectionSubtitle(state, hasAddress, reachable),
                    style = if (hasAddress && reachable) {
                        settingsMonoStyle(size = 11, color = TextTertiary)
                    } else {
                        SettingsSubtitleStyle.copy(color = TextSecondary)
                    },
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
            }
            Spacer(modifier = Modifier.width(12.dp))
            Icon(
                imageVector = Icons.Default.ChevronRight,
                contentDescription = null,
                tint = TextTertiary,
                modifier = Modifier.size(20.dp)
            )
        }
    }
}

private fun connectionSubtitle(
    state: SettingsUiState,
    hasAddress: Boolean,
    reachable: Boolean
): String = when {
    !hasAddress -> "点进网络页填写局域网、组网或公网域名"
    !reachable -> "局域网地址只在家里的 WiFi 下有效。用流量或在外面时，需要填组网地址或公网域名。"
    else -> buildString {
        append(state.activeAddress)
        state.activeLatencyMs?.let { append(" · ${it}ms") }
    }
}

@Composable
private fun ManualEmotionRow(
    settings: PluginSettings,
    onClick: () -> Unit
) {
    val emotion = settings.manualEmotion ?: EmotionType.NEUTRAL
    SettingsNavRow(
        title = "手动情绪",
        dimmed = settings.autoEmotion,
        onClick = onClick,
        valueContent = {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                SettingsValueDot(EmotionPalette.of(emotion.name.lowercase()))
                Text(
                    text = emotion.label,
                    fontSize = 14.sp,
                    lineHeight = 19.sp,
                    color = TextSecondary
                )
            }
        }
    )
}
