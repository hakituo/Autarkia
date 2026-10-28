package com.aveline.ai.mobile.presentation.study.vocab

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.ContentTransform
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.slideOutVertically
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.aveline.ai.mobile.presentation.components.controls.AvelineButton
import com.aveline.ai.mobile.presentation.components.controls.AvelineButtonVariant
import com.aveline.ai.mobile.presentation.components.controls.AvelineIconButton
import com.aveline.ai.mobile.presentation.study.DailyWord
import com.aveline.ai.mobile.presentation.study.VocabUiState
import com.aveline.ai.mobile.presentation.study.consumeTouches
import com.aveline.ai.mobile.presentation.study.formatVocabularyElapsed
import com.aveline.ai.mobile.presentation.theme.Edge
import com.aveline.ai.mobile.presentation.theme.Line
import com.aveline.ai.mobile.presentation.theme.MotionDuration
import com.aveline.ai.mobile.presentation.theme.MotionEasing
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import kotlinx.coroutines.flow.StateFlow

/**
 * 复习会话（全屏）。
 *
 * 问题面只保留「新词/复习」小字、单词和音标；答案面用细线与字号分层，
 * 评分按钮不靠四种颜色区分：【认识】实心，【不认识】危险色文字，其余描边。
 *
 * @param elapsedSeconds 当前会话累计前台秒数（只在这里 collect，避免每秒重组学习页）
 * @param onSubmitReview 提交评分（"1"=不认识 "2"=模糊 "3"=认识 "4"=太简单）
 */
@Composable
fun VocabReviewScreen(
    uiState: VocabUiState,
    elapsedSeconds: StateFlow<Int>,
    onSetShowAnswer: (Boolean) -> Unit,
    onSubmitReview: (String) -> Unit,
    onSetIsReviewMode: (Boolean) -> Unit
) {
    val elapsed by elapsedSeconds.collectAsStateWithLifecycle()
    val currentWord = uiState.learnWords.getOrNull(uiState.currentCardIndex)

    if (currentWord == null) {
        VocabReviewEmptyState(
            isNewWordsMode = uiState.isNewWordsMode,
            onExit = { onSetIsReviewMode(false) }
        )
        return
    }

    val progressTarget = if (uiState.learnWords.isEmpty()) {
        0f
    } else {
        (uiState.currentCardIndex + 1f) / uiState.learnWords.size
    }
    val progress by animateFloatAsState(
        targetValue = progressTarget,
        animationSpec = tween(MotionDuration.Medium, easing = MotionEasing.Standard),
        label = "vocab_review_progress"
    )

    // 「不认识」会把当前词复制到队尾：队列变长且索引前进，即为放回队尾
    val lastQueueSize = remember { intArrayOf(uiState.learnWords.size) }
    val requeued = uiState.learnWords.size > lastQueueSize[0]
    SideEffect { lastQueueSize[0] = uiState.learnWords.size }

    val density = LocalDensity.current
    val cardShiftPx = with(density) { 24.dp.roundToPx() }
    val requeueShiftPx = with(density) { 16.dp.roundToPx() }
    val revealShiftPx = with(density) { 12.dp.roundToPx() }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
    ) {
        ReviewTopBar(
            progress = progress,
            currentIndex = uiState.currentCardIndex,
            total = uiState.learnWords.size,
            onClose = { onSetIsReviewMode(false) }
        )
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = 20.dp, end = 20.dp, top = 4.dp),
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Text(
                text = formatVocabularyElapsed(elapsed),
                style = VocabMonoStyle,
                color = TextTertiary
            )
            Text(
                text = "连对 ${uiState.sessionStats?.streak ?: 0}",
                style = VocabMonoStyle,
                color = TextTertiary
            )
        }

        // 只认索引变化做卡片切换动画；requeued 只决定这一次往哪边走
        AnimatedContent(
            targetState = ReviewCardStep(uiState.currentCardIndex, requeued),
            contentKey = { it.index },
            transitionSpec = { cardTransform(targetState.requeued, cardShiftPx, requeueShiftPx) },
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth(),
            label = "vocab_card"
        ) { step ->
            val word = uiState.learnWords.getOrNull(step.index) ?: return@AnimatedContent
            val isCurrent = step.index == uiState.currentCardIndex
            // 离场的旧卡保持在答案面滑走，不在半路翻回问题面
            ReviewCard(
                word = word,
                answerShown = !isCurrent || uiState.showAnswer,
                revealShiftPx = revealShiftPx,
                onReveal = { onSetShowAnswer(true) },
                onSubmitReview = onSubmitReview,
                modifier = Modifier.consumeTouches(!isCurrent)
            )
        }
    }
}

/** 卡片切换的 key：[requeued] 表示上一张点了「不认识」被放回队尾。 */
private data class ReviewCardStep(val index: Int, val requeued: Boolean)

