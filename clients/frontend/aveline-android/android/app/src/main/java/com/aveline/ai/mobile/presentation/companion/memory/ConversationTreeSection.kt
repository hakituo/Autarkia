package com.aveline.ai.mobile.presentation.companion.memory

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
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
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.companion.companionRowHairline
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.Background
import com.aveline.ai.mobile.presentation.theme.TextBody
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import java.time.Instant

/** 每层分支的缩进步长 */
private val RailStep = 16.dp

/**
 * 「只看当前世界线」开关。
 *
 * 原来是一个 FilterChip：选中后整块变强调色，读起来像「启用了一个滤镜」，
 * 而它其实是一个二值开关。改成带说明文字的 Switch，副标题直接写清它会隐藏什么。
 */
@Composable
internal fun ConversationWorldLineSwitch(
    messageCount: Int,
    branchCount: Int,
    activeOnly: Boolean,
    onToggleActiveOnly: () -> Unit,
    modifier: Modifier = Modifier
) {
    Column(modifier = modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = 4.dp, end = 4.dp, top = 6.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = if (branchCount > 0) "$messageCount 条 · $branchCount 处分支" else "$messageCount 条",
                style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.5.sp),
                color = TextTertiary
            )
        }
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable(onClick = onToggleActiveOnly)
                .padding(start = 4.dp, end = 4.dp, top = 8.dp, bottom = 8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = "只看当前世界线",
                    style = MaterialTheme.typography.bodyLarge.copy(fontSize = 14.5.sp),
                    color = TextPrimary
                )
                Text(
                    text = "隐藏重新生成和编辑产生的分支",
                    style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp),
                    color = TextTertiary
                )
            }
            Switch(
                checked = activeOnly,
                onCheckedChange = { onToggleActiveOnly() },
                colors = SwitchDefaults.colors(
                    checkedThumbColor = Background,
                    checkedTrackColor = TextPrimary,
                    checkedBorderColor = Color.Transparent,
                    uncheckedThumbColor = TextPrimary,
                    uncheckedTrackColor = Color.White.copy(alpha = 0.14f),
                    uncheckedBorderColor = Color.Transparent
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
    companionName: String,
    onExpandBranch: (String) -> Unit
) {
    items(items = rows, key = { it.key }) { row ->
        when (row) {
            is ConversationTreeRow.MessageRow -> ConversationMessageRow(
                row = row,
                companionName = companionName
            )
            is ConversationTreeRow.BranchRow -> ConversationBranchRow(
                row = row,
                onClick = { onExpandBranch(row.parentId) }
            )
        }
    }
}

/**
 * 一条消息：作者 + 时间 + 来源 + 正文，不再套卡片。
 *
 * 主世界线不缩进；分支靠左侧一条细线挂在父消息上，越深越往右。
 * 未采用的分支整体降到 45% 透明度并标「未采用」，来自服务端的标「来自 Windows」。
 */
@Composable
private fun ConversationMessageRow(
    row: ConversationTreeRow.MessageRow,
    companionName: String
) {
    val message = row.message
    val thought = message.thought?.trim().orEmpty()
    var thoughtExpanded by rememberSaveable(message.id) { mutableStateOf(false) }
    val who = if (message.isUser) "我" else companionName.ifBlank { "她" }
    val whoColor = if (message.isUser) TextBody else Accent
    val bodyColor = if (row.onActivePath) TextBody else TextTertiary

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .then(
                if (row.showRail) {
                    Modifier.drawBehind { drawBranchRail(depth = row.depth, isLast = row.isLastChild) }
                } else {
                    Modifier
                }
            )
            .padding(start = rowIndent(row.depth), end = 4.dp)
            .alpha(if (row.onActivePath) 1f else 0.45f)
    ) {
        Column(
            modifier = Modifier
                .weight(1f)
                .companionRowHairline()
                .padding(top = 10.dp, bottom = 10.dp),
            verticalArrangement = Arrangement.spacedBy(3.dp)
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Text(
                    text = who,
                    style = MaterialTheme.typography.bodySmall.copy(
                        fontSize = 12.sp,
                        fontWeight = FontWeight.Medium
                    ),
                    color = whoColor,
                    maxLines = 1
                )
                Text(
                    text = formatMessageTime(message.timestamp),
                    style = MaterialTheme.typography.bodySmall.copy(
                        fontFamily = FontFamily.Monospace,
                        fontSize = 11.5.sp
                    ),
                    color = TextTertiary,
                    maxLines = 1
                )
                if (row.fromServer) {
                    Text(
                        text = "来自 Windows",
                        style = MaterialTheme.typography.bodySmall.copy(fontSize = 11.5.sp),
                        color = TextTertiary,
                        maxLines = 1
                    )
                }
                if (!row.onActivePath) {
                    Text(
                        text = "未采用",
                        style = MaterialTheme.typography.bodySmall.copy(fontSize = 11.5.sp),
                        color = TextTertiary,
                        maxLines = 1
                    )
                } else if (message.variantCount > 1) {
                    Text(
                        text = "${message.variantIndex + 1}/${message.variantCount}",
                        style = MaterialTheme.typography.bodySmall.copy(fontSize = 11.5.sp),
                        color = TextTertiary,
                        maxLines = 1
                    )
                }
                if (thought.isNotEmpty()) {
                    ThoughtToggle(
                        expanded = thoughtExpanded,
                        onClick = { thoughtExpanded = !thoughtExpanded }
                    )
                }
            }
            Text(
                text = conversationMessageText(message),
                style = MaterialTheme.typography.bodyMedium.copy(fontSize = 14.5.sp, lineHeight = 22.sp),
                color = bodyColor,
                maxLines = 6,
                overflow = TextOverflow.Ellipsis
            )
            if (thought.isNotEmpty() && thoughtExpanded) {
                ThoughtBody(text = thought)
            }
        }
    }
}

