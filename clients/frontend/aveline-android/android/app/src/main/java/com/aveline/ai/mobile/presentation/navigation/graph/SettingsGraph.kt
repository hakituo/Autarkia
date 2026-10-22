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
import com.aveline.ai.mobile.domain.models.EmotionType
import com.aveline.ai.mobile.domain.models.ResponseLength
import com.aveline.ai.mobile.presentation.navigation.Routes
import com.aveline.ai.mobile.presentation.navigation.fadeEnter
import com.aveline.ai.mobile.presentation.navigation.fadeExit
import com.aveline.ai.mobile.presentation.plugins.PluginsViewModel
import com.aveline.ai.mobile.presentation.settings.SettingsScreenV2
import com.aveline.ai.mobile.presentation.settings.SettingsViewModel
import com.aveline.ai.mobile.presentation.tools.ToolsViewModel

/** 设置（常规 / 权限 / 隐私 / 数据 / 高级，含 Plugins + Tools 调试工具）。 */
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
                // Settings 回调
                onOpenUsageStatsSettings = settingsViewModel::openUsageStatsSettings,
                onOpenNotificationSettings = settingsViewModel::openNotificationSettings,
                onToggleContextSync = {
                    settingsViewModel.toggleContextSync(!settingsUiState.isContextSyncEnabled)
                },
                onBackendUrlChange = settingsViewModel::setBackendUrl,
                onLanUrlChange = settingsViewModel::setLanUrl,
                onVpnUrlChange = settingsViewModel::setVpnUrl,
                onTunnelUrlChange = settingsViewModel::setTunnelUrl,
                onTokenChange = settingsViewModel::setAccessToken,
                onTestConnection = settingsViewModel::testConnection,
                onReprobeEndpoint = settingsViewModel::reprobeEndpoint,
                onSaveBackendUrl = settingsViewModel::saveBackendUrl,
                onModelChange = { modelId ->
                    pluginsUiState.models.find { it.id == modelId }?.let {
                        settingsViewModel.selectModel(it)
                    }
                },
                onVoiceIdChange = settingsViewModel::setVoiceId,
                onResponseLengthChange = { lengthStr ->
                    settingsViewModel.setResponseLength(
                        ResponseLength.values().find {
                            it.name.equals(lengthStr, ignoreCase = true)
                        } ?: ResponseLength.NORMAL
                    )
                },
                onToggleAutoTts = {
                    settingsViewModel.toggleAutoTts(!settingsUiState.autoTtsEnabled)
                },
                onToggleResidentMode = {
                    settingsViewModel.toggleResidentMode(!settingsUiState.residentModeEnabled)
                },
                onConfirmBatteryOptimization = settingsViewModel::confirmBatteryOptimization,
                onDismissBatteryOptimization = settingsViewModel::dismissBatteryOptimization,
                onClearHistory = settingsViewModel::clearHistory,
                onShowClearConfirm = settingsViewModel::showClearHistoryConfirm,
                onHideClearConfirm = settingsViewModel::hideClearHistoryConfirm,
                onHideSaveConfirm = settingsViewModel::hideSaveConfirm,
                // Plugins 回调(情绪 / 学习模式 / 分级模式)
                onSetManualEmotion = { emotionName ->
                    pluginsViewModel.setManualEmotion(
                        EmotionType.values().find {
                            it.name.equals(emotionName, ignoreCase = true)
                        }
                    )
                },
                onToggleStudyMode = pluginsViewModel::toggleStudyMode,
                onToggleAutoEmotion = pluginsViewModel::toggleAutoEmotion,
                onShowEmotionSelector = {
                    // 自动情绪开启时,先关闭它,否则手动选择会被后端推送覆盖
                    if (pluginsUiState.settings.autoEmotion) {
                        pluginsViewModel.toggleAutoEmotion()
                    }
                    pluginsViewModel.showEmotionSelector()
                },
                onHideEmotionSelector = pluginsViewModel::hideEmotionSelector,
                // toggleSensitive() 无参数,忽略 Boolean 入参
                onToggleSensitive = { _ -> pluginsViewModel.toggleSensitive() },
                onRefreshSensitive = pluginsViewModel::refreshSensitive,
                // Tools 回调(高级调试工具)
                onLoadImageModels = toolsViewModel::loadImageModels,
                onGenerateImage = toolsViewModel::generateImage,
                onImagePromptChange = toolsViewModel::setImagePrompt,
                onImageModelChange = toolsViewModel::setImageModelId,
                onVisionInputChange = toolsViewModel::setVisionInput,
                onVisionPromptChange = toolsViewModel::setVisionPrompt,
                onDescribeVision = toolsViewModel::describeVision,
                onLoadSystemResources = toolsViewModel::loadSystemResources,
                onLoadSystemStats = toolsViewModel::loadSystemStats,
                onClearError = toolsViewModel::clearError,
                // ON_RESUME 时重新检测 HC / Usage Stats / Notification 三个权限, 修复授权后仍显 ×
                onRefreshPermissions = settingsViewModel::refreshPermissions
            )
        }
    }
}
