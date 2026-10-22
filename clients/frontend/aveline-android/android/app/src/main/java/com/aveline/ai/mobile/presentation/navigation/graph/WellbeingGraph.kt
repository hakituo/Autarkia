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
import com.aveline.ai.mobile.presentation.navigation.Routes
import com.aveline.ai.mobile.presentation.navigation.fadeEnter
import com.aveline.ai.mobile.presentation.navigation.fadeExit
import com.aveline.ai.mobile.presentation.wellbeing.WellbeingScreen
import com.aveline.ai.mobile.presentation.wellbeing.WellbeingViewModel

/** 数字健康（应用使用时长限额）。 */
internal fun NavGraphBuilder.wellbeingScreen(navController: NavHostController) {
    composable(
        route = Routes.WELLBEING,
        deepLinks = listOf(navDeepLink { uriPattern = "aveline://wellbeing" }),
        enterTransition = fadeEnter,
        exitTransition = fadeExit,
        popEnterTransition = fadeEnter,
        popExitTransition = fadeExit
    ) {
        val viewModel: WellbeingViewModel = hiltViewModel()
        val uiState by viewModel.uiState.collectAsStateWithLifecycle()

        Surface(modifier = Modifier.fillMaxSize(), color = Color.Transparent) {
            WellbeingScreen(
                viewModel = viewModel,
                onBackClick = { navController.popBackStack() }
            )
        }
    }
}
