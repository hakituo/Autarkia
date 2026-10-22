package com.aveline.ai.mobile.presentation.navigation.graph

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavGraphBuilder
import androidx.navigation.compose.composable
import androidx.navigation.navDeepLink
import com.aveline.ai.mobile.presentation.food.FoodScreen
import com.aveline.ai.mobile.presentation.navigation.Routes
import com.aveline.ai.mobile.presentation.navigation.fadeEnter
import com.aveline.ai.mobile.presentation.navigation.fadeExit
import com.aveline.ai.mobile.presentation.shop.ShopViewModel
import com.aveline.ai.mobile.presentation.tools.ToolsViewModel

/** 商城（食物 / 礼物 / 玩具 / 书籍 / 服饰 / 科技 / 奢侈品）。 */
internal fun NavGraphBuilder.mallScreen() {
    composable(
        route = Routes.FOOD,
        deepLinks = listOf(
            navDeepLink { uriPattern = "aveline://food" },
            navDeepLink { uriPattern = "aveline://mall" }
        ),
        enterTransition = fadeEnter,
        exitTransition = fadeExit,
        popEnterTransition = fadeEnter,
        popExitTransition = fadeExit
    ) {
        val shopViewModel: ShopViewModel = hiltViewModel()
        val toolsViewModel: ToolsViewModel = hiltViewModel()
        val shopUiState by shopViewModel.uiState.collectAsStateWithLifecycle()

        Surface(modifier = Modifier.fillMaxSize(), color = Color.Transparent) {
            FoodScreen(
                shopUiState = shopUiState,
                onSelectCategory = { category -> shopViewModel.selectCategory(category) },
                onLoadMore = shopViewModel::loadMore,
                onShowPurchaseConfirm = shopViewModel::showPurchaseConfirm,
                onHidePurchaseConfirm = shopViewModel::hidePurchaseConfirm,
                onConfirmPurchase = shopViewModel::confirmPurchase,
                onIncreaseQuantity = shopViewModel::increaseQuantity,
                onDecreaseQuantity = shopViewModel::decreaseQuantity,
                onSelectRecipient = shopViewModel::selectRecipient,
                onHidePurchaseResult = shopViewModel::hidePurchaseResult,
                onClearError = shopViewModel::clearError,
                onShowGiftInventory = shopViewModel::showGiftInventory,
                onHideGiftInventory = shopViewModel::hideGiftInventory,
                onUseGift = shopViewModel::useGift,
                onHideUseGiftResult = shopViewModel::hideUseGiftResult,
                // 食用功能来自 Tools：先选"谁吃"(self/动态角色)再执行
                onEatFood = { foodId, recipient -> toolsViewModel.eatFood(foodId, recipient) }
            )
        }
    }
}
