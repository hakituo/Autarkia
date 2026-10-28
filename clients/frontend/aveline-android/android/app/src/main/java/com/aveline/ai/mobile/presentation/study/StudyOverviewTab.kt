package com.aveline.ai.mobile.presentation.study

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.domain.models.LatestProgress
import com.aveline.ai.mobile.presentation.components.controls.AvelineButton
import com.aveline.ai.mobile.presentation.components.controls.AvelineButtonVariant
import com.aveline.ai.mobile.presentation.theme.Line
import com.aveline.ai.mobile.presentation.theme.TextBody
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 学习记录页。
 *
 * 第三轮设计稿把原来的四张卡收成三段：
 * 1. 三个统计数字（今日时长 / 科目 / 连续学习），不用卡片、不用图标；
 * 2. 最新进度一段话（「各科进展」已在「学科」Tab 里，这里剥掉，不重复）；
 * 3. 今天的会话列表（时间 + 会话名 + 时长）。
 *
 * 手动录入的三个输入框收进底部按钮，点开是底部面板；录入仍复用
 * [StudyUiState.recordTopic] / [StudyUiState.recordContent] / [StudyUiState.recordDuration]，
 * 不新增第二套表单状态。
 */
@Composable
fun StudyOverviewTab(
    uiState: StudyUiState,
    dailyUiState: StudyDailyUiState,
    onTopicChange: (String) -> Unit,
    onContentChange: (String) -> Unit,
    onDurationChange: (Int) -> Unit,
    onRecordStudy: () -> Unit,
    onStartStudy: () -> Unit,
    onFinishStudy: () -> Unit
) {
    val sessions = uiState.studyRecords
    val subjectCount = remember(sessions) {
        sessions.map { it.topic.trim() }.filter { it.isNotBlank() }.distinct().size
    }
    var showRecordSheet by remember { mutableStateOf(false) }

    Column(modifier = Modifier.fillMaxSize()) {
        LazyColumn(
            modifier = Modifier
                .fillMaxWidth()
                .weight(1f),
            contentPadding = PaddingValues(bottom = 16.dp)
        ) {
            item {
                RecordStats(
                    minutes = uiState.todayStudyMinutes,
                    subjectCount = subjectCount,
                    streakDays = uiState.studyStreakDays
                )
            }
            // 表单收进底部面板后，保存失败不能再靠"点了没反应"暴露，错误直接挂在列表上方。
            uiState.error?.takeIf { it.isNotBlank() }?.let { message ->
                item {
                    Text(
                        text = message,
                        fontSize = 13.sp,
                        lineHeight = 20.sp,
                        color = MaterialTheme.colorScheme.error,
                        modifier = Modifier.padding(top = 14.dp)
                    )
                }
            }
            item { LatestProgressBlock(progress = dailyUiState.latestProgress) }
            item { TodaySessionsBlock(sessions = sessions) }
        }

        // 固定在页底：列表只占按钮以上的空间，滚动内容不会从按钮下面穿过去。
        AvelineButton(
            text = "手动记录一次",
            onClick = { showRecordSheet = true },
            icon = Icons.Default.Add,
            variant = AvelineButtonVariant.Secondary,
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = 8.dp, bottom = 24.dp)
        )
    }

    if (showRecordSheet) {
        StudyRecordSheet(
            topic = uiState.recordTopic,
            content = uiState.recordContent,
            duration = uiState.recordDuration,
            onTopicChange = onTopicChange,
            onContentChange = onContentChange,
            onDurationChange = onDurationChange,
            onSave = {
                onRecordStudy()
                showRecordSheet = false
            },
            onStart = {
                onStartStudy()
                showRecordSheet = false
            },
            onFinish = {
                onFinishStudy()
                showRecordSheet = false
            },
            onDismiss = { showRecordSheet = false }
        )
    }
}

/** 三个统计数字：26sp 等宽数值 + 12sp 灰标签，不套卡片。 */
@Composable
private fun RecordStats(minutes: Int, subjectCount: Int, streakDays: Int) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 22.dp, bottom = 2.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        RecordStat(
            label = "今日时长",
            value = formatRecordMinutes(minutes),
            modifier = Modifier.weight(1f)
        )
        RecordStat(
            label = "科目",
            value = subjectCount.toString(),
            modifier = Modifier.weight(1f)
        )
        RecordStat(
            label = "连续学习",
            value = streakDays.toString(),
            unit = "天",
            modifier = Modifier.weight(1f)
        )
    }
}

@Composable
private fun RecordStat(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
    unit: String? = null
) {
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(3.dp)
    ) {
        Row {
            Text(
                text = value,
                fontSize = 26.sp,
                lineHeight = 30.sp,
                fontWeight = FontWeight.Medium,
                letterSpacing = (-0.6f).sp,
                color = TextPrimary,
                style = RecordNumericStyle,
                maxLines = 1,
                modifier = Modifier.alignByBaseline()
            )
            if (!unit.isNullOrBlank()) {
                Spacer(modifier = Modifier.width(3.dp))
                Text(
                    text = unit,
                    fontSize = 14.sp,
                    color = TextTertiary,
                    modifier = Modifier.alignByBaseline()
                )
            }
        }
        Text(
            text = label,
            fontSize = 12.sp,
            color = TextTertiary
        )
    }
}

