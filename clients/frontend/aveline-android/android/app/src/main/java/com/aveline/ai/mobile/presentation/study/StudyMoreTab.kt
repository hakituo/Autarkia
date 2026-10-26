package com.aveline.ai.mobile.presentation.study

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Article
import androidx.compose.material.icons.automirrored.filled.ListAlt
import androidx.compose.material.icons.automirrored.filled.MenuBook
import androidx.compose.material.icons.filled.ChevronLeft
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.EditCalendar
import androidx.compose.material.icons.filled.History
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.domain.models.PlanItem
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Study 顶层“更多”里的功能入口。 */
enum class StudyMoreSection(val title: String) {
    HUB("更多"),
    PLAN("计划"),
    VOCAB("词汇"),
    NOTES("笔记"),
    DIARY("日记"),
    RECORDS("学习记录")
}

@Composable
fun StudyMoreTab(
    section: StudyMoreSection,
    uiState: StudyUiState,
    dailyUiState: StudyDailyUiState,
    planUiState: StudyPlanUiState,
    notesUiState: StudyNotesUiState,
    vocabUiState: VocabUiState,
    onSectionChange: (StudyMoreSection) -> Unit,
    onDateSelected: (String) -> Unit,
    onTogglePlanItem: (PlanItem) -> Unit,
    onAddPlanItem: (PlanItem) -> Unit,
    onUpdatePlanItem: (PlanItem, PlanItem) -> Unit,
    onDeletePlanItem: (PlanItem) -> Unit,
    onPlanStartFocus: (PlanItem) -> Unit,
    onTopicChange: (String) -> Unit,
    onContentChange: (String) -> Unit,
    onDurationChange: (Int) -> Unit,
    onRecordStudy: () -> Unit,
    onStartStudy: () -> Unit,
    onFinishStudy: () -> Unit,
    onStartReview: () -> Unit,
    onStartNewWords: () -> Unit,
    onNewWordsBatchSizeChange: (Int) -> Unit = {},
    onReviewBatchSizeChange: (Int) -> Unit = {},
    onToggleWordOrder: () -> Unit,
    onAddManualStudy: (Int) -> Unit,
    onOpenBooks: () -> Unit,
    onOpenMistakes: () -> Unit,
    onSearch: (String) -> Unit,
    onClearSearch: () -> Unit,
    onOpenLibraryNote: (String) -> Unit
) {
    if (section == StudyMoreSection.HUB) {
        StudyMoreHub(onSectionChange)
        return
    }

    val noteTree = notesUiState.noteTree
    val noteCount = remember(noteTree) { noteTree.sumOf { it.fileCount() } }
    val noteSubtitle = when {
        noteTree.isNotEmpty() -> "$noteCount 篇 · ${noteTree.size} 个科目"
        notesUiState.isLoading -> "正在加载笔记…"
        else -> "暂无笔记"
    }
    val diaryDate = dailyUiState.selectedDate.ifBlank {
        SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(Date())
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            // 二级板块统一吞掉横向滑动：默认不让横滑冒泡到顶层把全局侧边栏拖出来。
            // 有"上一个 / 下一个"概念的板块（计划 / 日记）在更内层自己接住横滑翻日期，
            // 更内层的手势先拿到事件，因此不会被这里抢走。
            .consumeHorizontalSwipe()
    ) {
        MoreSectionHeader(
            title = section.title,
            subtitle = if (section == StudyMoreSection.NOTES) noteSubtitle else null,
            onBack = { onSectionChange(StudyMoreSection.HUB) },
            trailing = {
                if (section == StudyMoreSection.DIARY) {
                    DiaryDateNav(
                        date = diaryDate,
                        onPrevious = { onDateSelected(shiftDateString(diaryDate, -1)) },
                        onNext = { onDateSelected(shiftDateString(diaryDate, 1)) }
                    )
                }
            }
        )

        when (section) {
            StudyMoreSection.PLAN -> StudyPlanTab(
                planUiState = planUiState,
                onDateSelected = onDateSelected,
                onToggleItem = onTogglePlanItem,
                onAddItem = onAddPlanItem,
                onUpdateItem = onUpdatePlanItem,
                onDeleteItem = onDeletePlanItem,
                onStartFocus = onPlanStartFocus
            )

            StudyMoreSection.VOCAB -> LazyColumn(
                modifier = Modifier.fillMaxWidth(),
                contentPadding = PaddingValues(top = 18.dp, bottom = 28.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp)
            ) {
                item {
                    StudyVocabTab(
                        uiState = vocabUiState,
                        onStartReview = onStartReview,
                        onStartNewWords = onStartNewWords,
                        onToggleOrder = onToggleWordOrder,
                        onNewWordsBatchSizeChange = onNewWordsBatchSizeChange,
                        onReviewBatchSizeChange = onReviewBatchSizeChange,
                        onAddManualStudy = onAddManualStudy,
                        onOpenBooks = onOpenBooks,
                        onOpenMistakes = onOpenMistakes,
                        onSearch = onSearch,
                        onClearSearch = onClearSearch
                    )
                }
            }

            StudyMoreSection.NOTES -> StudyNotesTab(
                notesUiState = notesUiState,
                onOpenNote = onOpenLibraryNote
            )

            StudyMoreSection.DIARY -> StudyDiaryTab(
                dailyUiState = dailyUiState,
                onDateSelected = onDateSelected
            )

            StudyMoreSection.RECORDS -> StudyOverviewTab(
                uiState = uiState,
                dailyUiState = dailyUiState,
                onTopicChange = onTopicChange,
                onContentChange = onContentChange,
                onDurationChange = onDurationChange,
                onRecordStudy = onRecordStudy,
                onStartStudy = onStartStudy,
                onFinishStudy = onFinishStudy
            )

            StudyMoreSection.HUB -> Unit
        }
    }
}

