package com.aveline.ai.mobile.presentation.life

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.aveline.ai.mobile.presentation.components.AvelineTabRow
import com.aveline.ai.mobile.presentation.components.ModuleHeader
import com.aveline.ai.mobile.presentation.health.daily.DailyDataUiState
import com.aveline.ai.mobile.presentation.theme.EmotionGreen
import kotlinx.coroutines.launch

/**
 * Life 模块 Tab 枚举。
 *
 * 说明:现有 [com.aveline.ai.mobile.presentation.health.daily.DailyTab] 仅包含
 * PORTRAIT / SCHEDULE / FILES 三个值,无法表达"饮水 / 餐食"两个独立 tab。
 * 为遵循"只创建新文件、不修改旧文件"的约束,这里新建 LifeTab 枚举。
 */
enum class LifeTab(val title: String) {
    HEALTH("健康"),
    SCHEDULE("日程"),
    WATER("饮水"),
    MEAL("餐食")
}

/**
 * Life 模块主界面。
 *
 * 用 TabRow + HorizontalPager 组织 4 个 tab:健康 / 饮水 / 日程 / 餐食。
 * 复用现有 [DailyDataUiState] 作为数据源,支持左右滑动切换。
 *
 * @param uiState 日常生活数据状态
 * @param onRefresh 自动刷新回调（ON_RESUME 等，内部按 30 秒节流）
 * @param onSyncSamsungHealth 从 Samsung Health 同步数据
 * @param onTabChange Tab 切换回调
 * @param onUpdateSchedule 更新作息回调(睡觉/起床时间)
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun LifeScreen(
    uiState: DailyDataUiState,
    onRefresh: () -> Unit,
    onSyncSamsungHealth: () -> Unit,
    onTabChange: (LifeTab) -> Unit,
    onUpdateSchedule: (sleep: String?, wakeup: String?) -> Unit
) {
    val tabs = LifeTab.values()
    val pagerState = rememberPagerState(initialPage = 0) { tabs.size }
    val scope = rememberCoroutineScope()

    // 监听 pager 页面变化,通知外部
    LaunchedEffect(pagerState.currentPage) {
        onTabChange(tabs[pagerState.currentPage])
    }

    // 进入 HEALTH tab 时检查是否需要立即同步（距上次同步超过 30 秒）。
    // lastRefreshTime 初值来自 App 启动同步时间：刚在启动时同步过就不重复读 SDK。
    LaunchedEffect(pagerState.currentPage) {
        if (pagerState.currentPage == LifeTab.HEALTH.ordinal) {
            val elapsed = System.currentTimeMillis() - uiState.lastRefreshTime
            if (elapsed > 30_000L) {
                onSyncSamsungHealth()
            }
        }
    }

    // HEALTH tab 可见时循环定时刷新：活动状态 1 分钟、非活动 5 分钟。
    // 不能把 lastRefreshTime 作为 key —— 每次同步完成都会改它，effect 反复重启、
    // 计时被清零，非活动状态下首次三星同步可能被无限推迟。
    val latestUiState by rememberUpdatedState(uiState)
    val latestSyncSamsungHealth by rememberUpdatedState(onSyncSamsungHealth)
    LaunchedEffect(pagerState.currentPage) {
        if (pagerState.currentPage != LifeTab.HEALTH.ordinal) return@LaunchedEffect
        while (true) {
            val isActive = (latestUiState.activeCaloriesBurned ?: 0.0) > 0
            kotlinx.coroutines.delay(if (isActive) 60_000L else 300_000L)
            latestSyncSamsungHealth()
        }
    }

    // ON_RESUME 重新拉数据: 用户从 Health Connect 设置页授权完返回时,
    // 电池/网络/设备上下文等数据需要重新读取 (与 Settings 页权限重检同理)
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                onRefresh()
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
    ) {
        // 顶部模块标题（不再放刷新键：数据由 ON_RESUME 与定时任务自动刷新）
        // 标题与侧边栏同名，去掉副标题（设计稿：页头只留「生活」）。
        ModuleHeader(title = "生活")

        AvelineTabRow(
            titles = tabs.map { it.title },
            selectedTabIndex = pagerState.currentPage,
            onTabSelected = { index ->
                scope.launch { pagerState.animateScrollToPage(index) }
            },
            modifier = Modifier.fillMaxWidth()
        )

        // 消息提示
        uiState.message?.takeIf { it.isNotBlank() }?.let { message ->
            Text(
                text = message,
                color = EmotionGreen,
                style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp)
            )
        }

        // 错误提示
        uiState.error?.takeIf { it.isNotBlank() }?.let { error ->
            Text(
                text = error,
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp)
            )
        }

        // Tab 内容区域:HorizontalPager 支持左右滑动
        HorizontalPager(
            state = pagerState,
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 16.dp)
        ) { page ->
            val tab = tabs[page]
            // 与 Companion 一致:内层 Box 无 padding,只做容器对齐
            Box(
                modifier = Modifier.fillMaxSize(),
                contentAlignment = Alignment.TopStart
            ) {
                when (tab) {
                    LifeTab.HEALTH -> LifeTabScroll {
                        LifeHealthTab(
                            uiState = uiState,
                            onSyncSamsungHealth = onSyncSamsungHealth
                        )
                    }

                    LifeTab.WATER -> LifeTabScroll {
                        LifeWaterTab(uiState = uiState)
                    }

                    LifeTab.SCHEDULE -> LifeTabScroll {
                        LifeScheduleTab(
                            uiState = uiState,
                            onUpdateSchedule = onUpdateSchedule
                        )
                    }

                    LifeTab.MEAL -> LifeTabScroll {
                        LifeMealTab(uiState = uiState)
                    }
                }
            }
        }
    }
}

/** 单个 Tab 的滚动容器：统一上下留白，横向内边距由外层 pager 提供。 */
@Composable
private fun LifeTabScroll(content: @Composable () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        Spacer(modifier = Modifier.height(8.dp))
        content()
        Spacer(modifier = Modifier.height(24.dp))
    }
}