/** 最新进度：细线 + 小标签 + 一段话；「各科进展」段落已移到「学科」Tab。 */
@Composable
private fun LatestProgressBlock(progress: LatestProgress?) {
    val content = progress?.content.orEmpty()
    val summary = remember(content) { stripSubjectProgress(content) }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 26.dp)
    ) {
        SectionHairline()
        Spacer(modifier = Modifier.height(16.dp))
        Text(text = "最新进度", fontSize = 13.sp, color = TextTertiary)
        Spacer(modifier = Modifier.height(10.dp))
        if (summary.isBlank()) {
            Text(
                text = "暂无学习进度记录",
                fontSize = 15.sp,
                color = TextTertiary,
                modifier = Modifier.padding(vertical = 8.dp)
            )
        } else {
            NotesMarkdownRenderer(
                text = summary,
                bodyStyle = RecordBodyStyle,
                documentStyle = true
            )
        }
    }
}

/** 今天的会话：时间（等宽）+ 会话名 + 时长；没有时长就只显示名字。 */
@Composable
private fun TodaySessionsBlock(sessions: List<StudyRecord>) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 24.dp)
    ) {
        SectionHairline()
        Spacer(modifier = Modifier.height(12.dp))
        Text(
            text = "今天的会话",
            fontSize = 13.sp,
            color = TextTertiary,
            modifier = Modifier.padding(bottom = 4.dp)
        )
        if (sessions.isEmpty()) {
            Text(
                text = "今天还没有学习会话",
                fontSize = 13.5f.sp,
                color = TextTertiary,
                modifier = Modifier.padding(vertical = 12.dp)
            )
        } else {
            sessions.forEach { session ->
                SessionRow(session = session)
            }
        }
    }
}

@Composable
private fun SessionRow(session: StudyRecord) {
    Column(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 11.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = session.time.ifBlank { "--:--" },
                fontSize = 12.sp,
                fontFamily = FontFamily.Monospace,
                color = TextTertiary,
                modifier = Modifier.width(52.dp)
            )
            Spacer(modifier = Modifier.width(10.dp))
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(2.dp)
            ) {
                Text(
                    text = session.topic.ifBlank { "未命名会话" },
                    fontSize = 15.sp,
                    color = TextPrimary,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                if (session.content.isNotBlank()) {
                    Text(
                        text = session.content,
                        fontSize = 12.5f.sp,
                        color = TextTertiary,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }
            }
            val minutes = session.minutes
            if (minutes != null && minutes > 0) {
                Spacer(modifier = Modifier.width(10.dp))
                Text(
                    text = "$minutes 分钟",
                    fontSize = 13.5f.sp,
                    color = TextSecondary,
                    style = RecordNumericStyle
                )
            }
        }
        // 行分隔线走底边：小标题下面不再先压一条线。
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(1.dp)
                .background(RecordHairline)
        )
    }
}

@Composable
private fun SectionHairline() {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(1.dp)
            .background(Line)
    )
}

/** `200` → `3h 20m`；不足一小时只报分钟。 */
internal fun formatRecordMinutes(minutes: Int): String {
    val safe = minutes.coerceAtLeast(0)
    val hours = safe / 60
    val rest = safe % 60
    return when {
        hours <= 0 -> "${rest}m"
        rest == 0 -> "${hours}h"
        else -> "${hours}h ${rest}m"
    }
}

/**
 * 去掉进度文件里的 `## 各科进展` 段落。
 *
 * 各科进度已经在「学科」Tab 的列表里，记录页只保留进度文件里的其余叙述，
 * 避免同一份数据在同一屏重复出现。
 */
internal fun stripSubjectProgress(content: String): String {
    if (content.isBlank()) return ""
    val sectionStart = content.indexOf(SUBJECT_SECTION_HEADING)
    if (sectionStart < 0) return content.trim()

    val before = content.substring(0, sectionStart).trimEnd()
    val afterSection = content.substring(sectionStart)
    val nextSection = afterSection.indexOf("\n## ", 1)
    val after = if (nextSection > 0) {
        afterSection.substring(nextSection).trimStart()
    } else {
        ""
    }
    return listOf(before, after)
        .filter { it.isNotBlank() }
        .joinToString("\n\n")
}

/** 进度正文：15sp / 1.75 行高。 */
private val RecordBodyStyle = TextStyle(
    fontSize = 15.sp,
    lineHeight = 26.sp,
    color = TextBody
)

/** 等宽数字：统计与会话时长切换数值时不跳动。 */
private val RecordNumericStyle = TextStyle(fontFeatureSettings = "tnum")

/** 会话行分隔线：6% 白，走行底边。 */
private val RecordHairline = Color(0x0FFFFFFF)

private const val SUBJECT_SECTION_HEADING = "## 各科进展"
