package com.aveline.ai.mobile.presentation.navigation

import androidx.navigation.NavGraphBuilder
import androidx.navigation.NavHostController
import com.aveline.ai.mobile.presentation.navigation.graph.chatScreen
import com.aveline.ai.mobile.presentation.navigation.graph.companionRedirect
import com.aveline.ai.mobile.presentation.navigation.graph.conversationsScreen
import com.aveline.ai.mobile.presentation.navigation.graph.lifeScreen
import com.aveline.ai.mobile.presentation.navigation.graph.mallScreen
import com.aveline.ai.mobile.presentation.navigation.graph.settingsScreen
import com.aveline.ai.mobile.presentation.navigation.graph.studyScreen
import com.aveline.ai.mobile.presentation.navigation.graph.wellbeingScreen

/**
 * 应用导航路由。
 *
 * 单元职责:
 * - Conversations: 会话列表（主页，QQ 风格，每个角色一行）
 * - Chat: 聊天详情页（从会话列表点入）
 * - Companion: AI 伴侣(状态 / 人设 / 记忆)
 * - Study: 学习(概览 / 计划 / 日记 / 笔记 / 文件 / 词汇)
 * - Life: 日常生活(健康 / 饮水 / 日程 / 餐食)
 * - Food: 商城(全部 / 食物 / 礼物 / 玩具 / 书籍 / 服饰 / 科技 / 奢侈品)
 * - Inventory: 库存(非食物商品，可送出)
 * - Settings: 设置(常规 / 权限 / 隐私 / 数据 / 高级)
 * - Wellbeing: 数字健康(应用使用时长限额)
 */
object Routes {
    const val CONVERSATIONS = "conversations"
    const val CHAT = "chat"
    const val COMPANION = "companion"
    const val STUDY = "study"
    const val LIFE = "life"
    const val FOOD = "food"
    const val INVENTORY = "inventory"
    const val SETTINGS = "settings"
    const val WELLBEING = "wellbeing"

    // 深链查询参数
    const val CHAT_TEXT_PARAM = "text"
}

/**
 * 导航参数名。
 */
object NavArgs {
    const val TEXT = "text"
    const val ROLE = "role"
    const val PROFILE_FILENAME = "profile_filename"
    /** 会话列表算好的展示名（自定义昵称 > 角色名），避免聊天页首帧只能显示"聊天"。 */
    const val DISPLAY_NAME = "name"
    /** 学习页直达子模块：`vocab` = 背单词（更多 → 词汇）。 */
    const val TAB = "tab"

    /** 学习页 tab 参数取值：背单词。 */
    const val TAB_VOCAB = "vocab"
}

/**
 * 创建 Aveline 主导航图。
 *
 * 本文件只做**编排**：每个业务域的 `composable` 注册都在 `navigation/graph/` 下，
 * 各自持有自己的 ViewModel 绑定、生命周期回调与深链。加一个页面只需要在这里多一行，
 * 不再让单文件随功能线性膨胀。
 *
 * @param navController 导航控制器
 * @param onMenuClick 菜单按钮点击回调（保留给宿主，当前未使用）
 * @param startDestination 起始目的地路由（默认会话列表）
 */
@Suppress("UNUSED_PARAMETER")
fun NavGraphBuilder.avelineNavGraph(
    navController: NavHostController,
    onMenuClick: () -> Unit = {},
    startDestination: String = Routes.CONVERSATIONS
) {
    conversationsScreen(navController)
    chatScreen(navController)
    companionRedirect(navController)
    studyScreen()
    lifeScreen()
    mallScreen(navController)
    settingsScreen()
    wellbeingScreen(navController)
}

/**
 * 导航到指定路由(单顶 + 恢复状态)。
 */
fun NavHostController.navigateTo(route: String) {
    navigate(route) {
        launchSingleTop = true
        restoreState = true
    }
}

/**
 * 导航到 Chat 并预填文本。
 */
fun NavHostController.navigateToChatWithText(text: String) {
    // 传完整 query 参数（role/filename/name 空占位），避免 Navigation Compose 因中间参数省略匹配失败
    val encodedText = java.net.URLEncoder.encode(text, "UTF-8")
    navigate("${Routes.CHAT}?text=$encodedText&role=&filename=&${NavArgs.DISPLAY_NAME}=")
}
