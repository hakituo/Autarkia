package com.aveline.ai.mobile.presentation.mall

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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Inventory2
import androidx.compose.material.icons.outlined.Storefront
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.domain.models.RecipientOption
import com.aveline.ai.mobile.domain.models.ShopCategory
import com.aveline.ai.mobile.domain.models.ShopItem
import com.aveline.ai.mobile.presentation.components.ModuleHeader
import com.aveline.ai.mobile.presentation.components.controls.AvelineIconButton
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.Danger
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** 类目 Tab 与后端过滤参数：null = 全部。 */
private val CATEGORY_TABS: List<Pair<ShopCategory?, String>> = listOf(
    null to "全部",
    ShopCategory.FOOD to "食物",
    ShopCategory.GIFT to "礼物",
    ShopCategory.TOY to "玩具",
    ShopCategory.BOOK to "书籍",
    ShopCategory.CLOTHING to "服饰",
    ShopCategory.TECH to "科技",
    ShopCategory.LUXURY to "奢侈品"
)

/** 提示行停留时长：购买结果与加载失败都只闪一下，不弹对话框打断。 */
private const val MESSAGE_VISIBLE_MILLIS = 4_000L

/**
 * 商城主界面（设计稿《Aveline Android Mall》）。
 *
 * 一行一件商品：图位 / 名称与稀有度 / 描述 / 效果 / 价格，整行点击打开购买面板；
 * 食物行右下多一个「食用」。余额常驻页头，库存按钮进独立页。
 */
