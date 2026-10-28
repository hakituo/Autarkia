package com.aveline.ai.mobile.presentation.navigation.graph

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavGraphBuilder
import androidx.navigation.compose.composable
import androidx.navigation.navDeepLink
import com.aveline.ai.mobile.presentation.health.DailyDataViewModel
import com.aveline.ai.mobile.presentation.life.LifeScreen
import com.aveline.ai.mobile.presentation.navigation.Routes
import com.aveline.ai.mobile.presentation.navigation.fadeEnter
import com.aveline.ai.mobile.presentation.navigation.fadeExit

/** 日常生活（健康 / 饮水 / 餐食）。 */
internal fun NavGraphBuilder.lifeScreen() {
    composable(
        route = Routes.LIFE,
        deepLinks = listOf(navDeepLink { uriPattern = "aveline://life" }),
        enterTransition = fadeEnter,
        exitTransition = fadeExit,
        popEnterTransition = fadeEnter,
        popExitTransition = fadeExit
    ) {
        val viewModel: DailyDataViewModel = hiltViewModel()
        val uiState by viewModel.uiState.collectAsStateWithLifecycle()
        val context = LocalContext.current

        Surface(modifier = Modifier.fillMaxSize(), color = Color.Transparent) {
            LifeScreen(
                uiState = uiState,
                // 自动刷新（ON_RESUME）：三星读取按 30 秒节流，后端 portrait 照常拉
                onRefresh = {
                    (context as? android.app.Activity)?.let { activity ->
                        viewModel.syncFromSamsungHealth(activity)
                    }
                    viewModel.refreshData()
                },
                // Samsung Health 同步: 权限请求需要 Activity, 从 Context 获取
                onSyncSamsungHealth = {
                    (context as? android.app.Activity)?.let { activity ->
                        viewModel.syncFromSamsungHealth(activity)
                    }
                },
                // LifeTab 与 DailyTab 不兼容,LifeScreen 自管 pagerState,这里无需通知
                onTabChange = { _ -> }
            )
        }
    }
}
