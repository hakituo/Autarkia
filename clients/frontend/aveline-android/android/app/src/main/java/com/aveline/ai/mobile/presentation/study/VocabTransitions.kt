package com.aveline.ai.mobile.presentation.study

import androidx.compose.animation.AnimatedVisibilityScope
import androidx.compose.animation.ContentTransform
import androidx.compose.animation.EnterExitState
import androidx.compose.animation.core.FiniteAnimationSpec
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.slideOutVertically
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.State
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.presentation.theme.Background
import com.aveline.ai.mobile.presentation.theme.MotionDuration
import com.aveline.ai.mobile.presentation.theme.MotionEasing
import com.aveline.ai.mobile.presentation.theme.Scrim

/**
 * 词汇全屏层的页面与转场规则。
 *
 * 两种层级、两种手感：
 * - 子页面（词书列表 / 详情 / 错题本）从右侧整屏推入，底下那页向左让出 30% 并压暗；
 * - 背词会话（复习 / 结算）从底部升起，底下那页原地缩到 0.94 并压暗，像拿起一张卡。
 *
 * 全程不做整页淡入淡出：页面始终不透明，层次靠位移、缩放和遮罩表达。
 */
internal enum class VocabLayer { Base, Push, Session }

/** 宿主内的页面。[depth] 只用于同为子页面时判断前进还是后退。 */
internal enum class VocabScreen(val layer: VocabLayer, val depth: Int) {
    HOME(VocabLayer.Base, 0),
    BOOK_LIST(VocabLayer.Push, 1),
    MISTAKES(VocabLayer.Push, 1),
    BOOK_DETAIL(VocabLayer.Push, 2),
    REVIEW(VocabLayer.Session, 3),
    SUMMARY(VocabLayer.Session, 3)
}

internal enum class VocabMove { PushForward, PushBack, SessionOpen, SessionClose }

/** 上层盖住下层时，下层最终的压暗程度。 */
private const val SCRIM_ALPHA = 0.5f
/** 推入时底下那页让出的比例。 */
private const val PUSH_PARALLAX = 0.3f
/** 会话升起时底下那页缩到的比例。 */
private const val SESSION_BASE_SCALE = 0.94f

/** 当前应展示哪一页（复习 > 结算 > 子页面 > 主页）。 */
internal fun resolveVocabScreen(uiState: VocabUiState, sub: VocabSubScreen): VocabScreen = when {
    uiState.isReviewMode -> VocabScreen.REVIEW
    uiState.sessionSummary != null -> VocabScreen.SUMMARY
    sub == VocabSubScreen.BOOK_DETAIL -> VocabScreen.BOOK_DETAIL
    sub == VocabSubScreen.BOOK_LIST -> VocabScreen.BOOK_LIST
    sub == VocabSubScreen.MISTAKES -> VocabScreen.MISTAKES
    else -> VocabScreen.HOME
}

internal fun vocabMove(from: VocabScreen, to: VocabScreen): VocabMove = when {
    to.layer == VocabLayer.Session && from.layer != VocabLayer.Session -> VocabMove.SessionOpen
    from.layer == VocabLayer.Session && to.layer != VocabLayer.Session -> VocabMove.SessionClose
    // 复习 ↔ 结算是同一个会话里的「下一步」，两个方向都按前进推入
    from.layer == VocabLayer.Session -> VocabMove.PushForward
    to.depth > from.depth -> VocabMove.PushForward
    else -> VocabMove.PushBack
}

/** 这次切换是否是「新页盖到旧页上」。 */
private val VocabMove.covers: Boolean
    get() = this == VocabMove.PushForward || this == VocabMove.SessionOpen

private fun <T> moveSpec(move: VocabMove): FiniteAnimationSpec<T> = when (move) {
    VocabMove.PushForward -> tween(MotionDuration.Long, easing = MotionEasing.EmphasizedDecelerate)
    VocabMove.SessionOpen -> tween(MotionDuration.Session, easing = MotionEasing.EmphasizedDecelerate)
    VocabMove.PushBack, VocabMove.SessionClose -> tween(MotionDuration.Medium, easing = MotionEasing.Standard)
}

internal fun vocabTransform(move: VocabMove): ContentTransform = when (move) {
    VocabMove.PushForward -> (
        slideInHorizontally(moveSpec(move)) { it } togetherWith
            slideOutHorizontally(moveSpec(move)) { -(it * PUSH_PARALLAX).toInt() }
        ).apply { targetContentZIndex = 1f }

    VocabMove.PushBack -> (
        slideInHorizontally(moveSpec(move)) { -(it * PUSH_PARALLAX).toInt() } togetherWith
            slideOutHorizontally(moveSpec(move)) { it }
        ).apply { targetContentZIndex = -1f }

    VocabMove.SessionOpen -> (
        slideInVertically(moveSpec(move)) { it } togetherWith
            scaleOut(moveSpec(move), targetScale = SESSION_BASE_SCALE)
        ).apply { targetContentZIndex = 1f }

    // 关闭会话：卡片向下收走，用加速曲线；底下那页用标准曲线放大回位
    VocabMove.SessionClose -> (
        scaleIn(moveSpec(move), initialScale = SESSION_BASE_SCALE) togetherWith
            slideOutVertically(
                tween(MotionDuration.Medium, easing = MotionEasing.EmphasizedAccelerate)
            ) { it }
        ).apply { targetContentZIndex = -1f }
}

