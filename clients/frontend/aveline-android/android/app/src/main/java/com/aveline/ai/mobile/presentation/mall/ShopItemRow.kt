package com.aveline.ai.mobile.presentation.mall

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.domain.models.ItemRarity
import com.aveline.ai.mobile.domain.models.ShopItem
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.Edge
import com.aveline.ai.mobile.presentation.theme.Sand
import com.aveline.ai.mobile.presentation.theme.SurfaceHigh
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/** 列表行之间的细分隔线（6% 白，比分隔区块的 Line 更轻）。 */
@Composable
internal fun MallHairLine() {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(1.dp)
            .background(Color.White.copy(alpha = 0.06f))
    )
}

/** 统一图位：深灰底 + 线性图标；以后有商品图直接换成图片。 */
@Composable
internal fun MallIconTile(
    icon: ImageVector,
    size: Dp,
    corner: Dp,
    iconSize: Dp
) {
    Box(
        modifier = Modifier
            .size(size)
            .clip(RoundedCornerShape(corner))
            .background(SurfaceHigh),
        contentAlignment = Alignment.Center
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = TextTertiary,
            modifier = Modifier.size(iconSize)
        )
    }
}

/**
 * 商城列表的一件商品（一行一件）。
 *
 * 名称 + 稀有度文字 / 一句描述 / 效果（鼠尾草绿）/ 价格；食物右下多一个描边的「食用」。
 * 整行点击打开购买面板；售罄行不可点，价格与名称一起变灰。
 */
@Composable
internal fun ShopItemRow(
    item: ShopItem,
    canAfford: Boolean,
    onBuy: () -> Unit,
    onEat: () -> Unit
) {
    val available = item.isAvailable
    Column(modifier = Modifier.fillMaxWidth()) {
        MallHairLine()
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable(enabled = available, onClick = onBuy)
                .padding(vertical = 14.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            MallIconTile(
                icon = mallCategoryIcon(item.category),
                size = 52.dp,
                corner = 14.dp,
                iconSize = 24.dp
            )
            Spacer(modifier = Modifier.width(14.dp))
            Column(modifier = Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = item.name,
                        fontSize = 15.5.sp,
                        fontWeight = FontWeight.Medium,
                        color = if (available) TextPrimary else TextTertiary,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f, fill = false)
                    )
                    if (item.rarity != ItemRarity.COMMON) {
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            text = item.rarity.label,
                            fontSize = 12.sp,
                            color = Sand,
                            maxLines = 1
                        )
                    }
                }
                if (item.description.isNotBlank()) {
                    Spacer(modifier = Modifier.height(3.dp))
                    Text(
                        text = item.description,
                        fontSize = 13.sp,
                        color = TextTertiary,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }
                if (item.effectDescription.isNotBlank()) {
                    Spacer(modifier = Modifier.height(2.dp))
                    Text(
                        text = item.effectDescription,
                        fontSize = 12.5.sp,
                        color = Accent,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }
            }
            Spacer(modifier = Modifier.width(14.dp))
            Column(
                horizontalAlignment = Alignment.End,
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Text(
                    text = formatCoins(item.price),
                    style = TextStyle(
                        fontSize = 15.5.sp,
                        fontWeight = FontWeight.Medium,
                        color = if (available && canAfford) TextPrimary else TextTertiary,
                        fontFeatureSettings = "tnum"
                    )
                )
                if (item.isFood) {
                    SmallOutlinedAction(
                        text = "食用",
                        enabled = available,
                        onClick = onEat
                    )
                }
            }
        }
    }
}

/** 30dp 高的小描边按钮：食物行的「食用」，与购买面板的实心按钮拉开层级。 */
@Composable
internal fun SmallOutlinedAction(
    text: String,
    enabled: Boolean,
    onClick: () -> Unit
) {
    val shape = RoundedCornerShape(10.dp)
    Box(
        modifier = Modifier
            .height(30.dp)
            .clip(shape)
            .border(1.dp, Edge, shape)
            .clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = 12.dp),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = text,
            fontSize = 13.sp,
            fontWeight = FontWeight.Medium,
            color = if (enabled) TextPrimary else TextTertiary,
            maxLines = 1
        )
    }
}
