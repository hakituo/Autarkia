package com.aveline.ai.mobile.presentation.study

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.MenuBook
import androidx.compose.material.icons.filled.Today
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.presentation.components.SectionCard
import com.aveline.ai.mobile.presentation.theme.EmotionGreen
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/** 学习状态 → (标签, 颜色)，与后端 mastered / learning / due 一一对应。 */
private fun statusBadge(status: String): Pair<String, Color> = when (status) {
    "mastered" -> "已掌握" to EmotionGreen
    "due" -> "待复习" to Color(0xFFF59E0B)
    else -> "学习中" to Color(0xFF3B82F6)
}

/** 评分 → (标签, 颜色)：1=Again 2=Hard 3=Good 4=Easy。 */
private fun qualityBadge(quality: Int): Pair<String, Color> = when (quality) {
    1 -> "Again" to Color(0xFFEF4444)
    2 -> "Hard" to Color(0xFFF59E0B)
    4 -> "Easy" to Color(0xFF3B82F6)
    else -> "Good" to EmotionGreen
}

/**
 * 词书进度卡片：当前词书背到哪了、还剩多少、最近学过哪些词。
 *
 * 解决「只显示今天待复习数、看不到整本书进度」的问题。
 */
@Composable
fun VocabBookProgressCard(
    progress: VocabBookProgress?,
    learnedWords: List<LearnedWordItem>,
    learnedTotal: Int,
    onOpenBooks: () -> Unit
) {
    val book = progress ?: return
    SectionCard(
        title = "词书进度",
        icon = Icons.AutoMirrored.Filled.MenuBook,
        subtitle = book.currentBook.ifBlank { "当前词书" },
        trailingContent = {
            TextButton(onClick = onOpenBooks) { Text("换词书") }
        }
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = "已学 ${book.learnedWords} / ${book.totalWords}",
                style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Bold),
                color = TextPrimary
            )
            Text(
                text = "${book.progressPercent}%",
                style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Bold),
                color = EmotionGreen
            )
        }
        Spacer(modifier = Modifier.height(8.dp))
        LinearProgressIndicator(
            progress = { (book.progressPercent / 100f).coerceIn(0f, 1f) },
            modifier = Modifier
                .fillMaxWidth()
                .height(6.dp)
                .clip(RoundedCornerShape(3.dp)),
            color = EmotionGreen,
            trackColor = Color(0x1AFFFFFF)
        )
        Spacer(modifier = Modifier.height(12.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            ProgressStat("已掌握", book.masteredWords, EmotionGreen, Modifier.weight(1f))
            ProgressStat("学习中", book.learningWords, Color(0xFF3B82F6), Modifier.weight(1f))
            ProgressStat("待复习", book.dueWords, Color(0xFFF59E0B), Modifier.weight(1f))
            ProgressStat("未学", book.remainingWords, TextTertiary, Modifier.weight(1f))
        }
        if (book.todayNew > 0 || book.todayReview > 0) {
            Spacer(modifier = Modifier.height(10.dp))
            Text(
                text = "今日新学 ${book.todayNew} 个 · 复习 ${book.todayReview} 个",
                style = MaterialTheme.typography.bodySmall,
                color = TextSecondary
            )
        }

        if (learnedWords.isNotEmpty()) {
            Spacer(modifier = Modifier.height(14.dp))
            Text(
                text = "最近学过",
                style = MaterialTheme.typography.labelMedium,
                color = TextSecondary
            )
            Spacer(modifier = Modifier.height(6.dp))
            learnedWords.take(8).forEach { item ->
                LearnedWordRow(item)
            }
            if (learnedTotal > learnedWords.size) {
                Text(
                    text = "共 $learnedTotal 个已学单词（按最近复习排序）",
                    style = MaterialTheme.typography.labelSmall,
                    color = TextTertiary,
                    modifier = Modifier.padding(top = 4.dp)
                )
            }
        }
    }
}

@Composable
private fun ProgressStat(
    label: String,
    value: Int,
    color: Color,
    modifier: Modifier = Modifier
) {
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(8.dp))
            .background(color.copy(alpha = 0.10f))
            .padding(vertical = 8.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            text = value.toString(),
            style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Bold),
            color = color
        )
        Text(text = label, style = MaterialTheme.typography.labelSmall, color = TextTertiary)
    }
}

