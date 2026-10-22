package com.aveline.ai.mobile.presentation.navigation

import androidx.compose.animation.AnimatedContentTransitionScope
import androidx.compose.animation.EnterTransition
import androidx.compose.animation.ExitTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.navigation.NavBackStackEntry

/**
 * 页面切换动画参数（导航层共用）。
 *
 * 拆到单独文件是为了让每个业务域导航文件拿到同一套时长与转场，
 * 不再各自复制 `tween(ANIM_DURATION)` —— 曾经改时长要同时改七处。
 */
internal const val ANIM_DURATION = 300

/** 淡入淡出：tab 级页面（Study / Life / Mall / Settings / Wellbeing）。 */
internal val fadeEnter: AnimatedContentTransitionScope<NavBackStackEntry>.() -> EnterTransition =
    { fadeIn(animationSpec = tween(ANIM_DURATION)) }

internal val fadeExit: AnimatedContentTransitionScope<NavBackStackEntry>.() -> ExitTransition =
    { fadeOut(animationSpec = tween(ANIM_DURATION)) }

/**
 * 会话列表 ↔ 聊天详情的 QQ 风格 push/pop 转场。
 *
 * 列表侧只滑出 1/3 且带淡出，视觉上像被聊天页"压"回左侧；
 * 聊天页整屏滑入/滑出，返回时列表再从左侧滑回。
 */
internal val conversationsExit: AnimatedContentTransitionScope<NavBackStackEntry>.() -> ExitTransition =
    {
        slideOutHorizontally(
            targetOffsetX = { -it / 3 },
            animationSpec = tween(ANIM_DURATION)
        ) + fadeOut(animationSpec = tween(ANIM_DURATION))
    }

internal val conversationsPopEnter: AnimatedContentTransitionScope<NavBackStackEntry>.() -> EnterTransition =
    {
        slideInHorizontally(
            initialOffsetX = { -it / 3 },
            animationSpec = tween(ANIM_DURATION)
        ) + fadeIn(animationSpec = tween(ANIM_DURATION))
    }

internal val chatEnter: AnimatedContentTransitionScope<NavBackStackEntry>.() -> EnterTransition =
    {
        slideInHorizontally(
            initialOffsetX = { it },
            animationSpec = tween(ANIM_DURATION)
        ) + fadeIn(animationSpec = tween(ANIM_DURATION))
    }

internal val chatPopExit: AnimatedContentTransitionScope<NavBackStackEntry>.() -> ExitTransition =
    {
        slideOutHorizontally(
            targetOffsetX = { it },
            animationSpec = tween(ANIM_DURATION)
        ) + fadeOut(animationSpec = tween(ANIM_DURATION))
    }
