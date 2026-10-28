package com.aveline.ai.mobile.presentation.companion.memory

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.domain.models.MemorySortOrder
import com.aveline.ai.mobile.domain.models.MemoryTopics
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.Surface
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/** 输入框 / 图标按钮的描边：10% 白 */
private val ToolbarBorder = Color(0x1AFFFFFF)

/** 搜索框与 tune 按钮统一 42dp 高，两者底边对齐 */
private val ToolbarHeight = 42.dp

/**
 * 搜索 + 筛选入口一行。
 *
 * 搜索框自己做（不用 TextField 默认 56dp 的最小高度）：这一行只是「找一条记忆」，
 * 比正文还高的输入框会把整页的层级拉平。
 *
 * @param expanded 筛选面板是否展开（tune 按钮的开关）
 */
@Composable
internal fun MemorySearchRow(
    query: String,
    hasFilters: Boolean,
    expanded: Boolean,
    onQueryChange: (String) -> Unit,
    onToggleFilters: () -> Unit,
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        Row(
            modifier = Modifier
                .weight(1f)
                .height(ToolbarHeight)
                .clip(RoundedCornerShape(12.dp))
                .background(Surface)
                .border(BorderStroke(1.dp, ToolbarBorder), RoundedCornerShape(12.dp))
                .padding(horizontal = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Icon(
                imageVector = Icons.Default.Search,
                contentDescription = null,
                tint = TextTertiary,
                modifier = Modifier.size(18.dp)
            )
            BasicTextField(
                value = query,
                onValueChange = onQueryChange,
                singleLine = true,
                modifier = Modifier.weight(1f),
                textStyle = MaterialTheme.typography.bodyMedium.copy(
                    fontSize = 14.sp,
                    color = TextPrimary
                ),
                cursorBrush = SolidColor(Accent),
                decorationBox = { innerTextField ->
                    Box(contentAlignment = Alignment.CenterStart) {
                        if (query.isEmpty()) {
                            Text(
                                text = "搜索记忆",
                                style = MaterialTheme.typography.bodyMedium.copy(fontSize = 14.sp),
                                color = TextTertiary,
                                maxLines = 1
                            )
                        }
                        innerTextField()
                    }
                }
            )
        }

        Box(
            modifier = Modifier
                .size(ToolbarHeight)
                .clip(RoundedCornerShape(12.dp))
                .border(
                    BorderStroke(1.dp, if (expanded || hasFilters) Accent.copy(alpha = 0.45f) else ToolbarBorder),
                    RoundedCornerShape(12.dp)
                )
                .clickable(onClick = onToggleFilters),
            contentAlignment = Alignment.Center
        ) {
            Icon(
                imageVector = Icons.Default.Tune,
                contentDescription = if (expanded) "收起筛选" else "筛选",
                tint = if (expanded || hasFilters) Accent else TextSecondary,
                modifier = Modifier.size(20.dp)
            )
        }
    }
}

/**
 * 筛选面板：话题 + 只看重要 + 清除。
 *
 * 话题曾经是概览卡里的一排 chips（还兼着三个彩色大数字）。数字并进下面那行计数，
 * chips 收进 tune 按钮——不筛的时候它们不该常驻占一整屏高度。
 */
@Composable
internal fun MemoryFilterPanel(
    topics: List<Pair<String, Int>>,
    totalCount: Int,
    selectedTopic: String?,
    showImportantOnly: Boolean,
    hasFilters: Boolean,
    onTopicSelect: (String?) -> Unit,
    onToggleImportantOnly: () -> Unit,
    onClearFilters: () -> Unit,
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        FilterPill(
            label = "只看重要",
            count = null,
            color = MemoryImportantColor,
            selected = showImportantOnly,
            onClick = onToggleImportantOnly
        )
        FilterPill(
            label = "全部",
            count = totalCount,
            color = Accent,
            selected = selectedTopic == null,
            onClick = { onTopicSelect(null) }
        )
        topics.forEach { (key, count) ->
            FilterPill(
                label = MemoryTopics.labelOf(key),
                count = count,
                color = memoryTopicColor(key),
                selected = selectedTopic == key,
                onClick = { onTopicSelect(key) }
            )
        }
        if (hasFilters) {
            Text(
                text = "清除",
                style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.5.sp),
                color = TextTertiary,
                modifier = Modifier
                    .clickable(onClick = onClearFilters)
                    .padding(horizontal = 6.dp, vertical = 6.dp)
            )
        }
    }
}