/** 「心想」按键：点一下展开对方的内心独白 */
@Composable
private fun ThoughtToggle(expanded: Boolean, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .background(Accent.copy(alpha = 0.1f), RoundedCornerShape(4.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 5.dp, vertical = 1.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(
            imageVector = if (expanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
            contentDescription = null,
            tint = Accent.copy(alpha = 0.85f),
            modifier = Modifier.size(12.dp)
        )
        Text(
            text = "心想",
            style = MaterialTheme.typography.bodySmall.copy(fontSize = 11.5.sp),
            color = Accent.copy(alpha = 0.85f)
        )
    }
}

/** 展开后的心想正文 */
@Composable
private fun ThoughtBody(text: String) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 2.dp)
            .background(Accent.copy(alpha = 0.06f), RoundedCornerShape(6.dp))
            .padding(horizontal = 8.dp, vertical = 6.dp)
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.5.sp, lineHeight = 19.sp),
            color = TextSecondary
        )
    }
}

/** 分支行：灰色文字 + 展开箭头（原来是强调色的「其他 N 个版本」） */
@Composable
private fun ConversationBranchRow(row: ConversationTreeRow.BranchRow, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .drawBehind { drawBranchRail(depth = row.depth, isLast = row.isLastChild) }
            .clickable(onClick = onClick)
            .padding(start = rowIndent(row.depth), end = 4.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Row(
            modifier = Modifier
                .weight(1f)
                .companionRowHairline()
                .padding(vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = "其他 ${row.hiddenCount} 个版本",
                style = MaterialTheme.typography.bodySmall.copy(fontSize = 13.sp),
                color = TextSecondary,
                maxLines = 1
            )
            Spacer(modifier = Modifier.width(2.dp))
            Icon(
                imageVector = Icons.Default.ExpandMore,
                contentDescription = "展开",
                tint = TextTertiary,
                modifier = Modifier.size(17.dp)
            )
        }
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

/** 行缩进：主世界线 10dp，每层分支 +16dp */
private fun rowIndent(depth: Int) = 10.dp + RailStep * depth

/**
 * 画本行的分支线。
 *
 * 树是**倒序**渲染的（最新在最上），父节点在下方，因此竖线从行中部往下接到
 * 下一行（父/兄弟），只有同级组里位于最上方的行（`isLast`）不再向上接续。
 * 主世界线不调用；分支行之间没有额外间距，竖线自然接续。
 */
private fun DrawScope.drawBranchRail(depth: Int, isLast: Boolean) {
    if (depth <= 0) return
    val x = 2.dp.toPx() + (depth - 1) * RailStep.toPx()
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
    formatMemoryClock(Instant.ofEpochMilli(timestamp))
