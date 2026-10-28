package com.aveline.ai.mobile.presentation.study.vocab

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.components.controls.AvelineButton
import com.aveline.ai.mobile.presentation.components.controls.AvelineButtonVariant
import com.aveline.ai.mobile.presentation.study.VocabLaunch
import com.aveline.ai.mobile.presentation.study.VocabUiState
import com.aveline.ai.mobile.presentation.theme.Line
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

@Composable
internal fun EntryButtons(
    reviewCount: Int,
    newCount: Int,
    /** 正在启动的会话：对应按钮立即转圈，重复点击由管理器拦下。 */
    launching: VocabLaunch?,
    onStartReview: () -> Unit,
    onStartNewWords: () -> Unit
) {
    when {
        reviewCount > 0 && newCount > 0 -> {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                AvelineButton(
                    text = "开始复习",
                    onClick = onStartReview,
                    modifier = Modifier.weight(1.4f),
                    variant = AvelineButtonVariant.Primary,
                    icon = Icons.Default.PlayArrow,
                    loading = launching == VocabLaunch.REVIEW
                )
                AvelineButton(
                    text = "背新词",
                    onClick = onStartNewWords,
                    modifier = Modifier.weight(1f),
                    variant = AvelineButtonVariant.Secondary,
                    loading = launching == VocabLaunch.NEW_WORDS
                )
            }
        }
        reviewCount > 0 -> {
            AvelineButton(
                text = "开始复习",
                onClick = onStartReview,
                modifier = Modifier.fillMaxWidth(),
                variant = AvelineButtonVariant.Primary,
                icon = Icons.Default.PlayArrow,
                loading = launching == VocabLaunch.REVIEW
            )
        }
        else -> {
            AvelineButton(
                text = if (newCount > 0) "背新词" else "今天已完成",
                onClick = onStartNewWords,
                modifier = Modifier.fillMaxWidth(),
                variant = AvelineButtonVariant.Primary,
                enabled = newCount > 0,
                loading = launching == VocabLaunch.NEW_WORDS
            )
        }
    }
}

@Composable
internal fun BookSection(
    uiState: VocabUiState,
    isShuffle: Boolean,
    onOpenBooks: () -> Unit
) {
    val book = uiState.bookProgress
    val title = bookTitleWithOrder(uiState.currentBook, isShuffle).ifBlank { "未选词书" }
    VocabDivider()
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onOpenBooks)
            .padding(vertical = 16.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = title,
                    fontSize = 15.5.sp,
                    fontWeight = FontWeight.Medium,
                    color = TextPrimary,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Spacer(modifier = Modifier.height(2.dp))
                Text(
                    text = if (uiState.vocabBooks.isNotEmpty()) {
                        "共 ${uiState.vocabBooks.size} 本可选"
                    } else {
                        "无可用词书"
                    },
                    fontSize = 12.5.sp,
                    color = TextTertiary
                )
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(text = "换词书", fontSize = 14.sp, color = TextSecondary)
                Icon(
                    imageVector = Icons.Default.ChevronRight,
                    contentDescription = null,
                    tint = TextSecondary,
                    modifier = Modifier.size(18.dp)
                )
            }
        }
        if (book != null && book.totalWords > 0) {
            Spacer(modifier = Modifier.height(12.dp))
            val fraction = (book.progressPercent / 100f).coerceIn(0f, 1f)
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(4.dp)
                    .clip(RoundedCornerShape(2.dp))
                    .background(Line)
            ) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth(fraction)
                        .height(4.dp)
                        .background(TextPrimary)
                )
            }
            Spacer(modifier = Modifier.height(7.dp))
            Text(
                text = "已学 ${formatCount(book.learnedWords)} / ${formatCount(book.totalWords)}",
                style = VocabMonoStyle.copy(fontSize = 12.5.sp),
                color = TextTertiary
            )
        }
    }
    VocabDivider()
}

@Composable
internal fun StatsRow(
    streakDays: Int,
    masteredWords: Int,
    todayLearned: Int
) {
    Row(modifier = Modifier.fillMaxWidth()) {
        StatColumn(
            modifier = Modifier.weight(1f),
            value = streakDays.toString(),
            unit = "天",
            label = "连续"
        )
        StatColumn(
            modifier = Modifier.weight(1f),
            value = formatCount(masteredWords),
            label = "已掌握"
        )
        StatColumn(
            modifier = Modifier.weight(1f),
            value = todayLearned.toString(),
            label = "今日已背"
        )
    }
}

@Composable
private fun StatColumn(
    modifier: Modifier = Modifier,
    value: String,
    label: String,
    unit: String = ""
) {
    Column(modifier = modifier) {
        Row(verticalAlignment = Alignment.Bottom) {
            Text(
                text = value,
                fontSize = 22.sp,
                lineHeight = 26.sp,
                fontWeight = FontWeight.Medium,
                color = TextPrimary,
                style = TextStyle(fontFeatureSettings = "tnum")
            )
            if (unit.isNotBlank()) {
                Text(
                    text = unit,
                    fontSize = 13.sp,
                    color = TextTertiary,
                    modifier = Modifier.padding(start = 3.dp, bottom = 2.dp)
                )
            }
        }
        Spacer(modifier = Modifier.height(3.dp))
        Text(text = label, fontSize = 12.sp, color = TextTertiary)
    }
}
