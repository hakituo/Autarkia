package com.aveline.ai.mobile.presentation.study

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
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
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.domain.models.DiaryEntry
import com.aveline.ai.mobile.presentation.theme.TextBody
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 学习日记。
 *
 * 第三轮设计稿把「按作者分卡」改成一条时间流：
 * - 作者筛选从 FilterChip 换成与顶部一致的文字 Tab，选中只靠字重和亮度；
 * - 每条日记注明「时间 + 作者 · 类型」，天蓝底类型标签删掉；
 * - 「想法」从天蓝底块改成左侧一条细线的引文；
 * - 日期选择器已挪到页面标题右侧（见 StudyMoreTab），这里只保留左右滑翻日期。
 *
 * **作者名单完全来自后端数据**：后端返回哪些角色当天有日记，这里就呈现哪些角色，
 * 前端不维护任何角色名单 —— 角色会增删，写死的名单既会挡住新角色写出的日记，
 * 也会挡住「以前注册过、现在没注册」的角色留下的历史日记。展示名同理，
 * 直接取后端给的 [DiaryEntry.authorLabel]，不在本地维护 role_id → 中文名的映射。
 */
@Composable
fun StudyDiaryTab(
    dailyUiState: StudyDailyUiState,
    onDateSelected: (String) -> Unit,
) {
    val selectedDate = dailyUiState.selectedDate.ifBlank {
        SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(Date())
    }
    val diaryEntries = dailyUiState.diaryEntries

    // 人物切换: null=全部, 其余为作者 scope(user / aveline / ling / ye …)
    var selectedSource by remember { mutableStateOf<String?>(null) }

    // 当天出现的作者（source → 展示名），顺序：主人手记置顶，其余按当天首次出现顺序。
    val authors = remember(diaryEntries) {
        val labels = LinkedHashMap<String, String>()
        val ownerEntry = diaryEntries.firstOrNull { it.source == "user" }
        if (ownerEntry != null) {
            labels["user"] = ownerEntry.authorLabel
        }
        diaryEntries.forEach { entry ->
            if (!labels.containsKey(entry.source)) {
                labels[entry.source] = entry.authorLabel
            }
        }
        labels.toList()
    }

    // 一条按时间倒序的流：作者筛选只做过滤，不再分组。
    val entries = remember(diaryEntries, selectedSource) {
        diaryEntries
            .filter { selectedSource == null || it.source == selectedSource }
            .sortedByDescending { it.timestamp }
    }
    val counts = remember(diaryEntries) { diaryEntries.groupingBy { it.source }.eachCount() }

    // 切到另一天时，前一天选中的作者可能今天没写日记：退回「全部」，避免只剩一句空提示。
    LaunchedEffect(authors) {
        if (selectedSource != null && authors.none { it.first == selectedSource }) {
            selectedSource = null
        }
    }

    // 左滑/右滑与标题右侧箭头共用同一条跳日期路径
    fun gotoDate(newDate: String) {
        onDateSelected(newDate)
    }

    LazyColumn(
        modifier = Modifier
            .fillMaxWidth()
            // 左右滑动看前一天/后一天的日记;同时消费掉横滑,避免冒泡到顶层把侧边栏拖出来
            .horizontalPagingSwipe(
                onPrevious = { gotoDate(shiftDateString(selectedDate, -1)) },
                onNext = { gotoDate(shiftDateString(selectedDate, 1)) }
            ),
        contentPadding = PaddingValues(top = 14.dp, bottom = 28.dp)
    ) {
        if (diaryEntries.isNotEmpty()) {
            item {
                AuthorTabs(
                    authors = authors,
                    totalCount = diaryEntries.size,
                    counts = counts,
                    selectedSource = selectedSource,
                    onSelect = { selectedSource = it }
                )
            }
        }

        when {
            diaryEntries.isEmpty() -> item { EmptyDiary("今日暂无日记") }
            entries.isEmpty() -> item { EmptyDiary("该作者今日暂无日记") }
            else -> items(
                items = entries,
                key = { entry -> entry.id.ifBlank { "${entry.timestamp}-${entry.source}" } }
            ) { entry ->
                DiaryStreamEntry(entry = entry)
            }
        }
    }
}

