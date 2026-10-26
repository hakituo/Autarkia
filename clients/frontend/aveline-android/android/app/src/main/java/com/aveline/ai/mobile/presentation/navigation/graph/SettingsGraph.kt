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
import com.aveline.ai.mobile.presentation.navigation.Routes
import com.aveline.ai.mobile.presentation.navigation.fadeEnter
import com.aveline.ai.mobile.presentation.navigation.fadeExit
import com.aveline.ai.mobile.presentation.plugins.PluginsViewModel
import com.aveline.ai.mobile.presentation.settings.SettingsScreenV2
import com.aveline.ai.mobile.presentation.settings.SettingsViewModel
import com.aveline.ai.mobile.presentation.tools.ToolsViewModel

/** 设置（单页分组列表 + 网络 / 权限向导 / 系统资源三个二级页）。 */
internal fun NavGraphBuilder.settingsScreen() {
    composable(
        route = Routes.SETTINGS,
        deepLinks = listOf(navDeepLink { uriPattern = "aveline://settings" }),
        enterTransition = fadeEnter,
        exitTransition = fadeExit,
        popEnterTransition = fadeEnter,
        popExitTransition = fadeExit
    ) {
        val settingsViewModel: SettingsViewModel = hiltViewModel()
        val pluginsViewModel: PluginsViewModel = hiltViewModel()
        val toolsViewModel: ToolsViewModel = hiltViewModel()
        val settingsUiState by settingsViewModel.uiState.collectAsStateWithLifecycle()
        val pluginsUiState by pluginsViewModel.uiState.collectAsStateWithLifecycle()
        val toolsUiState by toolsViewModel.uiState.collectAsStateWithLifecycle()

        Surface(modifier = Modifier.fillMaxSize(), color = Color.Transparent) {
            SettingsScreenV2(
                settingsUiState = settingsUiState,
                pluginsUiState = pluginsUiState,
                toolsUiState = toolsUiState,
                onOpenUsageStatsSettings = settingsViewModel::openUsageStatsSettings,
                onOpenNotificationSettings = settingsViewModel::openNotificationSettings,
                onToggleContextSync = settingsViewModel::toggleContextSync,
                onToggleAutoTts = settingsViewModel::toggleAutoTts,
                onToggleStageDirection = settingsViewModel::toggleStageDirection,
                onToggleResidentMode = settingsViewModel::toggleResidentMode,
                onConfirmBatteryOptimization = settingsViewModel::confirmBatteryOptimization,
                onDismissBatteryOptimization = settingsViewModel::dismissBatteryOptimization,
                onClearHistory = settingsViewModel::clearHistory,
                onShowClearConfirm = settingsViewModel::showClearHistoryConfirm,
                onHideClearConfirm = settingsViewModel::hideClearHistoryConfirm,
                // 从系统设置授权后返回时重读 HC / 使用统计 / 通知监听
                onRefreshPermissions = settingsViewModel::refreshPermissions,
                onSaveAddress = settingsViewModel::saveAddress,
                onSaveAccessToken = settingsViewModel::saveAccessToken,
                onTestConnection = settingsViewModel::testConnection,
                onReprobeEndpoint = settingsViewModel::reprobeEndpoint,
                onRefreshCandidates = { settingsViewModel.refreshCandidates() },
                onToggleAutoEmotion = pluginsViewModel::toggleAutoEmotion,
                onSetManualEmotion = pluginsViewModel::setManualEmotion,
                onShowEmotionSelector = {
                    // 自动情绪开启时先关掉，否则手动选择会被后端推送覆盖
                    if (pluginsUiState.settings.autoEmotion) {
                        pluginsViewModel.toggleAutoEmotion()
                    }
                    pluginsViewModel.showEmotionSelector()
                },
                onHideEmotionSelector = pluginsViewModel::hideEmotionSelector,
                onLoadSystemResources = toolsViewModel::loadSystemResources,
                onLoadSystemStats = toolsViewModel::loadSystemStats,
                onClearToolsError = toolsViewModel::clearError,
                onDismissClearError = settingsViewModel::clearClearError
            )
        }
    }
}
