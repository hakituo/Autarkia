package com.aveline.ai.mobile.presentation.study

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import kotlin.math.roundToInt

/**
 * 学科入口。
 *
 * 设计稿第三轮：低频页面不靠「卡片套卡片」分层，改成「标题 + 细线列表」。
 * 每一科只留一行 —— 科目名、当前状态（章节 / 口径）、百分比，下面一条 3dp 进度线；
 * 空状态也只是一行灰字，不再放 School 图标。
 *
 * 当前只复用 Study Daily 已有的各科进度摘要，不伪造考纲节点或掌握度。
 */
@Composable
fun StudySubjectsTab(dailyUiState: StudyDailyUiState) {
    val progressContent = dailyUiState.latestProgress?.content.orEmpty()
    val subjects = remember(progressContent) { parseStudySubjectProgress(progressContent) }

    LazyColumn(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(top = 20.dp, bottom = 28.dp)
    ) {
        if (subjects.isEmpty()) {
            item {
                Text(
                    text = "还没有可展示的学科进度记录",
                    fontSize = 14.sp,
                    color = TextTertiary,
                    modifier = Modifier.padding(top = 16.dp, bottom = 8.dp)
                )
            }
        } else {
            items(subjects, key = { it.name }) { subject ->
                SubjectRow(subject)
            }
        }
    }
}

/** 一科一行：上行文字 + 百分比，下行 3dp 进度线。 */
@Composable
private fun SubjectRow(subject: StudySubjectProgress) {
    val percent = (subject.progress * 100).roundToInt().coerceIn(0, 100)
    Column(modifier = Modifier.fillMaxWidth()) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(1.dp)
                .background(SubjectHairline)
        )
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                // 百分比跟科目标题对齐（设计稿是 baseline），不跟着两行文字居中。
                verticalAlignment = Alignment.Top
            ) {
                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(3.dp)
                ) {
                    Text(
                        text = subject.name,
                        fontSize = 16.sp,
                        fontWeight = FontWeight.Medium,
                        color = TextPrimary
                    )
                    if (subject.status.isNotBlank()) {
                        Text(
                            text = subject.status,
                            fontSize = 12.5f.sp,
                            color = TextTertiary
                        )
                    }
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = "$percent%",
                        fontSize = 17.sp,
                        fontWeight = FontWeight.Medium,
                        color = TextPrimary,
                        style = TextStyle(fontFeatureSettings = "tnum")
                    )
                    Icon(
                        imageVector = Icons.Default.ChevronRight,
                        contentDescription = null,
                        tint = TextTertiary,
                        modifier = Modifier
                            .padding(start = 2.dp)
                            .size(18.dp)
                    )
                }
            }
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(3.dp)
                    .clip(RoundedCornerShape(2.dp))
                    .background(SubjectTrack)
            ) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth(subject.progress.coerceIn(0f, 1f))
                        .height(3.dp)
                        .clip(RoundedCornerShape(2.dp))
                        .background(TextPrimary)
                )
            }
        }
    }
}

/** 细线列表的顶栏线：6% 白，比正文分隔线更轻。 */
private val SubjectHairline = Color(0x0FFFFFFF)

/** 进度槽：8% 白。 */
private val SubjectTrack = Color(0x14FFFFFF)

internal data class StudySubjectProgress(
    val name: String,
    val status: String,
    val progress: Float
)

internal fun parseStudySubjectProgress(content: String): List<StudySubjectProgress> {
    if (content.isBlank()) return emptyList()
    val sectionStart = content.indexOf("## 各科进展")
    if (sectionStart < 0) return emptyList()

    val afterSection = content.substring(sectionStart)
    val nextSection = afterSection.indexOf("\n## ", 1)
    val sectionText = if (nextSection > 0) afterSection.substring(0, nextSection) else afterSection
    val subjectRegex = Regex("""### (.+?)\n(.*?)(?=\n###|\z)""", RegexOption.DOT_MATCHES_ALL)
    val parsed = mutableMapOf<String, StudySubjectProgress>()

    subjectRegex.findAll(sectionText).forEach { match ->
        val name = match.groupValues[1].trim()
        val body = match.groupValues[2]
        val status = body.lines()
            .firstOrNull { it.startsWith("- 状态：") }
            ?.removePrefix("- 状态：")
            ?.trim()
            .orEmpty()
        parsed[name] = StudySubjectProgress(name, status, mapStudyStatusToProgress(status))
    }

    val order = listOf(
        "语文", "数学", "英语",
        "物理", "化学", "生物",
        "政治", "历史", "地理",
        "计算机科学", "其他"
    )
    val ordered = order.mapNotNull(parsed::get)
    val extras = parsed.values.filter { it.name !in order }
    return ordered + extras
}

private fun mapStudyStatusToProgress(status: String): Float {
    if (status.isBlank() || status == "——" || status == "无") return 0f
    return when {
        status.contains("完整") || status.contains("全覆盖") -> 0.9f
        status.contains("体系") -> 0.7f
        status.contains("很大") || status.contains("很广") -> 0.6f
        status.contains("框架") -> 0.4f
        status.contains("较少") -> 0.2f
        status.contains("弱项") || status.contains("需关注") -> 0.5f
        else -> 0.5f
    }
}
