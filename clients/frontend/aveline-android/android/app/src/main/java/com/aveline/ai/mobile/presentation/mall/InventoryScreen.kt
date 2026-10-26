package com.aveline.ai.mobile.presentation.mall

import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.Inventory2
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.domain.models.GiftInventoryItem
import com.aveline.ai.mobile.presentation.components.controls.AvelineIconButton
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.Danger
import com.aveline.ai.mobile.presentation.theme.Edge
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import kotlinx.coroutines.delay

/** 送出结果停留时长：成功/失败都只留一行，不再弹结果对话框。 */
private const val MESSAGE_VISIBLE_MILLIS = 4_000L

/**
 * 库存页（设计稿《Aveline Android Mall》第三屏）。
 *
 * 从商城的礼物弹窗改成独立页：页头「库存 + 种数/件数」，每行一件物品 + 一个「送出」，
 * 点「送出」在底部面板里选收礼对象。
 */
@Composable
fun InventoryScreen(
    uiState: InventoryUiState,
    onBack: () -> Unit,
    onUseGift: (String, String) -> Unit,
    onClearMessage: () -> Unit
) {
    var giftToSend by remember { mutableStateOf<GiftInventoryItem?>(null) }

    LaunchedEffect(uiState.message) {
        if (uiState.message != null) {
            delay(MESSAGE_VISIBLE_MILLIS)
            onClearMessage()
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(56.dp)
                .padding(horizontal = 8.dp),
            contentAlignment = Alignment.CenterStart
        ) {
            AvelineIconButton(
                icon = Icons.AutoMirrored.Outlined.ArrowBack,
                contentDescription = "返回",
                onClick = onBack
            )
        }

        Column(modifier = Modifier.padding(horizontal = 20.dp)) {
            Text(text = "库存", style = MaterialTheme.typography.displaySmall)
            Text(
                text = "${uiState.kindCount} 种 · 共 ${uiState.totalQuantity} 件",
                fontSize = 13.sp,
                color = TextTertiary
            )
        }

        uiState.message?.let { message ->
            Text(
                text = message,
                fontSize = 13.sp,
                color = if (uiState.messageIsError) Danger else Accent,
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 8.dp)
            )
        }

        when {
            uiState.isLoading -> LoadingInventory(modifier = Modifier.weight(1f))

            uiState.items.isEmpty() -> EmptyInventory(modifier = Modifier.weight(1f))

            else -> LazyColumn(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f)
                    .padding(horizontal = 20.dp),
                contentPadding = PaddingValues(top = 20.dp, bottom = 24.dp)
            ) {
                items(items = uiState.items) { gift ->
                    InventoryRow(
                        gift = gift,
                        meta = inventoryMetaText(
                            rawCategory = gift.category,
                            recipientId = gift.recipient,
                            quantity = gift.quantity,
                            options = uiState.recipientOptions
                        ),
                        onSend = { giftToSend = gift }
                    )
                }
            }
        }
    }

    giftToSend?.let { gift ->
        RecipientPickerSheet(
            label = "送出 · ${gift.itemName}",
            title = "送给谁？",
            confirmText = "确认送出",
            options = uiState.recipientOptions,
            onConfirm = { recipient ->
                onUseGift(gift.itemId, recipient.id)
                giftToSend = null
            },
            onDismiss = { giftToSend = null }
        )
    }
}

/** 库存一行：44dp 图位 + 名称/类别与归属 + 右侧「送出」。 */
@Composable
private fun InventoryRow(
    gift: GiftInventoryItem,
    meta: String,
    onSend: () -> Unit
) {
    Column(modifier = Modifier.fillMaxWidth()) {
        MallHairLine()
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            MallIconTile(
                icon = mallCategoryIcon(gift.category),
                size = 44.dp,
                corner = 12.dp,
                iconSize = 22.dp
            )
            Spacer(modifier = Modifier.width(14.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = gift.itemName,
                    fontSize = 15.5.sp,
                    color = TextPrimary,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Spacer(modifier = Modifier.height(2.dp))
                Text(
                    text = meta,
                    fontSize = 12.5.sp,
                    color = TextTertiary,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
            Spacer(modifier = Modifier.width(12.dp))
            SendOutlinedButton(onClick = onSend)
        }
    }
}

/** 34dp 描边小按钮：库存每行只有这一个动作。 */
@Composable
private fun SendOutlinedButton(onClick: () -> Unit) {
    val shape = RoundedCornerShape(12.dp)
    Box(
        modifier = Modifier
            .height(34.dp)
            .border(1.dp, Edge, shape)
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = "送出",
            fontSize = 13.5.sp,
            fontWeight = FontWeight.Medium,
            color = TextPrimary,
            maxLines = 1
        )
    }
}

@Composable
private fun LoadingInventory(modifier: Modifier = Modifier) {
    Box(
        modifier = modifier.fillMaxWidth(),
        contentAlignment = Alignment.Center
    ) {
        CircularProgressIndicator(strokeWidth = 2.dp)
    }
}

@Composable
private fun EmptyInventory(modifier: Modifier = Modifier) {
    Box(
        modifier = modifier
            .fillMaxWidth()
            .padding(24.dp),
        contentAlignment = Alignment.Center
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Icon(
                imageVector = Icons.Outlined.Inventory2,
                contentDescription = null,
                tint = TextTertiary,
                modifier = Modifier.size(44.dp)
            )
            Text(text = "库存是空的", fontSize = 15.sp, color = TextPrimary)
            Text(text = "去商城买点东西吧", fontSize = 13.sp, color = TextTertiary)
        }
    }
}