@Composable
private fun LearnedWordRow(item: LearnedWordItem) {
    val (label, color) = statusBadge(item.status)
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 5.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            text = item.word,
            style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Bold),
            color = TextPrimary,
            modifier = Modifier.width(96.dp),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis
        )
        Text(
            text = item.translation.ifBlank { "—" },
            style = MaterialTheme.typography.bodySmall,
            color = TextSecondary,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f)
        )
        Spacer(modifier = Modifier.width(8.dp))
        Badge(text = label, color = color)
    }
}

/**
 * 今日已背卡片：今天背了哪些词、每个词最后一次评分是什么。
 *
 * 数据来自 /vocab/today-words，按最后一次评分时间倒序。
 */
@Composable
fun VocabTodayWordsCard(summary: TodayVocabSummary?) {
    val today = summary ?: return
    SectionCard(
        title = "今日已背",
        icon = Icons.Default.Today,
        subtitle = today.date,
        collapsible = true,
        defaultExpanded = true
    ) {
        if (today.total == 0) {
            Text(
                text = "今天还没有背单词，开始复习后会在这里记录。",
                style = MaterialTheme.typography.bodySmall,
                color = TextSecondary
            )
            return@SectionCard
        }

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            ProgressStat("新学", today.newWords, Color(0xFFF59E0B), Modifier.weight(1f))
            ProgressStat("复习", today.reviewWords, Color(0xFF3B82F6), Modifier.weight(1f))
            ProgressStat("记得", today.knownWords, EmotionGreen, Modifier.weight(1f))
            ProgressStat("Again", today.againWords, Color(0xFFEF4444), Modifier.weight(1f))
        }
        Spacer(modifier = Modifier.height(10.dp))
        Text(
            text = "共 ${today.total} 个词 · ${today.reviewEvents} 次评分",
            style = MaterialTheme.typography.bodySmall,
            color = TextSecondary
        )
        Spacer(modifier = Modifier.height(8.dp))

        today.words.forEach { item ->
            TodayWordRow(item)
        }
        if (today.words.size < today.total) {
            Text(
                text = "已展示 ${today.words.size} / ${today.total} 个",
                style = MaterialTheme.typography.labelSmall,
                color = TextTertiary,
                modifier = Modifier.padding(top = 4.dp)
            )
        }
    }
}

@Composable
private fun TodayWordRow(item: TodayVocabWord) {
    val (qualityLabel, qualityColor) = qualityBadge(item.lastQuality)
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 5.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Box(
            modifier = Modifier
                .clip(RoundedCornerShape(4.dp))
                .background(
                    if (item.status == "new") Color(0x1AF59E0B) else Color(0x1A3B82F6)
                )
                .padding(horizontal = 5.dp, vertical = 2.dp)
        ) {
            Text(
                text = if (item.status == "new") "新" else "复",
                style = MaterialTheme.typography.labelSmall,
                color = if (item.status == "new") Color(0xFFF59E0B) else Color(0xFF3B82F6),
                fontWeight = FontWeight.Bold
            )
        }
        Spacer(modifier = Modifier.width(8.dp))
        Text(
            text = item.word,
            style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Bold),
            color = TextPrimary,
            modifier = Modifier.width(96.dp),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis
        )
        Text(
            text = item.translation.ifBlank { "—" },
            style = MaterialTheme.typography.bodySmall,
            color = TextSecondary,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f)
        )
        if (item.reviews > 1) {
            Text(
                text = "×${item.reviews}",
                style = MaterialTheme.typography.labelSmall,
                color = TextTertiary
            )
            Spacer(modifier = Modifier.width(6.dp))
        }
        Badge(text = qualityLabel, color = qualityColor)
        Spacer(modifier = Modifier.width(6.dp))
        Text(
            text = item.lastReviewAt,
            style = MaterialTheme.typography.labelSmall,
            color = TextTertiary
        )
    }
}

@Composable
private fun Badge(text: String, color: Color) {
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(4.dp))
            .background(color.copy(alpha = 0.14f))
            .padding(horizontal = 6.dp, vertical = 2.dp)
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelSmall,
            color = color,
            fontWeight = FontWeight.Bold
        )
    }
}
