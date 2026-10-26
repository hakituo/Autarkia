package com.aveline.ai.mobile.presentation.study.vocab

import androidx.compose.animation.core.animateFloatAsState
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
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.aveline.ai.mobile.presentation.components.controls.AvelineButton
import com.aveline.ai.mobile.presentation.components.controls.AvelineButtonVariant
import com.aveline.ai.mobile.presentation.components.controls.AvelineIconButton
import com.aveline.ai.mobile.presentation.study.DailyWord
import com.aveline.ai.mobile.presentation.study.VocabUiState
import com.aveline.ai.mobile.presentation.study.formatVocabularyElapsed
import com.aveline.ai.mobile.presentation.theme.Background
import com.aveline.ai.mobile.presentation.theme.Danger
import com.aveline.ai.mobile.presentation.theme.Edge
import com.aveline.ai.mobile.presentation.theme.Line
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
        label = "vocab_review_progress"
    )

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

        if (!uiState.showAnswer) {
            QuestionFace(
                word = currentWord,
                modifier = Modifier.weight(1f),
                onReveal = { onSetShowAnswer(true) }
            )
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
                        .clickable { onSetShowAnswer(true) },
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
        } else {
            VocabAnswerFace(
                word = currentWord,
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
            )
            GradeBar(onSubmitReview = onSubmitReview)
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

/** 评分区：四个按钮等宽，只有【认识】是实心。 */
@Composable
private fun GradeBar(onSubmitReview: (String) -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .navigationBarsPadding()
            .padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 24.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        GradeButton(
            label = "不认识",
            sub = "本轮再背",
            style = VocabGradeStyle.Danger,
            modifier = Modifier.weight(1f),
            onClick = { onSubmitReview("1") }
        )
        GradeButton(
            label = "模糊",
            sub = "明天优先",
            style = VocabGradeStyle.Normal,
            modifier = Modifier.weight(1f),
            onClick = { onSubmitReview("2") }
        )
        GradeButton(
            label = "认识",
            sub = "间隔复习",
            style = VocabGradeStyle.Primary,
            modifier = Modifier.weight(1f),
            onClick = { onSubmitReview("3") }
        )
        GradeButton(
            label = "太简单",
            sub = "延后复习",
            style = VocabGradeStyle.Normal,
            modifier = Modifier.weight(1f),
            onClick = { onSubmitReview("4") }
        )
    }
}

private enum class VocabGradeStyle { Danger, Normal, Primary }

@Composable
private fun GradeButton(
    label: String,
    sub: String,
    style: VocabGradeStyle,
    modifier: Modifier = Modifier,
    onClick: () -> Unit
) {
    val shape = RoundedCornerShape(14.dp)
    val background = if (style == VocabGradeStyle.Primary) TextPrimary else Color.Transparent
    val labelColor = when (style) {
        VocabGradeStyle.Primary -> Background
        VocabGradeStyle.Danger -> Danger
        VocabGradeStyle.Normal -> TextPrimary
    }
    val subColor = if (style == VocabGradeStyle.Primary) {
        Background.copy(alpha = 0.6f)
    } else {
        TextTertiary
    }
    val border = when (style) {
        VocabGradeStyle.Primary -> null
        VocabGradeStyle.Danger -> Danger.copy(alpha = 0.35f)
        VocabGradeStyle.Normal -> Edge
    }

    Column(
        modifier = modifier
            .height(60.dp)
            .clip(shape)
            .background(background)
            .then(if (border != null) Modifier.border(1.dp, border, shape) else Modifier)
            .clickable(onClick = onClick),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text(
            text = label,
            fontSize = 14.5.sp,
            fontWeight = if (style == VocabGradeStyle.Primary) FontWeight.SemiBold else FontWeight.Medium,
            color = labelColor,
            maxLines = 1
        )
        Spacer(modifier = Modifier.height(2.dp))
        Text(
            text = sub,
            fontSize = 11.sp,
            color = subColor,
            maxLines = 1
        )
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
