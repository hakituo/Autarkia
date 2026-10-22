package com.aveline.ai.mobile.presentation.companion.memory

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.domain.models.Memory
import com.aveline.ai.mobile.domain.models.MemoryTopics
import com.aveline.ai.mobile.presentation.components.SectionCard
import com.aveline.ai.mobile.presentation.theme.Primary
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 记忆概览卡：总量、重要数、话题分布。
 *
 * 话题 chips 同时承担筛选入口，替代原先按 `MemoryType` 的筛选——
 * 后端历史记忆的 category 基本都落在 uncategorized，按类型筛永远是空列表。
 */
@Composable
internal fun MemoryOverviewCard(
    memories: List<Memory>,
    selectedTopic: String?,
    onTopicSelect: (String?) -> Unit
) {
    val visible = remember(memories) { memories.filter { it.hasVisibleContent() } }
    val topics = remember(visible) { topicCounts(visible) }
    val importantCount = remember(visible) { visible.count { it.isImportant } }

    SectionCard(title = "记忆档案") {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(28.dp),
            verticalAlignment = Alignment.Bottom
        ) {
            OverviewMetric(value = visible.size, label = "条记忆", color = TextPrimary)
            OverviewMetric(value = importantCount, label = "标为重要", color = MemoryImportantColor)
            OverviewMetric(value = topics.size, label = "个话题", color = TextPrimary)
        }

        Spacer(modifier = Modifier.height(14.dp))

        LazyRow(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            contentPadding = PaddingValues(end = 4.dp)
        ) {
            item(key = "topic-all") {
                TopicChip(
                    label = "全部",
                    count = visible.size,
                    color = Primary,
                    selected = selectedTopic == null,
                    onClick = { onTopicSelect(null) }
                )
            }
            items(items = topics, key = { it.first }) { (key, count) ->
                val topicColor = memoryTopicColor(key)
                TopicChip(
                    label = MemoryTopics.labelOf(key),
                    count = count,
                    color = topicColor,
                    selected = selectedTopic == key,
                    onClick = { onTopicSelect(key) }
                )
            }
        }
    }
}

@Composable
private fun OverviewMetric(value: Int, label: String, color: Color) {
    Column {
        Text(
            text = "$value",
            style = MaterialTheme.typography.headlineSmall,
            color = color,
            fontWeight = FontWeight.SemiBold
        )
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            color = TextTertiary
        )
    }
}

@Composable
private fun TopicChip(
    label: String,
    count: Int,
    color: Color,
    selected: Boolean,
    onClick: () -> Unit
) {
    FilterChip(
        selected = selected,
        onClick = onClick,
        label = {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = label,
                    style = MaterialTheme.typography.labelMedium,
                    color = if (selected) Color.White else TextSecondary
                )
                Spacer(modifier = Modifier.size(4.dp))
                Text(
                    text = "$count",
                    style = MaterialTheme.typography.labelSmall,
                    color = if (selected) Color.White.copy(alpha = 0.8f) else TextTertiary
                )
            }
        },
        colors = FilterChipDefaults.filterChipColors(
            selectedContainerColor = color.copy(alpha = 0.85f),
            containerColor = Color(0x14000000)
        ),
        border = null,
        modifier = Modifier.padding(vertical = 2.dp)
    )
}
