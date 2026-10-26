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
import com.aveline.ai.mobile.data.local.storage.PersonaAvatarStorage
import com.aveline.ai.mobile.presentation.conversations.ConversationAvatarStorageHolder
import com.aveline.ai.mobile.presentation.conversations.ConversationListScreen
import com.aveline.ai.mobile.presentation.conversations.ConversationListViewModel
import com.aveline.ai.mobile.presentation.navigation.NavArgs
import com.aveline.ai.mobile.presentation.navigation.Routes
import com.aveline.ai.mobile.presentation.navigation.conversationsExit
import com.aveline.ai.mobile.presentation.navigation.conversationsPopEnter
import com.aveline.ai.mobile.presentation.navigation.fadeEnter
import com.aveline.ai.mobile.presentation.navigation.fadeExit

/**
 * 会话列表（主页，QQ 风格：每个角色一行）。
 *
 * 平板与手机统一用可滑动的导航侧栏（右滑拉出、左滑收起），
 * 主内容始终是会话列表：侧栏收起时用户仍能在这里选角色进聊天。
 */
internal fun NavGraphBuilder.conversationsScreen(navController: NavHostController) {
    composable(
        route = Routes.CONVERSATIONS,
        deepLinks = listOf(navDeepLink { uriPattern = "aveline://conversations" }),
        enterTransition = fadeEnter,
        exitTransition = conversationsExit,
        popEnterTransition = conversationsPopEnter,
        popExitTransition = fadeExit
    ) {
        Surface(modifier = Modifier.fillMaxSize(), color = Color.Transparent) {
            val viewModel: ConversationListViewModel = hiltViewModel()
            val uiState by viewModel.uiState.collectAsStateWithLifecycle()
            val avatarStorage: PersonaAvatarStorage =
                hiltViewModel<ConversationAvatarStorageHolder>().avatarStorage

            ConversationListScreen(
                uiState = uiState,
                // 仅在列表为空时以"重新加载"按钮出现（非常驻）：启动瞬间后端未就绪时
                // 必须留一条恢复路径，否则错误条一关就永久卡在空列表。
                onReload = viewModel::refresh,
                // 点击角色：navigate 进 Chat，带 role + profileFilename。
                // 优先切到消息列表里代表该角色显示的那个 persona，避免点进去变成其它版本。
                onOpenChat = { role, profileFilename, displayName ->
                    navigateToChat(navController, role, profileFilename, displayName)
                },
                onUpdateDisplayName = viewModel::updateDisplayName,
                onUpdateAvatar = viewModel::updateAvatar,
                onClearAvatar = viewModel::clearAvatar,
                onClearError = viewModel::clearError,
                avatarStorage = avatarStorage,
                // 语音音色（人设面板里选）：候选与角色默认值都来自后端 persona 响应
                voiceNames = uiState.voiceNames,
                personaVoiceOverrides = uiState.personaVoiceOverrides,
                personaDefaultVoices = uiState.personaDefaultVoices,
                onSelectVoice = viewModel::selectPersonaVoice,
                onResetVoice = { filename -> viewModel.selectPersonaVoice(filename, "") }
            )
        }
    }
}

/**
 * 打开聊天页（窄窗口）。
 *
 * 连点保护：`navigate()` 同步压栈，第二次点击到达时栈顶已经是 Chat。
 * 不拦的话会 push 出两个完全相同的聊天页（要按两次返回才回到列表）。
 */
private fun navigateToChat(
    navController: NavHostController,
    role: String,
    profileFilename: String,
    displayName: String
) {
    val currentRoute = navController.currentBackStackEntry?.destination?.route
    if (currentRoute?.startsWith("${Routes.CHAT}?") == true) return

    navController.navigate(buildChatRoute(role, profileFilename, displayName))
}

/**
 * 拼聊天页路由。
 *
 * 昵称可能含空格，URLEncoder 会编成 '+'，而 Navigation 只解 %XX，故统一用 %20；
 * role / filename 也一起编码，避免角色名里的特殊字符把参数截断。
 */
internal fun buildChatRoute(role: String, profileFilename: String, displayName: String): String {
    val encodedRole = java.net.URLEncoder.encode(role, "UTF-8")
    val encodedFilename = java.net.URLEncoder.encode(profileFilename, "UTF-8")
    val encodedName = java.net.URLEncoder.encode(displayName, "UTF-8").replace("+", "%20")
    return "${Routes.CHAT}?text=&role=$encodedRole&filename=$encodedFilename" +
        "&${NavArgs.DISPLAY_NAME}=$encodedName"
}