/** 下一张：旧卡左移淡出、新卡从右侧移入；放回队尾的旧卡改为向下沉，暗示「放回去了」。 */
private fun cardTransform(requeued: Boolean, shiftPx: Int, requeueShiftPx: Int): ContentTransform {
    val move = tween<IntOffset>(MotionDuration.Short, easing = MotionEasing.EmphasizedDecelerate)
    val fade = tween<Float>(MotionDuration.Short)
    val exit = if (requeued) {
        slideOutVertically(move) { requeueShiftPx } + fadeOut(fade)
    } else {
        slideOutHorizontally(move) { -shiftPx } + fadeOut(fade)
    }
    return (slideInHorizontally(move) { shiftPx } + fadeIn(fade)) togetherWith exit
}

@Composable
private fun ReviewCard(
    word: DailyWord,
    answerShown: Boolean,
    revealShiftPx: Int,
    onReveal: () -> Unit,
    onSubmitReview: (String) -> Unit,
    modifier: Modifier = Modifier
) {
    // 翻答案：答案区和评分栏一起从下方 12dp 浮上来；问题面快速让开。不做 3D 翻转。
    AnimatedContent(
        targetState = answerShown,
        transitionSpec = {
            if (targetState) {
                (
                    slideInVertically(
                        tween(MotionDuration.Short, easing = MotionEasing.EmphasizedDecelerate)
                    ) { revealShiftPx } + fadeIn(tween(MotionDuration.Short))
                    ) togetherWith fadeOut(tween(90))
            } else {
                fadeIn(tween(MotionDuration.Short)) togetherWith fadeOut(tween(90))
            }
        },
        modifier = modifier.fillMaxSize(),
        label = "vocab_reveal"
    ) { shown ->
        Column(modifier = Modifier.fillMaxSize()) {
            if (shown) {
                VocabAnswerFace(
                    word = word,
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxWidth()
                )
                GradeBar(onSubmitReview = onSubmitReview)
            } else {
                QuestionFace(
                    word = word,
                    modifier = Modifier.weight(1f),
                    onReveal = onReveal
                )
                ShowAnswerButton(onClick = onReveal)
            }
        }
    }
}

@Composable
private fun ShowAnswerButton(onClick: () -> Unit) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 20.dp)
            .padding(bottom = 24.dp)
            .navigationBarsPadding()
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(56.dp)
                .clip(RoundedCornerShape(16.dp))
                .border(1.dp, Edge, RoundedCornerShape(16.dp))
                .clickable(onClick = onClick),
            contentAlignment = Alignment.Center
        ) {
            Text(
                text = "显示答案",
                fontSize = 15.5.sp,
                fontWeight = FontWeight.Medium,
                color = TextPrimary
            )
        }
    }
}

@Composable
private fun ReviewTopBar(
    progress: Float,
    currentIndex: Int,
    total: Int,
    onClose: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(start = 8.dp, end = 12.dp, top = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        AvelineIconButton(
            icon = Icons.Default.Close,
            contentDescription = "关闭复习",
            onClick = onClose
        )
        Box(
            modifier = Modifier
                .weight(1f)
                .height(3.dp)
                .clip(RoundedCornerShape(2.dp))
                .background(Line)
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth(progress.coerceIn(0f, 1f))
                    .height(3.dp)
                    .background(TextPrimary)
            )
        }
        Text(
            text = "${currentIndex + 1} / $total",
            style = VocabMonoStyle.copy(fontSize = 12.sp, color = TextSecondary),
            maxLines = 1
        )
    }
}

@Composable
private fun QuestionFace(
    word: DailyWord,
    modifier: Modifier = Modifier,
    onReveal: () -> Unit
) {
    Box(
        modifier = modifier
            .fillMaxWidth()
            .clickable(onClick = onReveal)
            .padding(horizontal = 24.dp),
        contentAlignment = Alignment.Center
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(14.dp)
        ) {
            Text(
                text = if (word.status == "new") "新词" else "复习",
                fontSize = 12.5.sp,
                color = TextTertiary
            )
            Text(
                text = word.word,
                fontSize = reviewWordSize(word.word),
                fontWeight = FontWeight.Medium,
                letterSpacing = (-1).sp,
                color = TextPrimary,
                textAlign = TextAlign.Center
            )
            PhoneticsRow(word = word, fontSize = 14.sp)
        }
    }
}

/** 音标只在后端有值时展示，避免出现空的「美 //」。 */
@Composable
internal fun PhoneticsRow(word: DailyWord, fontSize: TextUnit) {
    val phonetics = remember(word.us, word.uk) {
        listOfNotNull(
            word.us?.takeIf { it.isNotBlank() }?.let { "美 /$it/" },
            word.uk?.takeIf { it.isNotBlank() }?.let { "英 /$it/" }
        )
    }
    if (phonetics.isEmpty()) return
    Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
        phonetics.forEach { text ->
            Text(text = text, fontSize = fontSize, color = TextSecondary)
        }
    }
}

@Composable
private fun VocabReviewEmptyState(
    isNewWordsMode: Boolean,
    onExit: () -> Unit
) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .padding(24.dp),
        contentAlignment = Alignment.Center
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                text = if (isNewWordsMode) "当前词书没有新词了" else "没有待复习的词汇",
                fontSize = 15.sp,
                color = TextSecondary
            )
            Spacer(modifier = Modifier.height(16.dp))
            AvelineButton(
                text = "返回",
                onClick = onExit,
                variant = AvelineButtonVariant.Secondary
            )
        }
    }
}
