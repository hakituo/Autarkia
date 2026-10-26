package com.aveline.ai.mobile.presentation.study.vocab

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.study.MistakeWord
import com.aveline.ai.mobile.presentation.study.VocabUiState
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/** 错题本：与词书详情同一套细线列表，不加底色卡片。 */
@Composable
fun VocabMistakesScreen(
    uiState: VocabUiState,
    onBack: () -> Unit
) {
    val mistakes = uiState.mistakes
    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
    ) {
        VocabScreenHeader(
            title = "错题本",
            subtitle = if (mistakes.isEmpty()) "还没有错题" else "共 ${mistakes.size} 个词",
            onBack = onBack
        )
        Spacer(modifier = Modifier.height(24.dp))
        if (mistakes.isEmpty()) {
            Box(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .padding(24.dp),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    text = "复习时点「不认识」的词会收进这里",
                    fontSize = 15.sp,
                    color = TextTertiary,
                    textAlign = TextAlign.Center
                )
            }
        } else {
            LazyColumn(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth(),
                contentPadding = PaddingValues(start = 20.dp, end = 20.dp, bottom = 24.dp)
            ) {
                items(mistakes, key = { it.word }) { mistake ->
                    VocabDivider(color = Color.White.copy(alpha = 0.06f))
                    MistakeRow(mistake = mistake)
                }
            }
        }
    }
}

@Composable
private fun MistakeRow(mistake: MistakeWord) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = mistake.word,
                fontSize = 15.5.sp,
                fontWeight = FontWeight.Medium,
                color = TextPrimary,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
            if (mistake.translation.isNotBlank()) {
                Spacer(modifier = Modifier.height(3.dp))
                Text(
                    text = mistake.translation,
                    fontSize = 13.5.sp,
                    color = TextSecondary,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
        }
        if (mistake.errorCount > 0) {
            Spacer(modifier = Modifier.width(12.dp))
            Text(
                text = "错 ${mistake.errorCount} 次",
                style = VocabMonoStyle,
                color = TextTertiary
            )
        }
    }
}
