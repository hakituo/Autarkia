package com.aveline.ai.mobile.presentation.mall

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.MenuBook
import androidx.compose.material.icons.outlined.Checkroom
import androidx.compose.material.icons.outlined.Devices
import androidx.compose.material.icons.outlined.Diamond
import androidx.compose.material.icons.outlined.Redeem
import androidx.compose.material.icons.outlined.Restaurant
import androidx.compose.material.icons.outlined.Storefront
import androidx.compose.material.icons.outlined.Toys
import androidx.compose.ui.graphics.vector.ImageVector
import com.aveline.ai.mobile.domain.models.RecipientOption
import com.aveline.ai.mobile.domain.models.ShopCategory
import com.aveline.ai.mobile.domain.models.recipientLabel

/**
 * 商城展示口径（设计稿《Aveline Android Mall》）：
 * 价格只写数字、单位只写一次；类目一律用线性图标，不再用表情。
 */

/** 金币千分位：1280 → 1,280；单位由调用方决定写不写。 */
internal fun formatCoins(value: Int): String {
    val negative = value < 0
    val grouped = value.toString()
        .removePrefix("-")
        .reversed()
        .chunked(3)
        .joinToString(",")
        .reversed()
    return if (negative) "-$grouped" else grouped
}

/** 商品类目 → 线性图标；「全部」用店铺图标。 */
internal fun mallCategoryIcon(category: ShopCategory?): ImageVector = when (category) {
    null -> Icons.Outlined.Storefront
    ShopCategory.FOOD -> Icons.Outlined.Restaurant
    ShopCategory.GIFT -> Icons.Outlined.Redeem
    ShopCategory.TOY -> Icons.Outlined.Toys
    ShopCategory.BOOK -> Icons.AutoMirrored.Outlined.MenuBook
    ShopCategory.CLOTHING -> Icons.Outlined.Checkroom
    ShopCategory.TECH -> Icons.Outlined.Devices
    ShopCategory.LUXURY -> Icons.Outlined.Diamond
}

/** 库存接口下发的是原始类别字符串；认不出时不硬猜，回退成礼物图标。 */
internal fun mallCategoryIcon(rawCategory: String): ImageVector =
    mallCategoryIcon(ShopCategory.fromString(rawCategory) ?: ShopCategory.GIFT)

/** 类别中文名；未知类别保留后端原文，不显示空白。 */
internal fun mallCategoryLabel(rawCategory: String): String =
    ShopCategory.fromString(rawCategory)?.label ?: rawCategory

/**
 * 库存行副标题：类别 · 归属人 · ×件数。
 *
 * 共享库存不写归属人（「给 共享」读起来别扭），与 recipientLabel 的归一化口径一致。
 */
internal fun inventoryMetaText(
    rawCategory: String,
    recipientId: String?,
    quantity: Int,
    options: List<RecipientOption>
): String {
    val normalized = recipientId?.trim()?.lowercase().orEmpty()
    val shared = normalized.isEmpty() || normalized == "self" || normalized == "shared"
    val parts = buildList {
        add(mallCategoryLabel(rawCategory))
        if (!shared) add("给 ${recipientLabel(recipientId, options)}")
        add("×$quantity")
    }
    return parts.joinToString(" · ")
}
