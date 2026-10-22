@file:OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class)

package com.aveline.ai.mobile.presentation.components

import androidx.compose.foundation.gestures.AnchoredDraggableDefaults
import androidx.compose.foundation.gestures.AnchoredDraggableState
import androidx.compose.foundation.gestures.DraggableAnchors
import androidx.compose.foundation.gestures.Orientation
import androidx.compose.foundation.gestures.anchoredDraggable
import androidx.compose.foundation.gestures.animateTo
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.nestedscroll.NestedScrollConnection
import androidx.compose.ui.input.nestedscroll.NestedScrollSource
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Velocity
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlin.math.abs

/** 判定"面板已完全隐藏"的位移容差（px）：吸附动画的终点可能有亚像素误差。 */
private const val HIDDEN_OFFSET_EPSILON_PX = 0.5f

internal enum class DismissPanelValue {
    Visible,
    Dismissed
}

@Stable
class PullableDismissPanelState internal constructor(
    private val dragState: AnchoredDraggableState<DismissPanelValue>
) {
    internal val anchoredState: AnchoredDraggableState<DismissPanelValue>
        get() = dragState

    suspend fun show() {
        dragState.animateTo(DismissPanelValue.Visible)
    }

    suspend fun dismiss() {
        dragState.animateTo(DismissPanelValue.Dismissed)
    }

    /** 把聊天页的左滑位移交给与详情页退出手势相同的锚点状态。 */
    fun dispatchOpeningDelta(deltaX: Float): Float {
        return dragState.dispatchRawDelta(deltaX)
    }

    /**
     * 打开手势松开后的吸附判定。
     *
     * 返回 true 表示停在详情页，false 表示回到屏幕右侧隐藏位置。
     */
    suspend fun settleOpeningDrag(
        releaseVelocityX: Float,
        panelWidthPx: Float,
        velocityThresholdPx: Float
    ): Boolean {
        val offset = dragState.offset
        if (offset.isNaN() || panelWidthPx <= 0f) return false
        val revealProgress = ((panelWidthPx - offset) / panelWidthPx).coerceIn(0f, 1f)
        val target = when {
            releaseVelocityX <= -velocityThresholdPx -> DismissPanelValue.Visible
            releaseVelocityX >= velocityThresholdPx -> DismissPanelValue.Dismissed
            revealProgress >= SwipeGestureDefaults.POSITIONAL_THRESHOLD_RATIO ->
                DismissPanelValue.Visible
            else -> DismissPanelValue.Dismissed
        }
        dragState.animateTo(target)
        return target == DismissPanelValue.Visible
    }
}

@Composable
fun rememberPullableDismissPanelState(): PullableDismissPanelState {
    return remember {
        PullableDismissPanelState(
            AnchoredDraggableState(initialValue = DismissPanelValue.Dismissed)
        )
    }
}

/**
 * 从右侧退出的全屏跟手面板。
 *
 * 直接右滑由 anchoredDraggable 驱动；内部 HorizontalPager 位于第一页时，未消费的
 * 右滑通过 NestedScroll 接力到同一状态。面板整体跟随手指，松手后再吸附或退出。
 *
 * @param onDismissed 面板真正回到隐藏位置（彻底离开屏幕）时回调
 * @param onRevealed 面板离开隐藏位置（开始/已经展示）时回调，供调用方同步"可见"标记
 */
