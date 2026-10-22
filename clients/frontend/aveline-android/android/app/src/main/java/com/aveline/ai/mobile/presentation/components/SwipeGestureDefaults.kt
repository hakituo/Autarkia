package com.aveline.ai.mobile.presentation.components

import androidx.compose.ui.unit.dp

/**
 * 横向跟手手势的统一参数真源。
 *
 * 全局侧边栏（[PullableNavigationDrawer]）与伴侣详情面板（[PullableDismissPanel]）
 * 是同一类交互：手指位移直接驱动锚点、松手按速度/比例吸附。两者必须共用同一组阈值，
 * 否则会出现"侧边栏很顺滑、面板发木"的手感落差，也会让后续调参各改各的。
 */
object SwipeGestureDefaults {

    /** 松手吸附的位移比例阈值：拖动超过容器宽度的 12% 即吸向目标锚点。 */
    const val POSITIONAL_THRESHOLD_RATIO = 0.12f

    /** 甩动吸附的速度阈值。 */
    val VelocityThreshold = 125.dp

    /** 横向位移相对纵向位移的最小占比；低于此值视为纵向滚动，不抢手势。 */
    const val HORIZONTAL_DOMINANCE_RATIO = 1.2f
}
