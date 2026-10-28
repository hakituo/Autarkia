package com.aveline.ai.mobile.presentation.companion.memory

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.StarBorder
import androidx.compose.material3.BottomSheetDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.domain.models.Memory
import com.aveline.ai.mobile.domain.models.MemoryRelation
import com.aveline.ai.mobile.domain.models.MemoryType
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.Danger
import com.aveline.ai.mobile.presentation.theme.Edge
import com.aveline.ai.mobile.presentation.theme.Line
import com.aveline.ai.mobile.presentation.theme.SurfaceHigh
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 记忆详情底部面板。
 *
 * 原来是 AlertDialog：标题行塞了话题色点、类型徽章、星标，正文、四行元信息、
 * 邻域列表和两个按钮全挤在一个居中的小框里，长记忆只能滚动一个小窗口。
 * 改成底部面板后正文有整屏宽度，星标回到右上角，删除用危险色文字放在左下。
 *
 * @param relations 当前记忆的关联邻域（不含自身）
 * @param relationsLoading 是否正在拉取关联
 * @param onRelationClick 点击关联记忆，面板原地换成那条记忆，等于在记忆网络里走一步
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun MemoryDetailSheet(
    memory: Memory,
    relations: List<MemoryRelation>,
    relationsLoading: Boolean,
    onClose: () -> Unit,
    onToggleImportant: () -> Unit,
    onDelete: () -> Unit,
    onRelationClick: (Memory) -> Unit
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)

    ModalBottomSheet(
        onDismissRequest = onClose,
        sheetState = sheetState,
        containerColor = SurfaceHigh,
        contentColor = TextPrimary,
        dragHandle = { BottomSheetDefaults.DragHandle(color = Color.White.copy(alpha = 0.2f)) }
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .verticalScroll(rememberScrollState())
                .padding(start = 20.dp, end = 20.dp, bottom = 20.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text(
                    text = memoryTopicLine(memory),
                    style = MaterialTheme.typography.bodySmall.copy(fontSize = 13.sp),
                    color = TextTertiary,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                IconButton(onClick = onToggleImportant) {
                    Icon(
                        imageVector = if (memory.isImportant) Icons.Default.Star else Icons.Default.StarBorder,
                        contentDescription = if (memory.isImportant) "取消重要" else "标为重要",
                        tint = if (memory.isImportant) MemoryImportantColor else TextTertiary,
                        modifier = Modifier.size(22.dp)
                    )
                }
            }

            if (memory.isSummaryOnly) {
                Text(
                    text = "这条记忆的原文未回填，以下为蒸馏摘要",
                    style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp),
                    color = TextTertiary,
                    modifier = Modifier.padding(bottom = 8.dp)
                )
            }

            SelectionContainer {
                Text(
                    text = memory.displayContent,
                    style = MaterialTheme.typography.bodyLarge.copy(fontSize = 16.5.sp, lineHeight = 29.sp),
                    color = TextPrimary
                )
            }

            Spacer(modifier = Modifier.height(16.dp))

            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = 14.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                HorizontalDivider(color = Line, thickness = 1.dp)
                Spacer(modifier = Modifier.height(2.dp))
                DetailMetaRow(label = "记忆时间", value = formatMemoryTimestamp(memory.createdAt))
                DetailMetaRow(label = "被想起", value = "${memory.accessCount} 次")
                if (memory.tags.isNotEmpty()) {
                    DetailMetaRow(
                        label = "标签",
                        value = memory.tags.take(6).joinToString("、")
                    )
                }
                Spacer(modifier = Modifier.height(2.dp))
                HorizontalDivider(color = Line, thickness = 1.dp)
            }

            if (relationsLoading || relations.isNotEmpty()) {
                MemoryRelationList(
                    relations = relations,
                    isLoading = relationsLoading,
                    onRelationClick = onRelationClick
                )
                Spacer(modifier = Modifier.height(16.dp))
            }

            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .height(48.dp)
                        .clip(RoundedCornerShape(14.dp))
                        .clickable(onClick = onDelete),
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        text = "删除",
                        style = MaterialTheme.typography.labelLarge.copy(fontSize = 15.sp),
                        color = Danger
                    )
                }
                Box(
                    modifier = Modifier
                        .weight(1.6f)
                        .height(48.dp)
                        .clip(RoundedCornerShape(14.dp))
                        .border(BorderStroke(1.dp, Edge), RoundedCornerShape(14.dp))
                        .clickable(onClick = onClose),
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        text = "关闭",
                        style = MaterialTheme.typography.labelLarge.copy(
                            fontSize = 15.sp,
                            fontWeight = FontWeight.Medium
                        ),
                        color = TextPrimary
                    )
                }
            }
        }
    }
}

/** 「学习 · 物理」：话题 + 记忆类型（未分类时不重复） */
private fun memoryTopicLine(memory: Memory): String {
    val type = memory.formattedType
    val unknown = memory.type == MemoryType.UNCATEGORIZED || memory.type == MemoryType.UNKNOWN
    return if (unknown || type == memory.topicLabel) memory.topicLabel else "${memory.topicLabel} · $type"
}

@Composable
private fun DetailMetaRow(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.Top
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodySmall.copy(fontSize = 13.5.sp),
            color = TextTertiary
        )
        Spacer(modifier = Modifier.size(16.dp))
        Text(
            text = value,
            style = MaterialTheme.typography.bodySmall.copy(fontSize = 13.5.sp),
            color = TextSecondary,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis
        )
    }
}

/**
 * 「想起…」：关系图上的邻居。
 *
 * 关系名由后端给出（同一轮 / 同一件事 / 接着说 / 同一话题），前端不再自己推断，
 * 避免和后端的关系判定出现两套说法。
 */
@Composable
private fun MemoryRelationList(
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
                style = MaterialTheme.typography.labelMedium.copy(fontSize = 13.sp),
                color = TextSecondary,
                fontWeight = FontWeight.SemiBold
            )
            if (relations.isNotEmpty()) {
                Text(
                    text = "${relations.size} 条",
                    style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp),
                    color = TextTertiary
                )
            }
        }
        if (isLoading) {
            Text(
                text = "正在找关联…",
                style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp),
                color = TextTertiary
            )
            return@Column
        }
        relations.forEach { relation ->
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(10.dp))
                    .background(Color.White.copy(alpha = 0.04f))
                    .clickable { onRelationClick(relation.memory) }
                    .padding(horizontal = 10.dp, vertical = 8.dp),
                verticalAlignment = Alignment.Top
            ) {
                Row(
                    modifier = Modifier
                        .clip(RoundedCornerShape(4.dp))
                        .background(Accent.copy(alpha = 0.14f))
                        .padding(horizontal = 5.dp, vertical = 2.dp)
                ) {
                    Text(
                        text = relation.relationLabel,
                        style = MaterialTheme.typography.bodySmall.copy(fontSize = 11.5.sp),
                        color = Accent,
                        maxLines = 1
                    )
                }
                Spacer(modifier = Modifier.size(8.dp))
                Text(
                    text = relation.preview.ifBlank { "（无正文）" },
                    style = MaterialTheme.typography.bodySmall.copy(fontSize = 13.sp, lineHeight = 19.sp),
                    color = TextSecondary,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f)
                )
            }
        }
    }
}
