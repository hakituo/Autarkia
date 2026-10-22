package com.aveline.ai.mobile.presentation.companion.memory

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.StarBorder
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.domain.models.Memory
import com.aveline.ai.mobile.presentation.theme.CardBackground
import com.aveline.ai.mobile.presentation.theme.CardBorder
import com.aveline.ai.mobile.presentation.theme.Primary
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 把「时间桶 → 话题 → 记忆条目」三层树展开成 LazyColumn 的扁平 item。
 *
 * 树节点之间不依靠 LazyColumn 的间距，避免间距把引导线切断；
 * 行与行的呼吸感全部放在各自的 padding 里。
 */
internal fun LazyListScope.memoryTreeItems(
    groups: List<MemoryBucketNode>,
    isBucketExpanded: (MemoryTimeBucket) -> Boolean,
    isTopicExpanded: (String, String) -> Boolean,
    onToggleBucket: (MemoryTimeBucket) -> Unit,
    onToggleTopic: (String, String) -> Unit,
    onMemoryClick: (Memory) -> Unit,
    onToggleImportant: (Memory) -> Unit,
    onDelete: (Memory) -> Unit
) {
    groups.forEach { bucket ->
        val bucketExpanded = isBucketExpanded(bucket.bucket)

        item(key = "bucket-${bucket.bucket.name}") {
            BucketHeaderRow(
                bucket = bucket,
                expanded = bucketExpanded,
                onToggle = { onToggleBucket(bucket.bucket) }
            )
        }

        if (!bucketExpanded) return@forEach

        bucket.topics.forEachIndexed { topicIndex, topic ->
            val topicExpanded = isTopicExpanded(bucket.bucket.name, topic.key)
            val lastTopic = topicIndex == bucket.topics.lastIndex

            item(key = "topic-${bucket.bucket.name}-${topic.key}") {
                TopicHeaderRow(
                    topic = topic,
                    isLast = lastTopic,
                    expanded = topicExpanded,
                    onToggle = { onToggleTopic(bucket.bucket.name, topic.key) }
                )
            }

            if (topicExpanded) {
                itemsIndexed(
                    items = topic.memories,
                    key = { _, memory -> "leaf-${memory.id}" }
                ) { index, memory ->
                    MemoryLeafRow(
                        memory = memory,
                        isLast = index == topic.memories.lastIndex,
                        onClick = { onMemoryClick(memory) },
                        onToggleImportant = { onToggleImportant(memory) },
                        onDelete = { onDelete(memory) }
                    )
                }
            }
        }
    }
}

/**
 * 树工具栏：条目总数 + 展开/收起动作。
 *
 * 动作文案由调用方决定：默认是「全部展开 / 全部收起」，
 * 存在搜索或话题筛选时改为「重置筛选」，避免收起动作在强制展开下失效。
 */
@Composable
internal fun MemoryTreeToolbar(
    total: Int,
    actionLabel: String,
    onAction: () -> Unit,
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(start = 4.dp, end = 4.dp, top = 4.dp, bottom = 2.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            text = "记忆树",
            style = MaterialTheme.typography.titleSmall,
            color = TextPrimary,
            fontWeight = FontWeight.SemiBold
        )
        Spacer(modifier = Modifier.size(6.dp))
        Text(
            text = "$total 条",
            style = MaterialTheme.typography.labelSmall,
            color = TextTertiary
        )
        Spacer(modifier = Modifier.weight(1f))
        TextButton(onClick = onAction) {
            Text(
                text = actionLabel,
                style = MaterialTheme.typography.labelMedium,
                color = TextSecondary
            )
        }
    }
}

@Composable
private fun BucketHeaderRow(
    bucket: MemoryBucketNode,
    expanded: Boolean,
    onToggle: () -> Unit
) {
    Column {
        HorizontalDivider(color = CardBorder, thickness = 1.dp)
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable(onClick = onToggle)
                .padding(horizontal = 4.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(
                modifier = Modifier
                    .width(3.dp)
                    .height(18.dp)
                    .background(Primary, RoundedCornerShape(2.dp))
            )
            Spacer(modifier = Modifier.width(10.dp))
            Text(
                text = bucket.bucket.label,
                style = MaterialTheme.typography.titleSmall,
                color = TextPrimary,
                fontWeight = FontWeight.SemiBold
            )
            Spacer(modifier = Modifier.width(8.dp))
            CountBadge(count = bucket.count)
            Spacer(modifier = Modifier.weight(1f))
            if (bucket.importantCount > 0) {
                Text(
                    text = "${bucket.importantCount} 条重要",
                    style = MaterialTheme.typography.labelSmall,
                    color = MemoryImportantColor
                )
                Spacer(modifier = Modifier.width(6.dp))
            }
            ExpandIcon(expanded = expanded)
        }
    }
}