@Composable
private fun FilterPill(
    label: String,
    count: Int?,
    color: Color,
    selected: Boolean,
    onClick: () -> Unit
) {
    Row(
        modifier = Modifier
            .clip(RoundedCornerShape(9.dp))
            .background(if (selected) color.copy(alpha = 0.18f) else Color.Transparent)
            .border(
                BorderStroke(1.dp, if (selected) color.copy(alpha = 0.5f) else ToolbarBorder),
                RoundedCornerShape(9.dp)
            )
            .clickable(onClick = onClick)
            .padding(horizontal = 10.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        if (count != null) {
            Box(
                modifier = Modifier
                    .size(6.dp)
                    .clip(CircleShape)
                    .background(color)
            )
            Spacer(modifier = Modifier.width(6.dp))
        }
        Text(
            text = label,
            style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.5.sp),
            color = if (selected) TextPrimary else TextSecondary,
            maxLines = 1
        )
        count?.let {
            Spacer(modifier = Modifier.width(4.dp))
            Text(
                text = "$it",
                style = MaterialTheme.typography.bodySmall.copy(fontSize = 11.5.sp),
                color = TextTertiary,
                maxLines = 1
            )
        }
    }
}

/** 计数一行：214 条 · 18 条重要 · 26 个话题（右侧是全部展开 / 收起） */
@Composable
internal fun MemorySummaryRow(
    summary: String,
    actionLabel: String,
    onAction: () -> Unit,
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(
            text = summary,
            style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.5.sp),
            color = TextTertiary,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f)
        )
        Text(
            text = actionLabel,
            style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.5.sp),
            color = TextSecondary,
            maxLines = 1,
            modifier = Modifier
                .clickable(onClick = onAction)
                .padding(start = 12.dp, top = 2.dp, bottom = 2.dp)
        )
    }
}

/**
 * 排序：四个文字 Tab（最新 / 最早 / 常想起 / 重要）。
 *
 * 原来是「排序：最新优先 ▾」的下拉 chip——排序是这页最常用的操作之一，
 * 每换一次都要点两下、还要在弹层里找。四个词横排开，一次点击到位。
 */
@Composable
internal fun MemorySortTabs(
    sortOrder: MemorySortOrder,
    onSortOrderChange: (MemorySortOrder) -> Unit,
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(16.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        MemorySortOrder.entries.forEach { order ->
            val selected = order == sortOrder
            Row(
                modifier = Modifier
                    .height(32.dp)
                    .clickable { onSortOrderChange(order) },
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = memorySortLabel(order),
                    style = MaterialTheme.typography.bodySmall.copy(fontSize = 13.5.sp),
                    color = if (selected) TextPrimary else TextTertiary,
                    fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
                    maxLines = 1
                )
                if (selected) {
                    Spacer(modifier = Modifier.width(4.dp))
                    Icon(
                        imageVector = Icons.Default.Check,
                        contentDescription = null,
                        tint = TextPrimary,
                        modifier = Modifier.size(12.dp)
                    )
                }
            }
        }
    }
}

/** 排序方式中文标签 */
internal fun memorySortLabel(order: MemorySortOrder): String = when (order) {
    MemorySortOrder.NEWEST_FIRST -> "最新"
    MemorySortOrder.OLDEST_FIRST -> "最早"
    MemorySortOrder.MOST_ACCESSED -> "常想起"
    MemorySortOrder.MOST_IMPORTANT -> "重要"
}
