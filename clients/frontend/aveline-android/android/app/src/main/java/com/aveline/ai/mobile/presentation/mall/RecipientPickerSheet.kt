package com.aveline.ai.mobile.presentation.mall

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import com.aveline.ai.mobile.domain.models.RecipientOption

/**
 * 单人选人面板：食物「食用」与库存「送出」共用。
 *
 * 原先两处都是 AlertDialog，现在统一成与购买面板相同的底部面板，
 * 用一行「食用 · 热可可」交代来源，标题只问「给谁吃 / 送给谁」。
 */
@Composable
internal fun RecipientPickerSheet(
    label: String,
    title: String,
    confirmText: String,
    options: List<RecipientOption>,
    onConfirm: (RecipientOption) -> Unit,
    onDismiss: () -> Unit
) {
    val recipients = remember(options) {
        options.ifEmpty { listOf(RecipientOption("", "共享")) }
    }
    var selectedId by remember(recipients) { mutableStateOf(recipients.first().id) }
    val selected = recipients.firstOrNull { it.id == selectedId } ?: recipients.first()

    MallSheet(label = label, title = title, onDismiss = onDismiss) {
        recipients.forEach { option ->
            MallRecipientRow(
                name = option.label,
                note = if (option.id.isEmpty()) "当前无可选角色" else "",
                selected = option.id == selectedId,
                onClick = { selectedId = option.id }
            )
        }
        MallSheetActions(
            cancelText = "取消",
            confirmText = confirmText,
            onCancel = onDismiss,
            onConfirm = { onConfirm(selected) }
        )
    }
}
