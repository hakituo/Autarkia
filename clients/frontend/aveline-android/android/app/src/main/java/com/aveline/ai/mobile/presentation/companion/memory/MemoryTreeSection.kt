package com.aveline.ai.mobile.presentation.companion.memory

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
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.domain.models.Memory
import com.aveline.ai.mobile.presentation.companion.companionRowHairline
import com.aveline.ai.mobile.presentation.theme.TextBody
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/** 话题行里色点所在列宽 */
private val TopicDotColumn = 14.dp

/** 条目左侧引导线的 x 位置 */
private val LeafRailX = 21.dp

/** 引导线与条目正文的缩进 */
private val LeafIndent = 34.dp

/**
 * 把「时间桶 → 话题 → 记忆条目」三层树展开成 LazyColumn 的扁平 item。
 *
 * 树节点之间不依靠 LazyColumn 的间距，避免间距把引导线切断；
 * 行与行的呼吸感全部放在各自的 padding 里。
 *
 * 版式按设计稿收紧了一层：时间桶只是两行小字之间的一条气口，话题是一行
 * （色点 + 名称 + 重要数 + 条数 + 箭头），条目直接挂在一条细线下——
 * 不再给每层套卡片和数量徽章。
 */
internal fun LazyListScope.memoryTreeItems(
    groups: List<MemoryBucketNode>,
    isBucketExpanded: (MemoryTimeBucket) -> Boolean,
    isTopicExpanded: (String, String) -> Boolean,
    onToggleBucket: (MemoryTimeBucket) -> Unit,
    onToggleTopic: (String, String) -> Unit,
    onMemoryClick: (Memory) -> Unit,
    onDelete: (Memory) -> Unit
) {
    groups.forEach { bucket ->
        val bucketExpanded = isBucketExpanded(bucket.bucket)

        item(key = "bucket-${bucket.bucket.name}") {
            BucketCaptionRow(
                bucket = bucket,
                expanded = bucketExpanded,
                onToggle = { onToggleBucket(bucket.bucket) }
            )
        }

        if (!bucketExpanded) return@forEach

        bucket.topics.forEach { topic ->
            val topicExpanded = isTopicExpanded(bucket.bucket.name, topic.key)

            item(key = "topic-${bucket.bucket.name}-${topic.key}") {
                TopicRow(
                    topic = topic,
                    expanded = topicExpanded,
                    onToggle = { onToggleTopic(bucket.bucket.name, topic.key) }
                )
            }

            if (topicExpanded) {
                itemsIndexed(
                    items = topic.memories,
                    key = { _, memory -> "leaf-${memory.id}" }
                ) { _, memory ->
                    MemoryLeafRow(
                        memory = memory,
                        onClick = { onMemoryClick(memory) },
                        onLongClick = { onDelete(memory) }
                    )
                }
            }
        }
    }
}

/** 时间桶：左边是「今天 / 昨天」，右边是条数，中间不画任何东西 */
@Composable
private fun BucketCaptionRow(
    bucket: MemoryBucketNode,
    expanded: Boolean,
    onToggle: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onToggle)
            .padding(start = 4.dp, end = 4.dp, top = 14.dp, bottom = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(
            text = bucket.bucket.label,
            style = MaterialTheme.typography.labelMedium.copy(fontSize = 13.sp),
            color = TextTertiary
        )
        Text(
            text = if (expanded) "${bucket.count} 条" else "${bucket.count} 条 · 已收起",
            style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp),
            color = TextTertiary.copy(alpha = 0.7f),
            maxLines = 1
        )
    }
}

/** 话题行：色点 + 名称 + 重要数 + 条数 + 展开箭头 */
@Composable
private fun TopicRow(
    topic: MemoryTopicNode,
    expanded: Boolean,
    onToggle: () -> Unit
) {
    val topicColor = memoryTopicColor(topic.key)
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = 46.dp)
            .companionRowHairline()
            .clickable(onClick = onToggle)
            .padding(start = 4.dp, end = 4.dp, top = 8.dp, bottom = 8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Box(
            modifier = Modifier.width(TopicDotColumn),
            contentAlignment = Alignment.CenterStart
        ) {
            Box(
                modifier = Modifier
                    .size(8.dp)
                    .clip(CircleShape)
                    .background(topicColor)
            )
        }
        Text(
            text = topic.label,
            style = MaterialTheme.typography.bodyLarge.copy(fontSize = 15.sp),
            color = TextPrimary,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f)
        )
        if (topic.importantCount > 0) {
            Text(
                text = "重要 ${topic.importantCount}",
                style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.5.sp),
                color = MemoryImportantColor,
                maxLines = 1
            )
            Spacer(modifier = Modifier.width(8.dp))
        }
        Text(
            text = "${topic.count} 条",
            style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.5.sp),
            color = TextTertiary,
            maxLines = 1
        )
        Spacer(modifier = Modifier.width(4.dp))
        Icon(
            imageVector = if (expanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
            contentDescription = if (expanded) "收起" else "展开",
            tint = TextTertiary,
            modifier = Modifier.size(18.dp)
        )
    }
}

/**
 * 条目：正文 + 一行元信息，整体挂在左侧一条细线下。
 *
 * 点击看详情；长按删除（外层会弹确认对话框）。星标只在详情面板里出现：
 * 每一行都放一颗星，等于让「重要」这个标记在列表里反复抢注意力。
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun MemoryLeafRow(
    memory: Memory,
    onClick: () -> Unit,
    onLongClick: () -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .leafRail()
            .combinedClickable(onClick = onClick, onLongClick = onLongClick)
            .padding(start = LeafIndent, end = 4.dp, top = 8.dp, bottom = 10.dp),
        verticalArrangement = Arrangement.spacedBy(3.dp)
    ) {
        Text(
            text = memory.displayContent,
            style = MaterialTheme.typography.bodyMedium.copy(fontSize = 14.sp, lineHeight = 22.sp),
            color = TextBody,
            maxLines = 4,
            overflow = TextOverflow.Ellipsis
        )
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Text(
                text = formatMemoryClock(memory.createdAt),
                style = MaterialTheme.typography.bodySmall.copy(
                    fontFamily = FontFamily.Monospace,
                    fontSize = 11.5.sp
                ),
                color = TextTertiary,
                maxLines = 1
            )
            Text(
                text = "想起 ${memory.accessCount} 次",
                style = MaterialTheme.typography.bodySmall.copy(fontSize = 11.5.sp),
                color = TextTertiary,
                maxLines = 1
            )
            if (memory.isSummaryOnly) {
                Text(
                    text = "摘要",
                    style = MaterialTheme.typography.bodySmall.copy(fontSize = 11.5.sp),
                    color = TextTertiary,
                    maxLines = 1
                )
            }
            if (memory.isImportant) {
                Text(
                    text = "重要",
                    style = MaterialTheme.typography.bodySmall.copy(fontSize = 11.5.sp),
                    color = MemoryImportantColor,
                    maxLines = 1
                )
            }
        }
    }
}

/** 条目左侧那条竖线：14% 白，从行顶画到行底，相邻条目自然接续 */
private fun Modifier.leafRail(): Modifier = drawBehind {
    val x = LeafRailX.toPx()
    drawLine(
        color = Color.White.copy(alpha = 0.14f),
        start = Offset(x, 0f),
        end = Offset(x, size.height),
        strokeWidth = 1.dp.toPx()
    )
}

/** 树为空时的占位 */
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
