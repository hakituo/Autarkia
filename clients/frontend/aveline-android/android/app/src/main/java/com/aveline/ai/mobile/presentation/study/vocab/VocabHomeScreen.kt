package com.aveline.ai.mobile.presentation.study.vocab

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.study.VocabUiState
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 词汇主页：只回答「今天要背多少、从哪开始」。
 *
 * 今天总量 → 复习/新词两个入口 → 词书进度 → 三项统计 → 词典 → 错题本。
 * 出词顺序与每组数量收进标题栏齿轮（[VocabSettingsSheet]），主页只留背词主流程。
 */
@Composable
fun VocabHomeScreen(
    uiState: VocabUiState,
    onStartReview: () -> Unit,
    onStartNewWords: () -> Unit,
    onOpenBooks: () -> Unit,
    onOpenMistakes: () -> Unit,
    onSearch: (String) -> Unit,
    onClearSearch: () -> Unit
) {
    val overview = uiState.reviewOverview
    val book = uiState.bookProgress
    val isShuffle = uiState.wordOrder == "shuffle"
    // 分组复习后本地列表只装一组词，待复习总数以总览的权威口径为准。
    val reviewCount = overview?.dueTodayCount ?: uiState.learnWords.count { it.status == "review" }
    // 新词目标 = 今天还愿意背的量与词书剩余量的较小值。
    val newCount = book?.remainingWords?.coerceAtMost(uiState.newWordsBatchSize)
        ?: uiState.learnWords.count { it.status == "new" }
    val todayTotal = (reviewCount + newCount).coerceAtLeast(0)
    val todayLearned = uiState.todayVocab?.total
        ?: ((overview?.newToday ?: 0) + (overview?.reviewToday ?: 0))
    val mastered = overview?.masteredWords ?: book?.masteredWords ?: 0
    val streakDays = overview?.streakDays ?: 0

    var searchQuery by remember { mutableStateOf("") }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 20.dp)
    ) {
        Text(text = "今天", style = VocabKickerStyle)
        Spacer(modifier = Modifier.height(6.dp))
        Row(verticalAlignment = Alignment.Bottom) {
            Text(
                text = todayTotal.toString(),
                style = TextStyle(
                    fontSize = 52.sp,
                    lineHeight = 52.sp,
                    fontWeight = FontWeight.Medium,
                    letterSpacing = (-2).sp,
                    color = TextPrimary,
                    fontFeatureSettings = "tnum"
                )
            )
            Spacer(modifier = Modifier.width(6.dp))
            Text(
                text = "个词",
                fontSize = 16.sp,
                color = TextTertiary,
                modifier = Modifier.padding(bottom = 6.dp)
            )
        }
        Spacer(modifier = Modifier.height(4.dp))
        Text(
            text = if (todayTotal > 0) {
                "$reviewCount 个复习 · $newCount 个新词"
            } else {
                "今天没有待学习的词汇"
            },
            fontSize = 14.sp,
            lineHeight = 21.sp,
            color = TextSecondary
        )

        Spacer(modifier = Modifier.height(22.dp))
        EntryButtons(
            reviewCount = reviewCount,
            newCount = newCount,
            launching = uiState.launching,
            onStartReview = onStartReview,
            onStartNewWords = onStartNewWords
        )

        Spacer(modifier = Modifier.height(28.dp))
        BookSection(
            uiState = uiState,
            isShuffle = isShuffle,
            onOpenBooks = onOpenBooks
        )

        Spacer(modifier = Modifier.height(24.dp))
        StatsRow(
            streakDays = streakDays,
            masteredWords = mastered,
            todayLearned = todayLearned
        )

        Spacer(modifier = Modifier.height(26.dp))
        VocabDivider()
        Spacer(modifier = Modifier.height(18.dp))
        VocabSearchField(
            query = searchQuery,
            isSearching = uiState.isSearching,
            onQueryChange = { searchQuery = it },
            onSubmit = {
                if (searchQuery.isBlank()) onClearSearch() else onSearch(searchQuery.trim())
            },
            onClear = {
                searchQuery = ""
                onClearSearch()
            }
        )
        if (uiState.searchResults.isNotEmpty()) {
            Spacer(modifier = Modifier.height(6.dp))
            SearchResultList(uiState = uiState)
        }

        Spacer(modifier = Modifier.height(10.dp))
        MistakesRow(uiState = uiState, onClick = onOpenMistakes)
    }
}
