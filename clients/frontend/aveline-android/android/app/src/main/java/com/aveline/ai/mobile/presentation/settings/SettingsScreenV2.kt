package com.aveline.ai.mobile.presentation.settings

import androidx.activity.compose.BackHandler
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.aveline.ai.mobile.domain.models.EmotionType
import com.aveline.ai.mobile.presentation.plugins.PluginsUiState
import com.aveline.ai.mobile.presentation.tools.ToolsUiState

private enum class SettingsPage {
    HOME,
    NETWORK,
    ACCESSIBILITY,
    SHIZUKU,
    DEVELOPER
}

/**
 * 设置主界面：一页分组列表 + 四个二级页。
 *
 * 旧的五 Tab（常规 / 权限 / 隐私 / 数据 / 高级）已经取消；每次只渲染当前页，
 * 二级页用本地状态而非导航路由，返回键统一回到首页。
 */
@Composable
internal fun SettingsScreenV2(
    settingsUiState: SettingsUiState,
    pluginsUiState: PluginsUiState,
    toolsUiState: ToolsUiState,
    onOpenUsageStatsSettings: () -> Unit,
    onOpenNotificationSettings: () -> Unit,
    onToggleContextSync: (Boolean) -> Unit,
    onToggleAutoTts: (Boolean) -> Unit,
    onToggleStageDirection: (Boolean) -> Unit,
    onToggleResidentMode: (Boolean) -> Unit,
    onConfirmBatteryOptimization: () -> Unit,
    onDismissBatteryOptimization: () -> Unit,
    onClearHistory: () -> Unit,
    onShowClearConfirm: () -> Unit,
    onHideClearConfirm: () -> Unit,
    onRefreshPermissions: () -> Unit,
    onSaveAddress: (SettingsAddressSlot, String) -> Unit,
    onSaveAccessToken: (String) -> Unit,
    onTestConnection: () -> Unit,
    onReprobeEndpoint: () -> Unit,
    onRefreshCandidates: () -> Unit,
    onToggleAutoEmotion: () -> Unit,
    onSetManualEmotion: (EmotionType) -> Unit,
    onShowEmotionSelector: () -> Unit,
    onHideEmotionSelector: () -> Unit,
    onLoadSystemResources: () -> Unit,
    onLoadSystemStats: () -> Unit,
    onClearToolsError: () -> Unit,
    onDismissClearError: () -> Unit
) {
    var pageName by rememberSaveable { mutableStateOf(SettingsPage.HOME.name) }
    val page = SettingsPage.valueOf(pageName)
    var permissionRefreshKey by rememberSaveable { mutableIntStateOf(0) }
    val deviceStatus = rememberDevicePermissionStatus(permissionRefreshKey)

    // 从系统设置授权 / 从 Shizuku 返回时，系统状态和 ViewModel 里的权限都要重读
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                onRefreshPermissions()
                permissionRefreshKey++
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    BackHandler(enabled = page != SettingsPage.HOME) {
        pageName = SettingsPage.HOME.name
    }

    val goHome = { pageName = SettingsPage.HOME.name }

    when (page) {
        SettingsPage.HOME -> SettingsHomePage(
            state = settingsUiState,
            deviceStatus = deviceStatus,
            pluginSettings = pluginsUiState.settings,
            onOpenNetwork = { pageName = SettingsPage.NETWORK.name },
            onToggleAutoTts = onToggleAutoTts,
            onToggleStageDirection = onToggleStageDirection,
            onToggleAutoEmotion = onToggleAutoEmotion,
            onOpenEmotionSelector = onShowEmotionSelector,
            onOpenUsageStatsSettings = onOpenUsageStatsSettings,
            onOpenNotificationSettings = onOpenNotificationSettings,
            onOpenAccessibilityWizard = { pageName = SettingsPage.ACCESSIBILITY.name },
            onOpenShizukuWizard = { pageName = SettingsPage.SHIZUKU.name },
            onToggleContextSync = onToggleContextSync,
            onToggleResidentMode = onToggleResidentMode,
            onOpenDeveloperTools = { pageName = SettingsPage.DEVELOPER.name },
            onShowClearConfirm = onShowClearConfirm,
            onDismissClearError = onDismissClearError
        )

        SettingsPage.NETWORK -> SettingsNetworkScreen(
            state = settingsUiState,
            onBack = goHome,
            onSaveAddress = onSaveAddress,
            onSaveAccessToken = onSaveAccessToken,
            onTestConnection = onTestConnection,
            onReprobeEndpoint = onReprobeEndpoint,
            onRefreshCandidates = onRefreshCandidates
        )

        SettingsPage.ACCESSIBILITY -> SettingsPermissionWizard(
            kind = PermissionWizardKind.ACCESSIBILITY,
            status = deviceStatus,
            onBack = goHome,
            onRefresh = { permissionRefreshKey++ }
        )

        SettingsPage.SHIZUKU -> SettingsPermissionWizard(
            kind = PermissionWizardKind.SHIZUKU,
            status = deviceStatus,
            onBack = goHome,
            onRefresh = { permissionRefreshKey++ }
        )

        SettingsPage.DEVELOPER -> SettingsSystemResourcesScreen(
            state = toolsUiState,
            onBack = goHome,
            onLoadSystemResources = onLoadSystemResources,
            onLoadSystemStats = onLoadSystemStats,
            onClearError = onClearToolsError
        )
    }

    if (pluginsUiState.showEmotionSelector) {
        SettingsEmotionDialog(
            selected = pluginsUiState.settings.manualEmotion,
            onSelect = onSetManualEmotion,
            onDismiss = onHideEmotionSelector
        )
    }

    if (settingsUiState.showClearConfirm) {
        SettingsClearHistoryDialog(
            isClearing = settingsUiState.isClearing,
            onConfirm = onClearHistory,
            onDismiss = onHideClearConfirm
        )
    }

    if (settingsUiState.showBatteryOptimizationRequest) {
        SettingsBatteryOptimizationDialog(
            onConfirm = onConfirmBatteryOptimization,
            onDismiss = onDismissBatteryOptimization
        )
    }
}
