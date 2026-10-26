package com.aveline.ai.mobile.presentation.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.components.controls.AvelineButton
import com.aveline.ai.mobile.presentation.components.controls.AvelineButtonVariant
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.Background
import com.aveline.ai.mobile.presentation.theme.Edge
import com.aveline.ai.mobile.presentation.theme.Line
import com.aveline.ai.mobile.presentation.theme.Sand
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

internal enum class PermissionWizardKind {
    ACCESSIBILITY,
    SHIZUKU
}

private data class WizardStep(
    val title: String,
    val detail: String,
    val done: Boolean,
    val actionLabel: String? = null,
    val action: (() -> Unit)? = null
)

/**
 * 权限向导：垂直步骤条，只有「当前这一步」才给按钮。
 *
 * 之前是把所有按钮同时铺在卡片里，用户不知道该先点哪个；现在按已完成 / 当前 / 待办
 * 三级区分，已完成打勾、待办压暗，当前步才展开操作。
 */
@Composable
internal fun SettingsPermissionWizard(
    kind: PermissionWizardKind,
    status: DevicePermissionStatus,
    onBack: () -> Unit,
    onRefresh: () -> Unit,
    modifier: Modifier = Modifier
) {
    val context = LocalContext.current
    val steps = when (kind) {
        PermissionWizardKind.ACCESSIBILITY -> accessibilitySteps(status) {
            DevicePermissionActions.openAccessibilitySettings(context)
        }
        PermissionWizardKind.SHIZUKU -> shizukuSteps(
            status = status,
            openMarket = { DevicePermissionActions.openShizukuMarket(context) },
            openShizuku = { DevicePermissionActions.launchShizukuApp(context) },
            requestPermission = { DevicePermissionActions.requestShizukuPermission() }
        )
    }
    val ready = steps.all { it.done }
    val currentIndex = steps.indexOfFirst { !it.done }
    val title = when (kind) {
        PermissionWizardKind.ACCESSIBILITY -> "无障碍服务"
        PermissionWizardKind.SHIZUKU -> "Shizuku"
    }
    val subtitle = when (kind) {
        PermissionWizardKind.ACCESSIBILITY -> "用于点击、滑动等自动操作"
        PermissionWizardKind.SHIZUKU -> "用于强制停止应用、截屏等高级操作"
    }

    Column(
        modifier = modifier
            .fillMaxSize()
            .statusBarsPadding()
    ) {
        SettingsSubPageHeader(title = title, subtitle = subtitle, onBack = onBack)

        Column(
            modifier = Modifier
                .weight(1f)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp)
        ) {
            Spacer(modifier = Modifier.height(20.dp))
            WizardStatusLine(ready = ready, remaining = steps.count { !it.done })
            Spacer(modifier = Modifier.height(24.dp))

            steps.forEachIndexed { index, step ->
                WizardStepRow(
                    index = index,
                    step = step,
                    isCurrent = index == currentIndex,
                    isLast = index == steps.lastIndex
                )
            }

            if (ready) {
                Spacer(modifier = Modifier.height(20.dp))
                Text(
                    text = "已全部完成，相关功能可以直接使用。",
                    fontSize = 12.5.sp,
                    lineHeight = 18.sp,
                    color = TextSecondary
                )
            }

            Spacer(modifier = Modifier.height(28.dp))
        }

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .navigationBarsPadding()
                .padding(horizontal = 20.dp, vertical = 12.dp)
        ) {
            AvelineButton(
                text = "我已操作，重新检测",
                onClick = onRefresh,
                modifier = Modifier.fillMaxWidth(),
                variant = AvelineButtonVariant.Primary
            )
        }
    }
}

private fun accessibilitySteps(
    status: DevicePermissionStatus,
    openSettings: () -> Unit
): List<WizardStep> = listOf(
    WizardStep(
        title = "打开系统无障碍设置",
        detail = "系统设置 → 无障碍 → 已下载的应用",
        done = status.accessibilityReady,
        actionLabel = "去系统设置",
        action = openSettings
    ),
    WizardStep(
        title = "启用 Aveline 服务",
        detail = when {
            status.accessibilityRunning -> "服务已连接，自动操作可用"
            status.accessibilityEnabledInSystem -> "系统已启用，正在等待服务连接；若一直未连接，请关掉再打开一次"
            else -> "在列表里找到 Aveline 并打开开关"
        },
        done = status.accessibilityRunning,
        actionLabel = "去检查",
        action = openSettings
    )
)