/**
 * 作者筛选：文字 Tab。
 *
 * 选中项用正文色 + SemiBold，未选中降到 Faint；数量跟在名字后面，不加底色。
 */
@Composable
private fun AuthorTabs(
    authors: List<Pair<String, String>>,
    totalCount: Int,
    counts: Map<String, Int>,
    selectedSource: String?,
    onSelect: (String?) -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(bottom = 8.dp)
            .horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(22.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        AuthorTab(
            label = "全部",
            count = totalCount,
            selected = selectedSource == null,
            onClick = { onSelect(null) }
        )
        authors.forEach { (source, label) ->
            AuthorTab(
                label = label,
                count = counts[source] ?: 0,
                selected = selectedSource == source,
                onClick = { onSelect(source) }
            )
        }
    }
}

@Composable
private fun AuthorTab(label: String, count: Int, selected: Boolean, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .height(36.dp)
            .clickable(onClick = onClick),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            text = label,
            fontSize = 15.sp,
            fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
            color = if (selected) TextPrimary else TextTertiary
        )
        Spacer(modifier = Modifier.width(5.dp))
        Text(
            text = count.toString(),
            fontSize = 12.5f.sp,
            color = TextTertiary
        )
    }
}

/** 时间流里的一条：细线分隔，时间 + 作者 · 类型，正文，「想法」为细线引文。 */
@Composable
private fun DiaryStreamEntry(entry: DiaryEntry) {
    Column(modifier = Modifier.fillMaxWidth()) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(1.dp)
                .background(DiaryHairline)
        )
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 18.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Row(
                horizontalArrangement = Arrangement.spacedBy(10.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = entry.timeStr,
                    fontSize = 12.5f.sp,
                    fontFamily = FontFamily.Monospace,
                    color = TextSecondary
                )
                Text(
                    text = "${entry.authorLabel} · ${diaryTypeLabel(entry.type)}",
                    fontSize = 12.5f.sp,
                    color = TextTertiary
                )
            }

            NotesMarkdownRenderer(
                text = entry.content,
                bodyStyle = DiaryBodyStyle,
                documentStyle = true
            )

            val thought = entry.thought
            if (!thought.isNullOrBlank() && thought != "auto_generated_daily_summary") {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(IntrinsicSize.Min)
                ) {
                    Box(
                        modifier = Modifier
                            .width(1.dp)
                            .fillMaxHeight()
                            .background(DiaryQuoteRule)
                    )
                    Spacer(modifier = Modifier.width(12.dp))
                    Text(
                        text = thought,
                        fontSize = 14.sp,
                        lineHeight = 23.8.sp,
                        color = TextSecondary
                    )
                }
            }
        }
    }
}

@Composable
private fun EmptyDiary(text: String) {
    Text(
        text = text,
        fontSize = 14.sp,
        color = TextTertiary,
        modifier = Modifier.padding(top = 20.dp, bottom = 8.dp)
    )
}

/** 后端 type 字段转中文标签 */
private fun diaryTypeLabel(type: String): String = when (type) {
    "daily_summary" -> "每日总结"
    "proactive" -> "主动记录"
    "daily" -> "日记"
    else -> type
}

/** 日记正文：15.5sp / 1.75 行高。 */
private val DiaryBodyStyle = TextStyle(
    fontSize = 15.5f.sp,
    lineHeight = 27.sp,
    color = TextBody
)

/** 列表行顶栏线：8% 白。 */
private val DiaryHairline = Color(0x14FFFFFF)

/** 想法引文的竖线：18% 白。 */
private val DiaryQuoteRule = Color(0x2EFFFFFF)