@Composable
fun PullableDismissPanel(
    state: PullableDismissPanelState,
    onDismissed: () -> Unit,
    onRevealed: () -> Unit = {},
    gesturesEnabled: Boolean = true,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit
) {
    BoxWithConstraints(modifier = modifier.fillMaxSize()) {
        val density = LocalDensity.current
        val panelWidthPx = with(density) { maxWidth.toPx() }
        val velocityThresholdPx = with(density) { SwipeGestureDefaults.VelocityThreshold.toPx() }
        val anchors = remember(panelWidthPx) {
            DraggableAnchors {
                DismissPanelValue.Visible at 0f
                DismissPanelValue.Dismissed at panelWidthPx
            }
        }
        SideEffect {
            state.anchoredState.updateAnchors(anchors)
        }

        val latestOnDismissed by rememberUpdatedState(onDismissed)
        val latestOnRevealed by rememberUpdatedState(onRevealed)
        val latestPanelWidthPx by rememberUpdatedState(panelWidthPx)

        // 可见性只认 offset（面板真实位置），不再依赖 settledValue：
        // settledValue 仅在用户手势 settle 完成时更新，animateTo() 被新手势/新动画取消时不会变化。
        // 旧实现按 settledValue 的"值变化"边沿触发，一旦某次展开动画被打断，
        // Dismissed -> Dismissed 不构成状态跳变，onDismissed 永远不会回调，
        // 调用方的 visible 就永久停在 true（返回键被 BackHandler 吞掉、左滑再也打不开详情）。
        // 改成电平触发后，"此刻是否停在隐藏锚点"每次都会被重新判定，不依赖跳变。
        LaunchedEffect(state) {
            var hasBeenRevealed = false
            snapshotFlow {
                val offset = state.anchoredState.offset
                val width = latestPanelWidthPx
                offset.isNaN() || width <= 0f || offset >= width - HIDDEN_OFFSET_EPSILON_PX
            }
                .distinctUntilChanged()
                .collect { hidden ->
                    if (hidden) {
                        // 首次以隐藏锚点加入组合树时不回调；只有真正展示过再回到隐藏位才关闭覆盖层。
                        if (hasBeenRevealed) {
                            hasBeenRevealed = false
                            latestOnDismissed()
                        }
                    } else {
                        hasBeenRevealed = true
                        latestOnRevealed()
                    }
                }
        }

        val flingBehavior = AnchoredDraggableDefaults.flingBehavior(
            state = state.anchoredState,
            // 与全局侧边栏共用同一比例：详情页是整屏宽，12% 约 45dp 即可退出，
            // 和 Pager 翻页/轻推的力度接近。
            positionalThreshold = { distance ->
                distance * SwipeGestureDefaults.POSITIONAL_THRESHOLD_RATIO
            }
        )
        val nestedScrollConnection = remember(
            state,
            panelWidthPx,
            velocityThresholdPx,
            gesturesEnabled
        ) {
            object : NestedScrollConnection {
                private var originalFlingVelocityX = 0f

                override fun onPreScroll(
                    available: Offset,
                    source: NestedScrollSource
                ): Offset {
                    val offset = state.anchoredState.offset
                    val panelHasMoved = !offset.isNaN() && offset > 0.5f
                    val isHorizontal = abs(available.x) >
                        abs(available.y) * SwipeGestureDefaults.HORIZONTAL_DOMINANCE_RATIO
                    if (!gesturesEnabled || source != NestedScrollSource.UserInput ||
                        !panelHasMoved || !isHorizontal
                    ) {
                        return Offset.Zero
                    }
                    val consumedX = state.anchoredState.dispatchRawDelta(available.x)
                    return Offset(consumedX, 0f)
                }

                override fun onPostScroll(
                    consumed: Offset,
                    available: Offset,
                    source: NestedScrollSource
                ): Offset {
                    if (source != NestedScrollSource.UserInput || available.x <= 0f) {
                        return Offset.Zero
                    }
                    if (abs(available.x) <=
                        abs(available.y) * SwipeGestureDefaults.HORIZONTAL_DOMINANCE_RATIO
                    ) {
                        return Offset.Zero
                    }
                    if (!gesturesEnabled) {
                        // 面板还停在屏幕上、但当前不允许退出（Pager 尚未稳定在首页）时，
                        // 这段右滑必须就地吸收。返回 Zero 会让位移继续冒泡给外层的
                        // PullableNavigationDrawer，用户看到的就是"右滑把全局侧边栏拉出来了"。
                        val offset = state.anchoredState.offset
                        val panelOnScreen = !offset.isNaN() && panelWidthPx > 0f &&
                            offset < panelWidthPx - HIDDEN_OFFSET_EPSILON_PX
                        return if (panelOnScreen) Offset(available.x, 0f) else Offset.Zero
                    }
                    val consumedX = state.anchoredState.dispatchRawDelta(available.x)
                    return Offset(consumedX, 0f)
                }

                override suspend fun onPostFling(
                    consumed: Velocity,
                    available: Velocity
                ): Velocity {
                    if (!gesturesEnabled) {
                        originalFlingVelocityX = 0f
                        return Velocity.Zero
                    }
                    val offset = state.anchoredState.offset
                    if (offset.isNaN() || panelWidthPx <= 0f) return Velocity.Zero
                    val progress = (offset / panelWidthPx).coerceIn(0f, 1f)
                    val releaseVelocityX = if (
                        abs(originalFlingVelocityX) > abs(available.x)
                    ) {
                        originalFlingVelocityX
                    } else {
                        available.x
                    }
                    originalFlingVelocityX = 0f
                    val target = when {
                        releaseVelocityX >= velocityThresholdPx -> DismissPanelValue.Dismissed
                        releaseVelocityX <= -velocityThresholdPx -> DismissPanelValue.Visible
                        progress >= SwipeGestureDefaults.POSITIONAL_THRESHOLD_RATIO ->
                            DismissPanelValue.Dismissed
                        else -> DismissPanelValue.Visible
                    }
                    state.anchoredState.animateTo(target)
                    return available
                }

                override suspend fun onPreFling(available: Velocity): Velocity {
                    if (!gesturesEnabled) {
                        originalFlingVelocityX = 0f
                        return Velocity.Zero
                    }
                    originalFlingVelocityX = available.x
                    return Velocity.Zero
                }
            }
        }

        Box(
            modifier = Modifier
                .fillMaxSize()
                .graphicsLayer {
                    // 锚点首帧尚未安装时也保持在屏幕右侧，避免常驻面板短暂闪现。
                    translationX = state.anchoredState.offset.takeUnless { it.isNaN() }
                        ?: panelWidthPx
                }
                .nestedScroll(nestedScrollConnection)
                .anchoredDraggable(
                    state = state.anchoredState,
                    orientation = Orientation.Horizontal,
                    flingBehavior = flingBehavior,
                    enabled = gesturesEnabled
                )
        ) {
            content()
        }
    }
}