@Composable
private fun TopicHeaderRow(
    topic: MemoryTopicNode,
    isLast: Boolean,
    expanded: Boolean,
    onToggle: () -> Unit
) {
    val topicColor = memoryTopicColor(topic.key)
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .drawBehind { drawTreeRail(x = 14.dp.toPx(), isLast = isLast, branchLength = 10.dp.toPx()) }
            .clickable(onClick = onToggle)
            .padding(start = 34.dp, end = 4.dp, top = 8.dp, bottom = 8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Box(
            modifier = Modifier
                .size(8.dp)
                .background(topicColor, CircleShape)
        )
        Spacer(modifier = Modifier.width(8.dp))
        Text(
            text = topic.label,
            style = MaterialTheme.typography.labelLarge,
            color = TextSecondary,
            fontWeight = FontWeight.Medium
        )
        Spacer(modifier = Modifier.width(6.dp))
        Text(
            text = "${topic.count}",
            style = MaterialTheme.typography.labelSmall,
            color = TextTertiary
        )
        Spacer(modifier = Modifier.weight(1f))
        if (topic.importantCount > 0) {
            Icon(
                imageVector = Icons.Default.Star,
                contentDescription = null,
                tint = MemoryImportantColor,
                modifier = Modifier.size(12.dp)
            )
            Spacer(modifier = Modifier.width(2.dp))
            Text(
                text = "${topic.importantCount}",
                style = MaterialTheme.typography.labelSmall,
                color = MemoryImportantColor
            )
            Spacer(modifier = Modifier.width(6.dp))
        }
        ExpandIcon(expanded = expanded, size = 18)
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun MemoryLeafRow(
    memory: Memory,
    isLast: Boolean,
    onClick: () -> Unit,
    onToggleImportant: () -> Unit,
    onDelete: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .drawBehind { drawTreeRail(x = 32.dp.toPx(), isLast = isLast, branchLength = 10.dp.toPx()) }
            .padding(start = 52.dp, end = 4.dp, top = 3.dp, bottom = 3.dp)
    ) {
        Surface(
            modifier = Modifier
                .fillMaxWidth()
                .combinedClickable(onClick = onClick, onLongClick = onDelete),
            shape = RoundedCornerShape(12.dp),
            color = if (memory.isImportant) MemoryImportantColor.copy(alpha = 0.08f) else CardBackground,
            border = BorderStroke(
                width = 1.dp,
                color = if (memory.isImportant) MemoryImportantColor.copy(alpha = 0.28f) else CardBorder
            )
        ) {
            Column(modifier = Modifier.padding(start = 12.dp, top = 10.dp, end = 6.dp, bottom = 8.dp)) {
                Text(
                    text = memory.displayContent,
                    style = MaterialTheme.typography.bodyMedium,
                    color = TextPrimary,
                    maxLines = 3,
                    overflow = TextOverflow.Ellipsis
                )
                Spacer(modifier = Modifier.height(4.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    if (memory.isSummaryOnly) {
                        Surface(
                            color = MemoryImportantColor.copy(alpha = 0.12f),
                            shape = RoundedCornerShape(4.dp)
                        ) {
                            Text(
                                text = "摘要",
                                style = MaterialTheme.typography.labelSmall,
                                color = MemoryImportantColor.copy(alpha = 0.9f),
                                modifier = Modifier.padding(horizontal = 5.dp, vertical = 1.dp)
                            )
                        }
                        Spacer(modifier = Modifier.width(6.dp))
                    }
                    Text(
                        text = memory.formattedCreatedAt,
                        style = MaterialTheme.typography.labelSmall,
                        color = TextTertiary
                    )
                    Spacer(modifier = Modifier.weight(1f))
                    IconButton(
                        onClick = onToggleImportant,
                        modifier = Modifier.size(26.dp)
                    ) {
                        Icon(
                            imageVector = if (memory.isImportant) Icons.Default.Star else Icons.Default.StarBorder,
                            contentDescription = if (memory.isImportant) "取消重要" else "标记重要",
                            tint = if (memory.isImportant) MemoryImportantColor else TextTertiary,
                            modifier = Modifier.size(16.dp)
                        )
                    }
                }
            }
        }
    }
}

@Composable
internal fun CountBadge(count: Int, color: Color = TextSecondary) {
    Surface(
        color = Color(0x1AFFFFFF),
        shape = RoundedCornerShape(6.dp)
    ) {
        Text(
            text = "$count",
            style = MaterialTheme.typography.labelSmall,
            color = color,
            modifier = Modifier.padding(horizontal = 6.dp, vertical = 1.dp)
        )
    }
}

@Composable
private fun ExpandIcon(expanded: Boolean, size: Int = 20) {
    Icon(
        imageVector = if (expanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
        contentDescription = if (expanded) "收起" else "展开",
        tint = TextTertiary,
        modifier = Modifier.size(size.dp)
    )
}

/** 画一段「├─ / └─」引导线，竖线在Ye行之间自然接续 */
private fun DrawScope.drawTreeRail(x: Float, isLast: Boolean, branchLength: Float) {
    val stroke = 1.dp.toPx()
    val midY = size.height / 2f
    val endY = if (isLast) midY else size.height
    drawLine(
        color = MemoryTreeLineColor,
        start = Offset(x, 0f),
        end = Offset(x, endY),
        strokeWidth = stroke,
        cap = StrokeCap.Round
    )
    drawLine(
        color = MemoryTreeLineColor,
        start = Offset(x, midY),
        end = Offset(x + branchLength, midY),
        strokeWidth = stroke,
        cap = StrokeCap.Round
    )
}

/** 树为空时的占位（放在 SectionCard 内） */
@Composable
internal fun EmptyMemoryState(
    hasFilters: Boolean,
    onClearFilters: () -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Text(
            text = if (hasFilters) "没有找到匹配的记忆" else "这里还没有记忆",
            style = MaterialTheme.typography.bodyMedium,
            color = TextSecondary
        )
        if (hasFilters) {
            TextButton(onClick = onClearFilters) {
                Text("清除筛选条件")
            }
        }
    }
}
