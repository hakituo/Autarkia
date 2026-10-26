package com.aveline.ai.mobile.presentation.mall

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.domain.models.RecipientOption
import com.aveline.ai.mobile.domain.models.ShopItem
import com.aveline.ai.mobile.presentation.components.controls.AvelineStepper
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 购买面板：点商品整行打开。
 *
 * 收礼对象与「谁吃」用同一套单选行；数量是步进器，上限由余额算出来；
 * 底部只保留「取消 / 确认购买」两个动作，买不起时确认键降透明度而不是弹红字。
 */
@Composable
internal fun PurchaseSheet(
    item: ShopItem,
    quantity: Int,
    totalCost: Int,
    canAfford: Boolean,
    maxQuantity: Int,
    recipientOptions: List<RecipientOption>,
    selectedRecipient: RecipientOption,
    onSelectRecipient: (RecipientOption) -> Unit,
    onIncrease: () -> Unit,
    onDecrease: () -> Unit,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit
) {
    // 角色列表没取到时按「共享」处理，与 recipientLabel 的历史口径一致
    val recipients = remember(recipientOptions) {
        recipientOptions.ifEmpty { listOf(RecipientOption("", "共享")) }
    }

    MallSheet(
        label = "购买 · ${item.name}",
        title = "买给谁？",
        onDismiss = onDismiss
    ) {
        recipients.forEach { option ->
            MallRecipientRow(
                name = option.label,
                note = if (option.id.isEmpty()) "不计入具体角色" else "",
                selected = option.id == selectedRecipient.id,
                onClick = { onSelectRecipient(option) }
            )
        }

        Spacer(modifier = Modifier.height(14.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(text = "数量", fontSize = 14.sp, color = TextSecondary)
            AvelineStepper(
                value = quantity,
                onValueChange = { next ->
                    if (next > quantity) onIncrease() else if (next < quantity) onDecrease()
                },
                min = 1,
                max = maxQuantity.coerceAtLeast(1)
            )
        }

        Spacer(modifier = Modifier.height(10.dp))
        MallHairLine()
        Spacer(modifier = Modifier.height(10.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(text = "合计", fontSize = 14.sp, color = TextSecondary)
            Text(
                text = "${formatCoins(totalCost)} 金币",
                style = TextStyle(
                    fontSize = 15.5.sp,
                    fontWeight = FontWeight.Medium,
                    color = if (canAfford) TextPrimary else TextTertiary,
                    fontFeatureSettings = "tnum"
                )
            )
        }

        MallSheetActions(
            cancelText = "取消",
            confirmText = "确认购买",
            onCancel = onDismiss,
            onConfirm = onConfirm,
            confirmEnabled = canAfford && item.isAvailable
        )
    }
}
