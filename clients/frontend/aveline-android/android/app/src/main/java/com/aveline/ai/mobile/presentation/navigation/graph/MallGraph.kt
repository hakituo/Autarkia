package com.aveline.ai.mobile.presentation.navigation.graph

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavGraphBuilder
import androidx.navigation.NavHostController
import androidx.navigation.compose.composable
import androidx.navigation.navDeepLink
import com.aveline.ai.mobile.presentation.mall.InventoryScreen
import com.aveline.ai.mobile.presentation.mall.InventoryViewModel
import com.aveline.ai.mobile.presentation.mall.MallScreen
import com.aveline.ai.mobile.presentation.mall.ShopViewModel
import com.aveline.ai.mobile.presentation.navigation.Routes
import com.aveline.ai.mobile.presentation.navigation.fadeEnter
import com.aveline.ai.mobile.presentation.navigation.fadeExit
import com.aveline.ai.mobile.presentation.navigation.navigateTo
import com.aveline.ai.mobile.presentation.tools.ToolsViewModel

/**
 * 商城与库存。
 *
 * 商品列表（商城）与礼物库存被拆成两个目的地：库存不再以弹窗形式压在商城上，
 * 返回时商城列表与滚动位置原样保留。
 */
internal fun NavGraphBuilder.mallScreen(navController: NavHostController) {
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
            MallScreen(
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
                onOpenInventory = { navController.navigateTo(Routes.INVENTORY) },
                // 食用来自 Tools：先选"谁吃"再执行，优先消耗对应角色名下库存
                onEatFood = { foodId, recipient -> toolsViewModel.eatFood(foodId, recipient) }
            )
        }
    }

    composable(
        route = Routes.INVENTORY,
        enterTransition = fadeEnter,
        exitTransition = fadeExit,
        popEnterTransition = fadeEnter,
        popExitTransition = fadeExit
    ) {
        val inventoryViewModel: InventoryViewModel = hiltViewModel()
        val inventoryUiState by inventoryViewModel.uiState.collectAsStateWithLifecycle()

        Surface(modifier = Modifier.fillMaxSize(), color = Color.Transparent) {
            InventoryScreen(
                uiState = inventoryUiState,
                onBack = { navController.popBackStack() },
                onUseGift = inventoryViewModel::useGift,
                onClearMessage = inventoryViewModel::clearMessage
            )
        }
    }
}