@Composable
fun MallScreen(
    shopUiState: ShopUiState,
    onSelectCategory: (ShopCategory?) -> Unit,
    onLoadMore: (ShopCategory?) -> Unit,
    onShowPurchaseConfirm: (ShopItem) -> Unit,
    onHidePurchaseConfirm: () -> Unit,
    onConfirmPurchase: () -> Unit,
    onIncreaseQuantity: () -> Unit,
    onDecreaseQuantity: () -> Unit,
    onSelectRecipient: (RecipientOption) -> Unit,
    onHidePurchaseResult: () -> Unit,
    onClearError: () -> Unit,
    onOpenInventory: () -> Unit,
    onEatFood: (String, String) -> Unit
) {
    // 点「食用」先记录商品，选完人再真正执行
    var itemToEat by remember { mutableStateOf<ShopItem?>(null) }
    val pagerState = rememberPagerState(initialPage = 0) { CATEGORY_TABS.size }
    val scope = rememberCoroutineScope()
    val purchaseResult = shopUiState.purchaseResult

    // 只在落位后切数据：滑动过程中 currentPage 会来回跳，提前加载等于白发请求。
    LaunchedEffect(pagerState.settledPage) {
        onSelectCategory(CATEGORY_TABS[pagerState.settledPage].first)
    }

    LaunchedEffect(shopUiState.showPurchaseResult, purchaseResult) {
        if (shopUiState.showPurchaseResult && purchaseResult != null) {
            delay(MESSAGE_VISIBLE_MILLIS)
            onHidePurchaseResult()
        }
    }
    LaunchedEffect(shopUiState.error) {
        if (!shopUiState.error.isNullOrBlank()) {
            delay(MESSAGE_VISIBLE_MILLIS)
            onClearError()
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
    ) {
        ModuleHeader(
            title = "商城",
            subtitle = "余额 ${formatCoins(shopUiState.balance.coins)} 金币"
        ) {
            AvelineIconButton(
                icon = Icons.Outlined.Inventory2,
                contentDescription = "库存",
                onClick = onOpenInventory
            )
        }

        MallCategoryTabs(
            labels = CATEGORY_TABS.map { it.second },
            selectedIndex = pagerState.currentPage,
            onSelect = { index ->
                // 点击时先切数据，动画结束落位后的 settledPage 回调会因已在加载而跳过
                onSelectCategory(CATEGORY_TABS[index].first)
                scope.launch { pagerState.animateScrollToPage(index) }
            }
        )
        Spacer(modifier = Modifier.height(8.dp))

        // 错误优先于购买结果；两者都只占一行
        when {
            !shopUiState.error.isNullOrBlank() -> {
                MallStatusLine(text = shopUiState.error.orEmpty(), isError = true)
            }

            shopUiState.showPurchaseResult && purchaseResult != null -> {
                MallStatusLine(text = purchaseResult.message, isError = !purchaseResult.success)
            }
        }

        // 与 Tab 联动的是 pager 本身：整页左右滑切换类目，每个类目各自保留列表和滚动位置。
        HorizontalPager(
            state = pagerState,
            modifier = Modifier
                .fillMaxWidth()
                .weight(1f),
            key = { page -> CATEGORY_TABS[page].first?.name ?: "all" }
        ) { page ->
            val category = CATEGORY_TABS[page].first
            ShopItemList(
                feed = shopUiState.feedFor(category),
                coins = shopUiState.balance.coins,
                onLoadMore = { onLoadMore(category) },
                onBuy = onShowPurchaseConfirm,
                onEat = { itemToEat = it }
            )
        }
    }

    val item = shopUiState.itemToPurchase
    if (shopUiState.showPurchaseConfirm && item != null) {
        PurchaseSheet(
            item = item,
            quantity = shopUiState.purchaseQuantity,
            totalCost = shopUiState.totalCost,
            canAfford = shopUiState.canAffordSelectedItem,
            maxQuantity = shopUiState.maxPurchaseQuantity,
            recipientOptions = shopUiState.recipientOptions,
            selectedRecipient = shopUiState.purchaseRecipient,
            onSelectRecipient = onSelectRecipient,
            onIncrease = onIncreaseQuantity,
            onDecrease = onDecreaseQuantity,
            onConfirm = onConfirmPurchase,
            onDismiss = onHidePurchaseConfirm
        )
    }

    itemToEat?.let { food ->
        RecipientPickerSheet(
            label = "食用 · ${food.name}",
            title = "给谁吃？",
            confirmText = "确认食用",
            options = shopUiState.recipientOptions,
            onConfirm = { recipient ->
                onEatFood(food.id, recipient.id)
                itemToEat = null
            },
            onDismiss = { itemToEat = null }
        )
    }
}

/** 单个类目的商品列表：首次加载 / 空态 / 到底提示都在同一列里，避免整页跳动。 */
@Composable
private fun ShopItemList(
    feed: ShopCategoryFeed,
    coins: Int,
    onLoadMore: () -> Unit,
    onBuy: (ShopItem) -> Unit,
    onEat: (ShopItem) -> Unit
) {
    val listState = rememberLazyListState()

    // derivedStateOf 只创建一次，必须经 rememberUpdatedState 读到最新分页状态，
    // 否则 hasMore / isLoadingMore 会一直停留在首次组合的快照上。
    val latestFeed by rememberUpdatedState(feed)
    val shouldLoadMore by remember {
        derivedStateOf {
            val lastVisible = listState.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: -1
            val total = listState.layoutInfo.totalItemsCount
            total > 0 && lastVisible >= total - 3 &&
                latestFeed.hasMore && !latestFeed.isLoading && !latestFeed.isLoadingMore
        }
    }
    LaunchedEffect(shouldLoadMore) {
        if (shouldLoadMore) onLoadMore()
    }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 20.dp),
        state = listState,
        contentPadding = PaddingValues(bottom = 24.dp)
    ) {
        if (feed.isLoading && feed.items.isEmpty()) {
            item {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 48.dp),
                    contentAlignment = Alignment.Center
                ) {
                    CircularProgressIndicator(strokeWidth = 2.dp)
                }
            }
        }

        if (!feed.isLoading && feed.items.isEmpty()) {
            item { EmptyMallState() }
        }

        items(items = feed.items, key = { it.id }) { item ->
            ShopItemRow(
                item = item,
                canAfford = coins >= item.price,
                onBuy = { onBuy(item) },
                onEat = { onEat(item) }
            )
        }

        if (feed.isLoadingMore) {
            item {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 16.dp),
                    contentAlignment = Alignment.Center
                ) {
                    CircularProgressIndicator(modifier = Modifier.size(24.dp), strokeWidth = 2.dp)
                }
            }
        }

        if (!feed.hasMore && feed.items.isNotEmpty()) {
            item {
                Text(
                    text = "已经到底啦",
                    fontSize = 12.sp,
                    color = TextTertiary,
                    textAlign = TextAlign.Center,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 14.dp)
                )
            }
        }
    }
}

@Composable
private fun EmptyMallState() {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 56.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Icon(
            imageVector = Icons.Outlined.Storefront,
            contentDescription = null,
            tint = TextTertiary,
            modifier = Modifier.size(44.dp)
        )
        Text(
            text = "这个类目还没有商品",
            style = MaterialTheme.typography.bodyMedium,
            color = TextSecondary
        )
    }
}

@Composable
private fun MallStatusLine(text: String, isError: Boolean) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 20.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            text = text,
            fontSize = 13.sp,
            color = if (isError) Danger else Accent,
            maxLines = 2
        )
    }
}
