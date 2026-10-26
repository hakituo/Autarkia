package com.aveline.ai.mobile.presentation.companion.memory

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.presentation.theme.Line
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import java.time.Instant

/**
 * 聊天记录树工具栏：消息数、分支数、只看当前世界线、全部展开/收起。
 */
@Composable
internal fun ConversationTreeToolbar(
    messageCount: Int,
    branchCount: Int,
    activeOnly: Boolean,
    actionLabel: String,
    onToggleActiveOnly: () -> Unit,
    onAction: () -> Unit,
    modifier: Modifier = Modifier
) {
    Column(modifier = modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = 4.dp, end = 4.dp, top = 4.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = "聊天记录树",
                style = MaterialTheme.typography.titleSmall,
                color = TextPrimary,
                fontWeight = FontWeight.SemiBold
            )
            Spacer(modifier = Modifier.size(6.dp))
            Text(
                text = if (branchCount > 0) "$messageCount 条 · $branchCount 处分支" else "$messageCount 条",
                style = MaterialTheme.typography.labelSmall,
                color = TextTertiary
            )
            Spacer(modifier = Modifier.weight(1f))
            if (branchCount > 0 && !activeOnly) {
                TextButton(onClick = onAction) {
                    Text(
                        text = actionLabel,
                        style = MaterialTheme.typography.labelMedium,
                        color = TextSecondary
                    )
                }
            }
        }

        Row(
            modifier = Modifier.padding(start = 4.dp, bottom = 4.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            FilterChip(
                selected = activeOnly,
                onClick = onToggleActiveOnly,
                label = {
                    Text(
                        text = "只看当前世界线",
                        color = if (activeOnly) Color.White else TextSecondary
                    )
                },
                colors = FilterChipDefaults.filterChipColors(
                    selectedContainerColor = Accent.copy(alpha = 0.85f),
                    containerColor = Color(0x1A000000)
                )
            )
        }
    }
}

/**
 * 把扁平化的聊天记录树塞进 LazyColumn。
 *
 * 折叠只影响展示，不触碰本地消息库；树结构完全由 parentId 还原。
 */
internal fun LazyListScope.conversationTreeItems(
    rows: List<ConversationTreeRow>,
    onExpandBranch: (String) -> Unit
) {
    items(items = rows, key = { it.key }) { row ->
        when (row) {
            is ConversationTreeRow.MessageRow -> ConversationMessageRow(row)
            is ConversationTreeRow.BranchRow -> ConversationBranchRow(
                row = row,
                onClick = { onExpandBranch(row.parentId) }
            )
        }
    }
}

@Composable
private fun ConversationMessageRow(row: ConversationTreeRow.MessageRow) {
    val message = row.message
    val roleColor = if (message.isUser) Accent else Color(0xFFA78BFA)
    val thought = message.thought?.trim().orEmpty()
    var thoughtExpanded by rememberSaveable(message.id) { mutableStateOf(false) }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .then(
                if (row.showRail) {
                    Modifier.drawBehind {
                        drawBranchRail(depth = row.depth, isLast = row.isLastChild)
                    }
                } else {
                    Modifier
                }
            )
            .padding(start = rowIndent(row.depth), end = 4.dp, top = 3.dp, bottom = 3.dp)
    ) {
        Surface(
            modifier = Modifier
                .fillMaxWidth()
                .alpha(if (row.onActivePath) 1f else 0.45f),
            shape = RoundedCornerShape(10.dp),
            color = Color.Transparent,
            border = BorderStroke(1.dp, Line)
        ) {
            Row(
                modifier = Modifier.padding(horizontal = 10.dp, vertical = 8.dp),
                verticalAlignment = Alignment.Top
            ) {
                RoleBadge(isUser = message.isUser, color = roleColor)
                Spacer(modifier = Modifier.width(8.dp))
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = conversationMessageText(message),
                        style = MaterialTheme.typography.bodyMedium,
                        color = TextPrimary,
                        maxLines = 3,
                        overflow = TextOverflow.Ellipsis
                    )
                    Spacer(modifier = Modifier.size(3.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        if (row.fromServer) {
                            ServerBadge()
                            Spacer(modifier = Modifier.width(6.dp))
                        }
                        if (message.variantCount > 1) {
                            VariantBadge(
                                index = message.variantIndex,
                                count = message.variantCount,
                                active = row.onActivePath
                            )
                            Spacer(modifier = Modifier.width(6.dp))
                        }
                        if (thought.isNotEmpty()) {
                            ThoughtToggle(
                                expanded = thoughtExpanded,
                                onClick = { thoughtExpanded = !thoughtExpanded }
                            )
                            Spacer(modifier = Modifier.width(6.dp))
                        }
                        Text(
                            text = formatMessageTime(message.timestamp),
                            style = MaterialTheme.typography.labelSmall,
                            color = TextTertiary
                        )
                    }
                    if (thought.isNotEmpty() && thoughtExpanded) {
                        ThoughtBody(text = thought)
                    }
                }
            }
        }
    }
}

