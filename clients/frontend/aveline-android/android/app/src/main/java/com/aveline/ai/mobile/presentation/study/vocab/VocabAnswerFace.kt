package com.aveline.ai.mobile.presentation.study.vocab

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.study.DailyWord
import com.aveline.ai.mobile.presentation.study.WordTranslation
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 答案面完整内容：释义 / 更多释义 / 短语 / 例句。
 *
 * 用细线与字号分层，不再给每一块加灰底卡片；内容超出一屏时内部滚动。
 */
@Composable
internal fun VocabAnswerFace(
    word: DailyWord,
    modifier: Modifier = Modifier
) {
    var showExtended by remember(word.word) { mutableStateOf(false) }
    val scrollState = rememberScrollState()
    LaunchedEffect(word.word) { scrollState.scrollTo(0) }

    Column(
        modifier = modifier
            .verticalScroll(scrollState)
            .padding(start = 20.dp, end = 20.dp, top = 28.dp, bottom = 16.dp)
    ) {
        Text(
            text = word.word,
            fontSize = 30.sp,
            lineHeight = 38.sp,
            fontWeight = FontWeight.Medium,
            letterSpacing = (-0.6).sp,
            color = TextPrimary
        )
        Spacer(modifier = Modifier.height(6.dp))
        PhoneticsRow(word = word, fontSize = 13.5.sp)

        Spacer(modifier = Modifier.height(18.dp))
        val definitions = groupDefinitions(word.translations)
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            definitions.forEach { definition ->
                DefinitionRow(
                    label = definition.label,
                    text = definition.text,
                    emphasize = definition.primary
                )
            }
        }

        val extended = word.extendedTranslations
        if (extended.isNotEmpty()) {
            Spacer(modifier = Modifier.height(16.dp))
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { showExtended = !showExtended },
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text(
                    text = "更多释义 · ${extended.size}",
                    fontSize = 13.5.sp,
                    color = TextSecondary
                )
                Icon(
                    imageVector = if (showExtended) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
                    contentDescription = if (showExtended) "收起更多释义" else "展开更多释义",
                    tint = TextSecondary,
                    modifier = Modifier.size(18.dp)
                )
            }
            if (showExtended) {
                Spacer(modifier = Modifier.height(10.dp))
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    extended.forEach { translation ->
                        val label = extendedLabel(translation)
                        DefinitionRow(
                            label = label,
                            text = parseWordType(translation).second,
                            emphasize = false,
                            muted = true
                        )
                    }
                }
            }
        }

        val phrases = word.phrases.orEmpty()
        if (phrases.isNotEmpty()) {
            Spacer(modifier = Modifier.height(18.dp))
            SectionDivider()
            Spacer(modifier = Modifier.height(14.dp))
            SectionLabel("短语")
            Spacer(modifier = Modifier.height(10.dp))
            Column(verticalArrangement = Arrangement.spacedBy(9.dp)) {
                phrases.take(5).forEach { phrase ->
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            text = phrase.phrase,
                            fontSize = 14.5.sp,
                            color = TextPrimary,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.weight(1f)
                        )
                        Spacer(modifier = Modifier.width(12.dp))
                        Text(
                            text = phrase.translation,
                            fontSize = 14.5.sp,
                            color = TextSecondary,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            textAlign = TextAlign.End,
                            modifier = Modifier.weight(1f)
                        )
                    }
                }
            }
        }

        val sentences = word.sentences.orEmpty()
        if (sentences.isNotEmpty()) {
            Spacer(modifier = Modifier.height(18.dp))
            SectionDivider()
            Spacer(modifier = Modifier.height(14.dp))
            SectionLabel("例句")
            Spacer(modifier = Modifier.height(8.dp))
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                sentences.take(3).forEach { sentence ->
                    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text(
                            text = highlightWord(sentence.sentence, word.word),
                            fontSize = 15.sp,
                            lineHeight = 24.sp,
                            color = TextPrimary
                        )
                        if (sentence.translation.isNotBlank()) {
                            Text(
                                text = sentence.translation,
                                fontSize = 13.5.sp,
                                lineHeight = 22.sp,
                                color = TextSecondary
                            )
                        }
                    }
                }
            }
        }
    }
}

/** 词性占 40dp 窄列，释义与词性按基线对齐；primary 释义加粗。 */
@Composable
private fun DefinitionRow(
    label: String,
    text: String,
    emphasize: Boolean,
    muted: Boolean = false
) {
    Row(modifier = Modifier.fillMaxWidth()) {
        Text(
            text = label,
            fontSize = if (muted) 11.5.sp else 12.5.sp,
            color = TextTertiary,
            style = TextStyle(fontFeatureSettings = "tnum"),
            modifier = Modifier
                .width(40.dp)
                .alignByBaseline()
        )
        Spacer(modifier = Modifier.width(8.dp))
        Text(
            text = text,
            fontSize = if (muted) 14.5.sp else 16.5.sp,
            lineHeight = if (muted) 22.5.sp else 25.5.sp,
            fontWeight = if (emphasize) FontWeight.SemiBold else FontWeight.Normal,
            color = if (muted) TextSecondary else TextPrimary,
            modifier = Modifier
                .weight(1f)
                .alignByBaseline()
        )
    }
}

@Composable
private fun SectionLabel(text: String) {
    Text(text = text, fontSize = 12.5.sp, color = TextTertiary)
}

@Composable
private fun SectionDivider() {
    VocabDivider()
}

/** 扩展释义左侧优先显示学科标签（[法] / [计]），没有标签时退回词性。 */
private fun extendedLabel(translation: WordTranslation): String {
    val domain = translation.domains.joinToString(" ") { "[$it]" }
    if (domain.isNotBlank()) return domain
    val type = parseWordType(translation).first
    return if (type.isNotBlank()) "$type." else "·"
}
