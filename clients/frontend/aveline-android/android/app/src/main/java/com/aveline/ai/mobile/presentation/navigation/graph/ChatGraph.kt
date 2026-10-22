package com.aveline.ai.mobile.presentation.navigation.graph

import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.navigation.NavGraphBuilder
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.composable
import androidx.navigation.navArgument
import androidx.navigation.navDeepLink
import com.aveline.ai.mobile.presentation.chat.ChatScreen
import com.aveline.ai.mobile.presentation.chat.ChatViewModel
import com.aveline.ai.mobile.presentation.navigation.NavArgs
import com.aveline.ai.mobile.presentation.navigation.Routes
import com.aveline.ai.mobile.presentation.navigation.chatEnter
import com.aveline.ai.mobile.presentation.navigation.chatPopExit
import com.aveline.ai.mobile.presentation.navigation.fadeEnter
import com.aveline.ai.mobile.presentation.navigation.fadeExit

/** 聊天详情页（从会话列表点入，QQ 风格 push/pop 转场）。 */
internal fun NavGraphBuilder.chatScreen(navController: NavHostController) {
    composable(
        route = "${Routes.CHAT}?text={${NavArgs.TEXT}}&role={${NavArgs.ROLE}}" +
            "&filename={${NavArgs.PROFILE_FILENAME}}&${NavArgs.DISPLAY_NAME}={${NavArgs.DISPLAY_NAME}}",
        arguments = listOf(
            navArgument(NavArgs.TEXT) {
                type = NavType.StringType
                nullable = true
                defaultValue = null
            },
            navArgument(NavArgs.ROLE) {
                type = NavType.StringType
                nullable = true
                defaultValue = null
            },
            navArgument(NavArgs.PROFILE_FILENAME) {
                type = NavType.StringType
                nullable = true
                defaultValue = null
            },
            navArgument(NavArgs.DISPLAY_NAME) {
                type = NavType.StringType
                nullable = true
                defaultValue = null
            }
        ),
        deepLinks = listOf(
            navDeepLink { uriPattern = "aveline://chat" },
            navDeepLink { uriPattern = "aveline://chat?text={${NavArgs.TEXT}}" },
            navDeepLink { uriPattern = "aveline://chat?role={${NavArgs.ROLE}}" },
            // 主动消息通知深链：带 filename 让聊天页直达后端下发的那个 persona 会话。
            // 只有 role 时（旧通知），本地没有该 role 的选择记录就无法确定会话，
            // 聊天页会停留在上一个会话，用户表现为"点了通知但看不到那条消息"。
            navDeepLink {
                uriPattern = "aveline://chat?role={${NavArgs.ROLE}}" +
                    "&filename={${NavArgs.PROFILE_FILENAME}}"
            }
        ),
        enterTransition = chatEnter,
        exitTransition = fadeExit,
        popEnterTransition = fadeEnter,
        popExitTransition = chatPopExit
    ) { backStackEntry ->
        val chatViewModel: ChatViewModel = hiltViewModel()
        // 从 route 参数取 role + profileFilename。如果列表点击时带了 filename，
        // 优先切到列表里显示的那个 persona，避免点进去变成同一角色下的其它版本。
        val targetRole = backStackEntry.arguments?.getString(NavArgs.ROLE)
        val targetFilename = backStackEntry.arguments?.getString(NavArgs.PROFILE_FILENAME)
        val targetDisplayName = backStackEntry.arguments?.getString(NavArgs.DISPLAY_NAME)
        // 进入聊天页只记录"待切换意图"，不立即切 persona；真正切人设推迟到用户首次发消息时，
        // 避免只是查看历史也打后端 API（减少 429）。用 LaunchedEffect(Unit) 保证只执行一次。
        LaunchedEffect(targetRole, targetFilename) {
            if (!targetRole.isNullOrBlank()) {
                chatViewModel.setPendingSwitch(targetRole, targetFilename)
            } else {
                // 深链只给了 filename（或两者都空）时也要登记当前会话上下文：
                // 否则从通知进来的页面不会把自己的角色登记进去，
                // 后续通知既无法复用该页面（套娃），切回前台也不会自动撤通知。
                chatViewModel.markVisibleChat(targetRole, targetFilename)
            }
        }
        // 离开聊天页时清空"当前可见角色"登记：用户回到会话列表后，
        // 通知就不该再被当成"已看到"自动撤掉。
        DisposableEffect(Unit) {
            onDispose { chatViewModel.clearVisibleChat() }
        }
        // 聊天页每次重新可见都清零该角色未读：点通知回到已经打开的聊天页时，
        // 深链会被判定为"已在该角色聊天页"直接吞掉，不会重建 ViewModel，
        // 进页那一次清零也就不会发生（未读要再点几次才消）。这里用 ON_RESUME
        // 兜住所有"页面重新出现在眼前"的时机：首次进入、从后台切回、点通知复用页面。
        val chatLifecycleOwner = LocalLifecycleOwner.current
        DisposableEffect(chatLifecycleOwner) {
            val observer = LifecycleEventObserver { _, event ->
                if (event == Lifecycle.Event.ON_RESUME) chatViewModel.onChatPageResumed()
            }
            chatLifecycleOwner.lifecycle.addObserver(observer)
            onDispose { chatLifecycleOwner.lifecycle.removeObserver(observer) }
        }
        ChatScreen(
            viewModel = chatViewModel,
            // 标题初始值直接来自列表算好的 displayName：首帧就有正确角色名，
            // 不用等 persona 接口返回（否则会先闪一下"聊天"）。
            initialDisplayName = targetDisplayName,
            onBackClick = { navController.popBackStack() }
        )
    }
}

/** Companion 已合并到 Chat 内的伴侣详情面板，旧深链重定向回主页。 */
internal fun NavGraphBuilder.companionRedirect(navController: NavHostController) {
    composable(
        route = Routes.COMPANION,
        deepLinks = listOf(navDeepLink { uriPattern = "aveline://companion" }),
        enterTransition = fadeEnter,
        exitTransition = fadeExit,
        popEnterTransition = fadeEnter,
        popExitTransition = fadeExit
    ) {
        LaunchedEffect(Unit) {
            navController.navigate(Routes.CONVERSATIONS) {
                popUpTo(Routes.COMPANION) { inclusive = true }
            }
        }
    }
}
