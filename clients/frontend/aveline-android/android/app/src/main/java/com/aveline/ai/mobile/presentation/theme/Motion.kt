package com.aveline.ai.mobile.presentation.theme

import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.Easing

/**
 * 动效时长 token（毫秒）。
 *
 * 系统「移除动画」由 Compose 自己处理：开发者选项把动画时长缩放设成 0 时，
 * 帧时钟的 MotionDurationScale 为 0，所有 tween 立即跳到终点，不需要页面再判断。
 */
object MotionDuration {
    /** 卡片内的小位移：翻答案、下一张卡。 */
    const val Short = 160
    /** 返回、退出：比进入略快，跟手感更干脆。 */
    const val Medium = 260
    /** 推入子页面。 */
    const val Long = 320
    /** 会话层从底部升起。 */
    const val Session = 380
}

/** 动效曲线 token（Material 3 Emphasized 系列）。 */
object MotionEasing {
    /** 进入：起步快、收尾很长，页面「落」到位。 */
    val EmphasizedDecelerate: Easing = CubicBezierEasing(0.05f, 0.7f, 0.1f, 1f)
    /** 离开：起步慢、末段加速，页面「被拿走」。 */
    val EmphasizedAccelerate: Easing = CubicBezierEasing(0.3f, 0f, 0.8f, 0.15f)
    /** 返回推出：比 Accelerate 起步更快，避免按返回后有一拍停顿。 */
    val Standard: Easing = CubicBezierEasing(0.2f, 0f, 0f, 1f)
}
