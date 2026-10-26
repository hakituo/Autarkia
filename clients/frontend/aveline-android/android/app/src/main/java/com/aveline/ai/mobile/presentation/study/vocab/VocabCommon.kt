package com.aveline.ai.mobile.presentation.study.vocab

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.components.controls.AvelineIconButton
import com.aveline.ai.mobile.presentation.study.ReviewResultItem
import com.aveline.ai.mobile.presentation.study.WordTranslation
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.Line
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import java.util.Locale

/** 计时、进度等窄字段：等宽数字，避免数字跳动。 */
internal val VocabMonoStyle = TextStyle(
    fontFamily = FontFamily.Monospace,
    fontSize = 11.5.sp,
    lineHeight = 16.sp,
    color = TextTertiary,
    fontFeatureSettings = "tnum"
)

internal val VocabKickerStyle = TextStyle(
    fontSize = 13.sp,
    lineHeight = 18.sp,
    color = TextTertiary
)

internal val VocabPageTitleStyle = TextStyle(
    fontSize = 30.sp,
    lineHeight = 38.sp,
    fontWeight = FontWeight.SemiBold,
    letterSpacing = (-0.4).sp,
    color = TextPrimary
)

internal val VocabRowLabelStyle = TextStyle(
    fontSize = 14.5.sp,
    lineHeight = 20.sp,
    color = TextSecondary
)

@Composable
internal fun VocabDivider(
    modifier: Modifier = Modifier,
    color: Color = Line
) {
    Box(
        modifier = modifier
            .fillMaxWidth()
            .height(1.dp)
            .background(color)
    )
}

/** 子页面统一页头：44dp 返回键 + 30sp 标题 + 13sp 说明。 */
@Composable
internal fun VocabScreenHeader(
    title: String,
    subtitle: String?,
    onBack: () -> Unit
) {
    Column(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(56.dp)
                .padding(horizontal = 8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            AvelineIconButton(
                icon = Icons.AutoMirrored.Filled.ArrowBack,
                contentDescription = "返回",
                onClick = onBack
            )
        }
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp)
        ) {
            Text(text = title, style = VocabPageTitleStyle)
            if (!subtitle.isNullOrBlank()) {
                Spacer(modifier = Modifier.height(6.dp))
                Text(text = subtitle, style = VocabKickerStyle)
            }
        }
    }
}

/** 千分位展示词数，避免 4500 与 45,000 读错。 */
internal fun formatCount(value: Int): String = String.format(Locale.US, "%,d", value)

/** 词书文件名去掉扩展名，界面上不展示 .json。 */
internal fun bookDisplayName(filename: String): String = filename.removeSuffix(".json")

/** 去掉词书文件名里的顺序后缀，顺序在首页单独显示。 */
internal fun bookBaseName(filename: String): String =
    bookDisplayName(filename).substringBefore("-顺序").substringBefore("-乱序")

/** 首页词书行：CET4 · 顺序。 */
internal fun bookTitleWithOrder(filename: String, shuffle: Boolean): String {
    val base = bookBaseName(filename)
    if (base.isBlank()) return ""
    return "$base · ${if (shuffle) "乱序" else "顺序"}"
}

/** 长单词自动降字号，保证 44sp 的视觉重心不把单词挤出屏幕。 */
internal fun reviewWordSize(word: String): TextUnit = when {
    word.length <= 9 -> 44.sp
    word.length <= 13 -> 36.sp
    else -> 30.sp
}

/**
 * 从 [WordTranslation] 解析词性标签与纯净释义。
 *
 * 词库里形容词等词性的 type 字段常为空，词性缩写被塞进 translation 前缀。
 */
internal fun parseWordType(translation: WordTranslation): Pair<String, String> {
    if (translation.type.isNotBlank()) {
        return translation.type to translation.translation
    }
    // 长词性必须排在短词性前面，否则 "adj." 会被 "a" 抢先匹配成 "dj."。
    val regex = Regex("^(abbr|adj|adv|prep|conj|pron|num|art|int|vt|vi|n|v|a)\\.\\s*")
    val match = regex.find(translation.translation) ?: return "" to translation.translation
    val type = match.groupValues[1]
    val rest = translation.translation.substring(match.range.last + 1).trim()
    return type to rest
}

/** 答案面按词性合并同组释义，避免一个词铺出七八行相同词性。 */
internal data class VocabDefinitionGroup(
    val label: String,
    val text: String,
    val primary: Boolean
)

internal fun groupDefinitions(translations: List<WordTranslation>): List<VocabDefinitionGroup> {
    val groups = linkedMapOf<String, MutableList<WordTranslation>>()
    translations.forEach { translation ->
        val type = parseWordType(translation).first
        groups.getOrPut(type) { mutableListOf() }.add(translation)
    }
    return groups.map { (type, items) ->
        VocabDefinitionGroup(
            label = type.takeIf { it.isNotBlank() }?.let { "$it." }.orEmpty(),
            text = items.joinToString("；") { parseWordType(it).second },
            primary = items.any { it.primary }
        )
    }
}

/** 例句里把目标词标成鼠尾草绿下划线。 */
internal fun highlightWord(sentence: String, word: String): AnnotatedString {
    if (word.isBlank()) return AnnotatedString(sentence)
    val lowerSentence = sentence.lowercase()
    val target = word.lowercase()
    return buildAnnotatedString {
        append(sentence)
        var start = lowerSentence.indexOf(target)
        while (start >= 0) {
            addStyle(
                SpanStyle(color = Accent, textDecoration = TextDecoration.Underline),
                start,
                start + target.length
            )
            start = lowerSentence.indexOf(target, start + target.length)
        }
    }
}

/** 本轮明细按首次出现顺序计算最长连对。 */
internal fun longestKnownStreak(results: List<ReviewResultItem>): Int {
    var best = 0
    var current = 0
    results.forEach { item ->
        if (item.known) {
            current += 1
            best = maxOf(best, current)
        } else {
            current = 0
        }
    }
    return best
}
