package com.aveline.ai.mobile.presentation.settings

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.domain.models.EmotionType
import com.aveline.ai.mobile.presentation.components.controls.AvelineButton
import com.aveline.ai.mobile.presentation.components.controls.AvelineButtonVariant
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.EmotionPalette
import com.aveline.ai.mobile.presentation.theme.TextPrimary

/** 手动情绪选择：一行一个情绪，行尾用颜色点代替色块。 */
@Composable
internal fun SettingsEmotionDialog(
    selected: EmotionType?,
    onSelect: (EmotionType) -> Unit,
    onDismiss: () -> Unit
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("手动情绪") },
        text = {
            Column {
                EmotionType.values().forEach { emotion ->
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(10.dp))
                            .clickable {
                                onSelect(emotion)
                                onDismiss()
                            }
                            .padding(horizontal = 8.dp, vertical = 9.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        SettingsValueDot(EmotionPalette.of(emotion.name.lowercase()))
                        Spacer(modifier = Modifier.width(10.dp))
                        Text(
                            text = emotion.label,
                            style = MaterialTheme.typography.bodyLarge,
                            color = TextPrimary
                        )
                        Spacer(modifier = Modifier.weight(1f))
                        if (selected == emotion) {
                            Icon(
                                imageVector = Icons.Default.Check,
                                contentDescription = "已选择",
                                tint = Accent,
                                modifier = Modifier.size(18.dp)
                            )
                        }
                    }
                }
            }
        },
        confirmButton = {
            AvelineButton(
                text = "关闭",
                onClick = onDismiss,
                variant = AvelineButtonVariant.Text
            )
        }
    )
}

/** 清除本地聊天记录确认；实心红只出现在这个确认按钮上。 */
@Composable
internal fun SettingsClearHistoryDialog(
    isClearing: Boolean,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("清除本地聊天记录") },
        text = { Text("会删除所有本地聊天历史，此操作不可撤销。") },
        confirmButton = {
            AvelineButton(
                text = "清除",
                onClick = onConfirm,
                variant = AvelineButtonVariant.Danger,
                dangerFilled = true,
                loading = isClearing
            )
        },
        dismissButton = {
            AvelineButton(
                text = "取消",
                onClick = onDismiss,
                variant = AvelineButtonVariant.Text
            )
        }
    )
}

/** 常驻模式的电池白名单引导。 */
@Composable
internal fun SettingsBatteryOptimizationDialog(
    onConfirm: () -> Unit,
    onDismiss: () -> Unit
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("加入电池优化白名单") },
        text = {
            Text("常驻模式需要加入电池优化白名单才能稳定后台运行，否则系统可能限制后台活动。")
        },
        confirmButton = {
            AvelineButton(
                text = "前往设置",
                onClick = onConfirm,
                variant = AvelineButtonVariant.Primary
            )
        },
        dismissButton = {
            AvelineButton(
                text = "稍后",
                onClick = onDismiss,
                variant = AvelineButtonVariant.Text
            )
        }
    )
}
