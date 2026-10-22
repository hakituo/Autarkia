package com.aveline.ai.mobile.presentation.chat

import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.util.VelocityTracker
import com.aveline.ai.mobile.presentation.components.HorizontalContentGestureState
import com.aveline.ai.mobile.presentation.components.PullableDismissPanelState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import kotlin.math.abs

/**
 * 聊天页"向左滑打开伴侣详情面板"的手势。
 *
 * 面板常驻组合树并停在屏幕右侧隐藏锚点，因此方向锁定后可以把手指位移直接派发给面板状态，
 * 松手时再按速度或展开进度吸附。
 *
 * @param screenWidthPx 屏幕宽度（px），用于判断起手位置与吸附阈值
 * @param touchSlopPx 方向判定的最小位移（px）
 * @param openVelocityThresholdPx 判定为"打开"的甩动速度阈值（px/s）
 * @param edgeReservedRatio 左侧留给侧边栏的宽度比例，起手落在其中不触发本手势
 * @param horizontalContentGestureState 表格/代码块/宽公式会声明手势所有权，声明后不再抢左滑
 * @param panelState 伴侣面板的锚点状态
 * @param isGestureEnabled 是否允许本次手势。聊天 IME 显示期间应返回 false，避免打字时误开侧面板。
 * @param isPanelVisible 面板当前是否已展开；展开中不再重复触发。
 *        必须是 lambda 而不是 Boolean：pointerInput 的 lambda 只会在 key 变化时重建，
 *        传值会把"首次组合时的快照"固化下来，面板打开后依旧按未打开处理（会重复派发位移）。
 * @param onOpeningStarted 方向锁定为"打开面板"时回调（用于把面板挂进组合树）
 * @param onOpenFailed 松手后未达到展开条件时回调
 * @param settleScope 吸附动画用的协程作用域（AwaitPointerEventScope 是受限协程，不能直接启动动画）
 */
fun Modifier.companionPanelSwipeGesture(
    screenWidthPx: Float,
    touchSlopPx: Float,
    openVelocityThresholdPx: Float,
    edgeReservedRatio: Float = COMPANION_GESTURE_EDGE_RESERVED_RATIO,
    horizontalContentGestureState: HorizontalContentGestureState,
    panelState: PullableDismissPanelState,
    isGestureEnabled: () -> Boolean = { true },
    isPanelVisible: () -> Boolean,
    onOpeningStarted: () -> Unit,
    onOpenFailed: () -> Unit,
    settleScope: CoroutineScope
): Modifier = this.pointerInput(
    screenWidthPx,
    touchSlopPx,
    openVelocityThresholdPx,
    edgeReservedRatio
) {
    awaitEachGesture {
        val down = awaitFirstDown(requireUnconsumed = false)
        if (!isGestureEnabled()) return@awaitEachGesture

        val startX = down.position.x
        val startY = down.position.y
        // 左边缘起手留给 MainActivity 内容根节点的手势仲裁，
        // 避免与侧边栏右滑手势争抢方向。
        if (startX <= screenWidthPx * edgeReservedRatio) return@awaitEachGesture

        // 和 anchoredDraggable 内部一致：用多帧拟合的 VelocityTracker 求松手速度。
        // 旧实现取"最后一帧 delta / dt"，手指抬起前只要减速就退化成接近 0，
        // 吸附只能靠位移比例兜底，主观手感就是"推了没反应、卡一下"。
        val velocityTracker = VelocityTracker()
        velocityTracker.addPosition(down.uptimeMillis, down.position)

        var decided = false
        var lastX = startX
        var childConsumedHorizontalDrag = false
        var openingDragStarted = false
        while (true) {
            val event = awaitPointerEvent()
            // 固定跟踪按下时的那根手指：多指场景下取 firstOrNull 会让位移和速度一起跳变。
            val change = event.changes.firstOrNull { it.id == down.id } ?: break
            velocityTracker.addPosition(change.uptimeMillis, change.position)
            if (!isGestureEnabled()) {
                if (openingDragStarted) {
                    onOpenFailed()
                }
                break
            }
            val dx = change.position.x - startX
            val dy = change.position.y - startY
            val deltaX = change.position.x - lastX
            // 只有表格/代码块/宽公式会显式声明手势所有权。
            // 不再使用通用 isConsumed，避免 clickable/LazyColumn 屏蔽页面左滑。
            if (horizontalContentGestureState.isActive) {
                childConsumedHorizontalDrag = true
            }
            if (!decided && (abs(dx) > touchSlopPx || abs(dy) > touchSlopPx)) {
                // 左滑（dx < 0）且主要在水平方向，且面板未打开。
                if (dx < 0f && abs(dx) >= abs(dy) && !isPanelVisible() && !childConsumedHorizontalDrag) {
                    // anchoredDraggable 是"越过 slop 之后"才开始跟手，这里同样只补
                    // 超出 slop 的部分，面板起手位移曲线才和侧边栏一致，不会先蹿一下。
                    onOpeningStarted()
                    panelState.dispatchOpeningDelta(dx + touchSlopPx)
                    openingDragStarted = true
                    change.consume()
                }
                decided = true
            } else if (openingDragStarted) {
                panelState.dispatchOpeningDelta(deltaX)
                change.consume()
            }
            lastX = change.position.x
            if (event.changes.all { !it.pressed }) break
        }
        if (openingDragStarted && isGestureEnabled()) {
            // 先算速度再进入动画协程：VelocityTracker 是手势内的可变对象，
            // 不应跨协程边界延迟读取。
            val releaseVelocityX = velocityTracker.calculateVelocity().x
            // AwaitPointerEventScope 是受限协程；吸附动画交给普通 UI 协程执行。
            settleScope.launch {
                val opened = panelState.settleOpeningDrag(
                    releaseVelocityX = releaseVelocityX,
                    panelWidthPx = screenWidthPx,
                    velocityThresholdPx = openVelocityThresholdPx
                )
                if (!opened) onOpenFailed()
            }
        }
    }
}

/** 聊天内容区左侧留给侧边栏手势的宽度比例。 */
const val COMPANION_GESTURE_EDGE_RESERVED_RATIO = 0.12f