/**
 * 「更多」入口：五个 68dp 列表行。
 *
 * 第三轮设计稿：删掉页首说明，图标去掉底色块，只留 22dp 灰色线性图标。
 */
@Composable
private fun StudyMoreHub(onOpen: (StudyMoreSection) -> Unit) {
    val entries = listOf(
        MoreEntry(StudyMoreSection.PLAN, Icons.Default.EditCalendar, "其他日期、添加或编辑计划项"),
        MoreEntry(StudyMoreSection.VOCAB, Icons.AutoMirrored.Filled.MenuBook, "复习、新词、词书与词典"),
        MoreEntry(StudyMoreSection.NOTES, Icons.AutoMirrored.Filled.Article, "学习库里的知识笔记"),
        MoreEntry(StudyMoreSection.DIARY, Icons.Default.History, "每天的学习日记"),
        MoreEntry(StudyMoreSection.RECORDS, Icons.AutoMirrored.Filled.ListAlt, "最新进度、会话与手动记录")
    )

    LazyColumn(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(top = 28.dp, bottom = 28.dp)
    ) {
        items(entries, key = { it.section.name }) { entry ->
            MoreRow(entry = entry, onClick = { onOpen(entry.section) })
        }
    }
}

@Composable
private fun MoreRow(entry: MoreEntry, onClick: () -> Unit) {
    Column(modifier = Modifier.fillMaxWidth()) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(1.dp)
                .background(MoreHairline)
        )
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = 68.dp)
                .clickable(onClick = onClick),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(
                modifier = Modifier.width(32.dp),
                contentAlignment = Alignment.CenterStart
            ) {
                Icon(
                    imageVector = entry.icon,
                    contentDescription = null,
                    tint = TextSecondary,
                    modifier = Modifier.size(22.dp)
                )
            }
            Spacer(modifier = Modifier.width(10.dp))
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(3.dp)
            ) {
                Text(
                    text = entry.section.title,
                    fontSize = 16.sp,
                    color = TextPrimary
                )
                Text(
                    text = entry.subtitle,
                    fontSize = 12.5f.sp,
                    color = TextTertiary
                )
            }
            Spacer(modifier = Modifier.width(10.dp))
            Icon(
                imageVector = Icons.Default.ChevronRight,
                contentDescription = null,
                tint = TextTertiary,
                modifier = Modifier.size(20.dp)
            )
        }
    }
}

/**
 * 二级页头：返回行 + 30sp 大标题。
 *
 * 设计稿里二级页面不再顶着「学习」页头和 Tab 栏，标题本身就是这一页的层级；
 * 返回键单独占一行，日记的日期选择器跟标题同一行。
 */
@Composable
private fun MoreSectionHeader(
    title: String,
    subtitle: String?,
    onBack: () -> Unit,
    trailing: @Composable RowScope.() -> Unit = {}
) {
    Column(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(56.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(
                modifier = Modifier
                    .size(44.dp)
                    .clip(CircleShape)
                    .clickable(onClick = onBack),
                contentAlignment = Alignment.Center
            ) {
                Icon(
                    imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                    contentDescription = "返回更多",
                    tint = TextPrimary,
                    modifier = Modifier.size(22.dp)
                )
            }
        }
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = 8.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                Text(text = title, style = MaterialTheme.typography.displaySmall)
                if (!subtitle.isNullOrBlank()) {
                    Text(text = subtitle, fontSize = 13.sp, color = TextTertiary)
                }
            }
            trailing.invoke(this)
        }
    }
}

/** 日记标题右侧的日期切换：chevron + 月日 + chevron，等宽数字。 */
@Composable
private fun DiaryDateNav(date: String, onPrevious: () -> Unit, onNext: () -> Unit) {
    val label = remember(date) { formatDiaryDate(date) }
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(
            modifier = Modifier
                .size(40.dp)
                .clip(CircleShape)
                .clickable(onClick = onPrevious),
            contentAlignment = Alignment.Center
        ) {
            Icon(
                imageVector = Icons.Default.ChevronLeft,
                contentDescription = "前一天",
                tint = TextSecondary,
                modifier = Modifier.size(20.dp)
            )
        }
        Text(
            text = label,
            fontSize = 14.5f.sp,
            fontWeight = FontWeight.Medium,
            color = TextPrimary,
            style = TextStyle(fontFeatureSettings = "tnum")
        )
        Box(
            modifier = Modifier
                .size(40.dp)
                .clip(CircleShape)
                .clickable(onClick = onNext),
            contentAlignment = Alignment.Center
        ) {
            Icon(
                imageVector = Icons.Default.ChevronRight,
                contentDescription = "后一天",
                tint = TextSecondary,
                modifier = Modifier.size(20.dp)
            )
        }
    }
}

/** `yyyy-MM-dd` → `10月25日`；解析失败原样返回。 */
private fun formatDiaryDate(date: String): String {
    if (date.isBlank()) return ""
    return runCatching {
        val source = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault())
        val target = SimpleDateFormat("M月d日", Locale.CHINA)
        target.format(source.parse(date) ?: Date())
    }.getOrDefault(date)
}

private data class MoreEntry(
    val section: StudyMoreSection,
    val icon: ImageVector,
    val subtitle: String
)

/** 列表行顶栏线：6% 白。 */
private val MoreHairline = Color(0x0FFFFFFF)