/**
 * 宿主里每一页的外壳：不透明底色 + 被盖住时的遮罩 + 离场时吞掉点击。
 *
 * @param move 最近一次切换的方向，决定遮罩在进场还是离场时出现
 */
@Composable
internal fun AnimatedVisibilityScope.VocabPage(
    move: VocabMove,
    content: @Composable () -> Unit
) {
    val dim = transition.animateFloat(
        transitionSpec = { moveSpec(move) },
        label = "vocab_page_dim"
    ) { state ->
        when (state) {
            EnterExitState.PreEnter -> if (move.covers) 0f else SCRIM_ALPHA
            EnterExitState.Visible -> 0f
            EnterExitState.PostExit -> if (move.covers) SCRIM_ALPHA else 0f
        }
    }
    val leaving = transition.targetState == EnterExitState.PostExit
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Background)
            .consumeTouches(leaving)
            .drawWithContent {
                drawContent()
                val alpha = dim.value
                if (alpha > 0f) drawRect(Scrim, alpha = alpha)
            }
    ) {
        content()
    }
}

/** 动画中离场的页面不再响应点击，避免连点穿透到正在退出的按钮。 */
internal fun Modifier.consumeTouches(enabled: Boolean): Modifier =
    if (!enabled) {
        this
    } else {
        pointerInput(Unit) {
            awaitPointerEventScope {
                while (true) {
                    awaitPointerEvent(PointerEventPass.Initial).changes.forEach { it.consume() }
                }
            }
        }
    }

/**
 * 学习页本体（词汇主页所在层）被全屏层盖住时的姿态。
 *
 * 主页不在宿主的 AnimatedContent 里，所以单独跟随：推入时左移，会话时缩小并圆角，
 * 同时在它上面压一层遮罩。退出时沿用最后一次盖住它的层级，保证收回动作与打开对称。
 */
internal class VocabBaseCover(
    private val progress: State<Float>,
    private val layer: State<VocabLayer>
) {
    val covered: Boolean get() = progress.value > 0f

    /** 套在学习页本体上。 */
    fun Modifier.basePose(): Modifier = graphicsLayer {
        val p = progress.value
        if (p <= 0f) return@graphicsLayer
        if (layer.value == VocabLayer.Session) {
            val scale = 1f - (1f - SESSION_BASE_SCALE) * p
            scaleX = scale
            scaleY = scale
            shape = RoundedCornerShape((20 * p).dp)
            clip = true
        } else {
            translationX = -size.width * PUSH_PARALLAX * p
        }
    }

    /** 盖在学习页本体上的遮罩，被盖住期间吞掉点击。 */
    @Composable
    fun ScrimLayer(modifier: Modifier = Modifier) {
        Box(
            modifier = modifier
                .fillMaxSize()
                .consumeTouches(covered)
                .drawWithContent {
                    val alpha = progress.value * SCRIM_ALPHA
                    if (alpha > 0f) drawRect(Scrim, alpha = alpha)
                }
        )
    }
}

@Composable
internal fun rememberVocabBaseCover(screen: VocabScreen): VocabBaseCover =
    rememberLayerCover(
        covered = screen != VocabScreen.HOME,
        layer = screen.layer,
        label = "vocab_base_cover"
    )

/**
 * 通用的「下层被盖住」姿态：[covered] 为 true 时按 [layer] 让位（推入左移 / 会话缩小）并压暗。
 * 学习页的二级板块、笔记阅读页、词汇全屏层都用这一套，手感一致。
 */
@Composable
internal fun rememberLayerCover(
    covered: Boolean,
    layer: VocabLayer = VocabLayer.Push,
    label: String = "layer_cover"
): VocabBaseCover {
    val lastLayer = remember { mutableStateOf(VocabLayer.Push) }
    SideEffect { if (covered) lastLayer.value = layer }
    val openMove = if (layer == VocabLayer.Session) VocabMove.SessionOpen else VocabMove.PushForward
    val progress = animateFloatAsState(
        targetValue = if (covered) 1f else 0f,
        animationSpec = moveSpec(if (covered) openMove else VocabMove.PushBack),
        label = label
    )
    return remember { VocabBaseCover(progress, lastLayer) }
}