/** 「心想」按键：点一下展开对方的内心独白 */
@Composable
private fun ThoughtToggle(expanded: Boolean, onClick: () -> Unit) {
    Surface(
        color = Accent.copy(alpha = 0.14f),
        shape = RoundedCornerShape(4.dp),
        modifier = Modifier.clickable(onClick = onClick)
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 5.dp, vertical = 1.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            val chevron =
                if (expanded) Icons.Default.KeyboardArrowDown else Icons.AutoMirrored.Filled.KeyboardArrowRight
            Icon(
                imageVector = chevron,
                contentDescription = null,
                tint = Accent,
                modifier = Modifier.size(12.dp)
            )
            Text(
                text = "心想",
                style = MaterialTheme.typography.labelSmall,
                color = Accent
            )
        }
    }
}

/** 展开后的心想正文 */
@Composable
private fun ThoughtBody(text: String) {
    Surface(
        color = Accent.copy(alpha = 0.08f),
        shape = RoundedCornerShape(6.dp),
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 5.dp)
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.bodySmall,
            color = TextSecondary,
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 6.dp)
        )
    }
}

@Composable
private fun ConversationBranchRow(row: ConversationTreeRow.BranchRow, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .drawBehind { drawBranchRail(depth = row.depth, isLast = row.isLastChild) }
            .clickable(onClick = onClick)
            .padding(start = rowIndent(row.depth), end = 4.dp, top = 4.dp, bottom = 4.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(
            imageVector = Icons.AutoMirrored.Filled.KeyboardArrowRight,
            contentDescription = null,
            tint = Accent,
            modifier = Modifier.size(16.dp)
        )
        Spacer(modifier = Modifier.width(4.dp))
        Text(
            text = "其他 ${row.hiddenCount} 个版本",
            style = MaterialTheme.typography.labelMedium,
            color = Accent
        )
    }
}

@Composable
private fun RoleBadge(isUser: Boolean, color: Color) {
    Surface(
        color = color.copy(alpha = 0.16f),
        shape = RoundedCornerShape(4.dp)
    ) {
        Text(
            text = if (isUser) "你" else "AI",
            style = MaterialTheme.typography.labelSmall,
            color = color,
            modifier = Modifier.padding(horizontal = 5.dp, vertical = 1.dp)
        )
    }
}

/** 服务端历史标记：这条消息来自 Windows / 其他平台，不是本机产生的 */
@Composable
private fun ServerBadge() {
    Surface(
        color = Color(0x1AFFFFFF),
        shape = RoundedCornerShape(4.dp)
    ) {
        Text(
            text = "服务器",
            style = MaterialTheme.typography.labelSmall,
            color = TextTertiary,
            modifier = Modifier.padding(horizontal = 5.dp, vertical = 1.dp)
        )
    }
}

@Composable
private fun VariantBadge(index: Int, count: Int, active: Boolean) {
    val color = if (active) Accent else TextTertiary
    Surface(
        color = color.copy(alpha = 0.14f),
        shape = RoundedCornerShape(4.dp)
    ) {
        Text(
            text = "${index + 1}/$count",
            style = MaterialTheme.typography.labelSmall,
            color = color,
            modifier = Modifier.padding(horizontal = 5.dp, vertical = 1.dp)
        )
    }
}

/** 聊天记录树为空时的占位 */
@Composable
internal fun EmptyConversationTreeState() {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 28.dp),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = "当前会话还没有聊天记录",
            style = MaterialTheme.typography.bodyMedium,
            color = TextSecondary
        )
    }
}

/** 行缩进：主世界线 16dp，每层分支 +18dp */
private fun rowIndent(depth: Int) = 16.dp + 18.dp * depth

/**
 * 画本行的分支线。
 *
 * 树是**倒序**渲染的（最新在最上），父节点在下方，因此竖线从行中部往下接到
 * 下一行（父/兄弟），只有同级组里位于最上方的行（`isLast`）不再向上接续。
 * 主世界线不调用；分支行之间没有额外间距，竖线自然接续。
 */
private fun DrawScope.drawBranchRail(depth: Int, isLast: Boolean) {
    if (depth <= 0) return
    val step = 18.dp.toPx()
    val x = 8.dp.toPx() + (depth - 1) * step
    val midY = size.height / 2f
    val startY = if (isLast) midY else 0f
    val stroke = 1.dp.toPx()
    drawLine(
        color = MemoryTreeLineColor,
        start = Offset(x, startY),
        end = Offset(x, size.height),
        strokeWidth = stroke,
        cap = StrokeCap.Round
    )
    drawLine(
        color = MemoryTreeLineColor,
        start = Offset(x, midY),
        end = Offset(x + 8.dp.toPx(), midY),
        strokeWidth = stroke,
        cap = StrokeCap.Round
    )
}

private fun formatMessageTime(timestamp: Long): String =
    formatMemoryTimestamp(Instant.ofEpochMilli(timestamp))