private fun shizukuSteps(
    status: DevicePermissionStatus,
    openMarket: () -> Unit,
    openShizuku: () -> Unit,
    requestPermission: () -> Unit
): List<WizardStep> = listOf(
    WizardStep(
        title = "安装 Shizuku",
        detail = "在应用市场安装 Shizuku（moe.shizuku.privileged.api）",
        done = status.shizuku != ShizukuState.NOT_INSTALLED,
        actionLabel = "去安装",
        action = openMarket
    ),
    WizardStep(
        title = "启动 Shizuku 服务",
        detail = when (status.shizuku) {
            ShizukuState.NOT_INSTALLED -> "先完成上一步"
            ShizukuState.NOT_RUNNING -> "打开 Shizuku 应用，点「启动」按钮"
            else -> "服务已在运行"
        },
        done = status.shizuku == ShizukuState.NOT_AUTHORIZED ||
            status.shizuku == ShizukuState.AUTHORIZED,
        actionLabel = "打开 Shizuku",
        action = openShizuku
    ),
    WizardStep(
        title = "授权 Aveline",
        detail = when (status.shizuku) {
            ShizukuState.AUTHORIZED -> "已授权，高级设备控制可用"
            ShizukuState.NOT_AUTHORIZED -> "在系统弹窗里选择「允许」"
            else -> "先完成前面的步骤"
        },
        done = status.shizuku == ShizukuState.AUTHORIZED,
        actionLabel = "请求授权",
        action = requestPermission
    )
)

@Composable
private fun WizardStatusLine(ready: Boolean, remaining: Int) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Box(
            modifier = Modifier
                .size(7.dp)
                .clip(CircleShape)
                .background(if (ready) Accent else Sand)
        )
        Text(
            text = if (ready) "已就绪" else "还差 $remaining 步",
            fontSize = 13.5.sp,
            lineHeight = 19.sp,
            color = if (ready) Accent else Sand
        )
    }
}

@Composable
private fun WizardStepRow(
    index: Int,
    step: WizardStep,
    isCurrent: Boolean,
    isLast: Boolean
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(IntrinsicSize.Min)
    ) {
        Column(
            modifier = Modifier
                .width(28.dp)
                .fillMaxHeight(),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            WizardStepCircle(number = index + 1, done = step.done, current = isCurrent)
            if (!isLast) {
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .width(1.dp)
                        .background(Line)
                )
            }
        }
        Column(
            modifier = Modifier
                .weight(1f)
                .padding(start = 10.dp, bottom = if (isLast) 0.dp else 24.dp)
        ) {
            Text(
                text = step.title,
                fontSize = 15.5.sp,
                lineHeight = 21.sp,
                color = when {
                    step.done -> TextSecondary
                    isCurrent -> TextPrimary
                    else -> TextTertiary
                }
            )
            Spacer(modifier = Modifier.height(2.dp))
            Text(
                text = step.detail,
                fontSize = 12.5.sp,
                lineHeight = 18.sp,
                color = if (isCurrent) TextSecondary else TextTertiary
            )
            val actionLabel = step.actionLabel
            val action = step.action
            if (isCurrent && actionLabel != null && action != null) {
                Spacer(modifier = Modifier.height(12.dp))
                AvelineButton(
                    text = actionLabel,
                    onClick = action,
                    variant = AvelineButtonVariant.Secondary
                )
            }
        }
    }
}

@Composable
private fun WizardStepCircle(number: Int, done: Boolean, current: Boolean) {
    val background = if (done) Accent else Color.Transparent
    val border = when {
        done -> Accent
        current -> Accent
        else -> Edge
    }
    Box(
        modifier = Modifier
            .size(24.dp)
            .clip(CircleShape)
            .background(background)
            .border(1.dp, border, CircleShape),
        contentAlignment = Alignment.Center
    ) {
        if (done) {
            Icon(
                imageVector = Icons.Default.Check,
                contentDescription = "已完成",
                tint = Background,
                modifier = Modifier.size(14.dp)
            )
        } else {
            Text(
                text = number.toString(),
                style = settingsMonoStyle(
                    size = 11,
                    color = if (current) Accent else TextTertiary
                )
            )
        }
    }
}
