package com.aveline.ai.mobile.presentation.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.components.controls.AvelineIconButton
import com.aveline.ai.mobile.presentation.components.controls.AvelineSwitch
import com.aveline.ai.mobile.presentation.theme.Danger
import com.aveline.ai.mobile.presentation.theme.Line
import com.aveline.ai.mobile.presentation.theme.Sand
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

internal val SettingsTitleStyle = TextStyle(
    fontSize = 15.5.sp,
    lineHeight = 21.sp,
    color = TextPrimary
)

internal val SettingsSubtitleStyle = TextStyle(
    fontSize = 12.5.sp,
    lineHeight = 17.sp,
    color = TextTertiary
)

internal fun settingsMonoStyle(
    size: Int = 12,
    color: Color = TextTertiary
): TextStyle = TextStyle(
    fontFamily = FontFamily.Monospace,
    fontSize = size.sp,
    lineHeight = (size + 4).sp,
    color = color
)

/** 分组小标题；右侧可带一枚状态（如「1 项未授予」）。 */
@Composable
internal fun SettingsSectionHeader(
    title: String,
    status: String? = null,
    statusColor: Color = Sand
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 24.dp, bottom = 6.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            text = title,
            fontSize = 13.sp,
            lineHeight = 18.sp,
            color = TextTertiary
        )
        if (!status.isNullOrBlank()) {
            Text(
                text = status,
                fontSize = 13.sp,
                lineHeight = 18.sp,
                color = statusColor
            )
        }
    }
}

@Composable
internal fun SettingsRowDivider(color: Color = Line) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(1.dp)
            .background(color)
    )
}

/** 标题 + 一行说明 + 右侧开关；整行可点。 */
@Composable
internal fun SettingsSwitchRow(
    title: String,
    subtitle: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
    enabled: Boolean = true
) {
    SettingsRowDivider()
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .alpha(if (enabled) 1f else 0.4f)
            .clickable(enabled = enabled) { onCheckedChange(!checked) }
            .defaultMinSize(minHeight = 60.dp)
            .padding(vertical = 11.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(text = title, style = SettingsTitleStyle)
            Spacer(modifier = Modifier.height(2.dp))
            Text(text = subtitle, style = SettingsSubtitleStyle)
        }
        Spacer(modifier = Modifier.width(16.dp))
        AvelineSwitch(
            checked = checked,
            onCheckedChange = onCheckedChange,
            enabled = enabled
        )
    }
}

/** 标题 + 说明 + 行尾状态 / 值 + 箭头；用于权限、开发者工具、版本等入口。 */
@Composable
internal fun SettingsNavRow(
    title: String,
    subtitle: String? = null,
    value: String? = null,
    valueColor: Color = TextTertiary,
    valueMono: Boolean = false,
    enabled: Boolean = true,
    /** 置灰但保持可点：自动情绪开启时，手动情绪行仍要能点进去改。 */
    dimmed: Boolean = false,
    showChevron: Boolean = true,
    onClick: (() -> Unit)? = null,
    valueContent: (@Composable RowScope.() -> Unit)? = null
) {
    SettingsRowDivider()
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .alpha(if (dimmed) 0.4f else 1f)
            .then(
                if (onClick != null) {
                    Modifier.clickable(enabled = enabled, onClick = onClick)
                } else {
                    Modifier
                }
            )
            .defaultMinSize(minHeight = 52.dp)
            .padding(vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(text = title, style = SettingsTitleStyle)
            if (!subtitle.isNullOrBlank()) {
                Spacer(modifier = Modifier.height(2.dp))
                Text(text = subtitle, style = SettingsSubtitleStyle)
            }
        }
        Spacer(modifier = Modifier.width(12.dp))
        if (valueContent != null) {
            valueContent()
        } else if (!value.isNullOrBlank()) {
            Text(
                text = value,
                style = if (valueMono) {
                    settingsMonoStyle(size = 12, color = valueColor)
                } else {
                    TextStyle(fontSize = 13.5.sp, lineHeight = 18.sp, color = valueColor)
                },
                maxLines = 1
            )
        }
        if (showChevron && onClick != null) {
            Spacer(modifier = Modifier.width(2.dp))
            Icon(
                imageVector = Icons.Default.ChevronRight,
                contentDescription = null,
                tint = TextTertiary,
                modifier = Modifier.size(18.dp)
            )
        }
    }
}

/** 危险操作行：只有文字是危险色，不带箭头。 */
@Composable
internal fun SettingsDangerRow(
    title: String,
    subtitle: String? = null,
    enabled: Boolean = true,
    onClick: () -> Unit
) {
    SettingsRowDivider()
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .alpha(if (enabled) 1f else 0.4f)
            .clickable(enabled = enabled, onClick = onClick)
            .defaultMinSize(minHeight = 52.dp)
            .padding(vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = title,
                style = SettingsTitleStyle.copy(color = Danger)
            )
            if (!subtitle.isNullOrBlank()) {
                Spacer(modifier = Modifier.height(2.dp))
                Text(text = subtitle, style = SettingsSubtitleStyle)
            }
        }
        Spacer(modifier = Modifier.width(12.dp))
    }
}

@Composable
internal fun SettingsValueDot(color: Color) {
    Box(
        modifier = Modifier
            .size(8.dp)
            .clip(CircleShape)
            .background(color)
    )
}

/** 二级页统一页头：44dp 返回键 + 30sp 标题 + 13sp 说明。 */
@Composable
internal fun SettingsSubPageHeader(
    title: String,
    subtitle: String?,
    onBack: () -> Unit
) {
    Column(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(56.dp)
                .padding(horizontal = 8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            AvelineIconButton(
                icon = Icons.AutoMirrored.Filled.ArrowBack,
                contentDescription = "返回",
                onClick = onBack
            )
        }
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp)
        ) {
            Text(text = title, style = MaterialTheme.typography.displaySmall)
            if (!subtitle.isNullOrBlank()) {
                Spacer(modifier = Modifier.height(6.dp))
                Text(
                    text = subtitle,
                    fontSize = 13.sp,
                    lineHeight = 19.sp,
                    color = TextTertiary
                )
            }
        }
    }
}

/** 行尾状态色：正常灰、需要处理时沙金。 */
internal fun permissionStateColor(missing: Boolean): Color =
    if (missing) Sand else TextTertiary

internal val SettingsBodySecondary = TextStyle(
    fontSize = 13.sp,
    lineHeight = 19.sp,
    color = TextSecondary,
    fontWeight = FontWeight.Normal
)
