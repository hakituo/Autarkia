package com.aveline.ai.mobile.presentation.companion.memory

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.domain.models.Memory
import com.aveline.ai.mobile.domain.models.MemoryRelation
import com.aveline.ai.mobile.domain.models.MemoryType
import com.aveline.ai.mobile.presentation.theme.Primary
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 记忆详情弹窗。
 *
 * 展示完整内容（可长按复制）、话题、时间与访问次数，并提供重要标记和删除。
 * 底部「想起…」是关系图上的邻居：点进去原地换成那条记忆，等于在记忆网络里走一步。
 *
 * @param relations 当前记忆的关联邻域（不含自身）
 * @param relationsLoading 是否正在拉取关联
 * @param onRelationClick 点击关联记忆，打开它的详情
 */
@Composable
internal fun MemoryDetailDialog(
    memory: Memory,
    relations: List<MemoryRelation>,
    relationsLoading: Boolean,
    onClose: () -> Unit,
    onToggleImportant: () -> Unit,
    onDelete: () -> Unit,
    onRelationClick: (Memory) -> Unit
) {
    val topicColor = memoryTopicColor(memory.topicKey)

    AlertDialog(
        onDismissRequest = onClose,
        title = {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Box(
                    modifier = Modifier
                        .size(8.dp)
                        .background(topicColor, CircleShape)
                )
                Text(
                    text = memory.topicLabel,
                    style = MaterialTheme.typography.titleMedium,
                    color = topicColor,
                    fontWeight = FontWeight.SemiBold
                )
                if (memory.type != MemoryType.UNCATEGORIZED && memory.type != MemoryType.UNKNOWN) {
                    Surface(
                        color = memoryTypeColor(memory.type).copy(alpha = 0.18f),
                        shape = RoundedCornerShape(4.dp)
                    ) {
                        Text(
                            text = memory.formattedType,
                            style = MaterialTheme.typography.labelSmall,
                            color = memoryTypeColor(memory.type),
                            modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
                        )
                    }
                }
                Spacer(modifier = Modifier.weight(1f))
                if (memory.isImportant) {
                    Icon(
                        imageVector = Icons.Default.Star,
                        contentDescription = "重要",
                        tint = MemoryImportantColor,
                        modifier = Modifier.size(18.dp)
                    )
                }
            }
        },
        text = {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                if (memory.isSummaryOnly) {
                    Text(
                        text = "这条记忆的原文未回填，以下为蒸馏摘要",
                        style = MaterialTheme.typography.labelSmall,
                        color = MemoryImportantColor.copy(alpha = 0.85f)
                    )
                }
                SelectionContainer {
                    Text(
                        text = memory.displayContent,
                        style = MaterialTheme.typography.bodyLarge,
                        color = TextPrimary
                    )
                }
                Spacer(modifier = Modifier.height(2.dp))
                MemoryMetaRow(label = "创建时间", value = formatMemoryTimestamp(memory.createdAt))
                MemoryMetaRow(label = "记忆时间", value = memory.formattedCreatedAt)
                MemoryMetaRow(label = "访问次数", value = "${memory.accessCount}")
                if (memory.tags.isNotEmpty()) {
                    MemoryMetaRow(
                        label = "标签",
                        value = memory.tags.take(6).joinToString(" · ")
                    )
                }
                if (relationsLoading || relations.isNotEmpty()) {
                    MemoryRelationSection(
                        relations = relations,
                        isLoading = relationsLoading,
                        onRelationClick = onRelationClick
                    )
                }
                Surface(
                    color = Color(0x14000000),
                    shape = RoundedCornerShape(8.dp)
                ) {
                    Text(
                        text = "点击星标可标记为重要；长按列表中的记忆可快速删除。",
                        style = MaterialTheme.typography.labelSmall,
                        color = TextTertiary,
                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 8.dp)
                    )
                }
            }
        },
        confirmButton = {
            TextButton(onClick = onToggleImportant) {
                Text(
                    text = if (memory.isImportant) "取消重要" else "标为重要",
                    color = if (memory.isImportant) TextSecondary else MemoryImportantColor
                )
            }
        },
        dismissButton = {
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                TextButton(
                    onClick = onDelete,
                    colors = ButtonDefaults.textButtonColors(
                        contentColor = MaterialTheme.colorScheme.error
                    )
                ) {
                    Text("删除")
                }
                TextButton(onClick = onClose) {
                    Text("关闭")
                }
            }
        }
    )
}

/**
 * 详情里的「想起…」：关系图上的邻居。
 *
 * 关系名由后端给出（同一轮 / 同一件事 / 接着说 / 同一话题），前端不再自己推断，
 * 避免和后端的关系判定出现两套说法。
 */
@Composable
private fun MemoryRelationSection(
    relations: List<MemoryRelation>,
    isLoading: Boolean,
    onRelationClick: (Memory) -> Unit
) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = "想起…",
                style = MaterialTheme.typography.labelMedium,
                color = TextSecondary,
                fontWeight = FontWeight.SemiBold
            )
            if (relations.isNotEmpty()) {
                Text(
                    text = "${relations.size} 条",
                    style = MaterialTheme.typography.labelSmall,
                    color = TextTertiary
                )
            }
        }
        if (isLoading) {
            Text(
                text = "正在找关联…",
                style = MaterialTheme.typography.labelSmall,
                color = TextTertiary
            )
            return@Column
        }
        relations.forEach { relation ->
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(8.dp))
                    .background(Color(0x0F000000))
                    .clickable { onRelationClick(relation.memory) }
                    .padding(horizontal = 10.dp, vertical = 8.dp),
                verticalAlignment = Alignment.Top
            ) {
                Surface(
                    color = Primary.copy(alpha = 0.14f),
                    shape = RoundedCornerShape(4.dp)
                ) {
                    Text(
                        text = relation.relationLabel,
                        style = MaterialTheme.typography.labelSmall,
                        color = Primary,
                        modifier = Modifier.padding(horizontal = 5.dp, vertical = 2.dp)
                    )
                }
                Spacer(modifier = Modifier.size(8.dp))
                Text(
                    text = relation.preview.ifBlank { "（无正文）" },
                    style = MaterialTheme.typography.bodySmall,
                    color = TextSecondary,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f)
                )
            }
        }
    }
}

/** 详情里的元信息行 */
@Composable
private fun MemoryMetaRow(label: String, value: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 2.dp),
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            color = TextTertiary
        )
        Text(
            text = value,
            style = MaterialTheme.typography.bodySmall,
            color = TextSecondary
        )
    }
}
