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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowLeft
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.domain.models.MemoryRelation
import com.aveline.ai.mobile.presentation.theme.Background
import com.aveline.ai.mobile.presentation.theme.Edge
import com.aveline.ai.mobile.presentation.theme.SurfaceHigh
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/** 标签截断长度：8 个字 + 省略号，超出部分本来也读不到 */
internal const val LABEL_LIMIT = 8

/** 中心节点的标签可以稍长一点，它是用户最该读的那一条 */
internal const val SEED_LABEL_LIMIT = 14

/**
 * 画布上方一行：地标层是说明，邻域层是「返回 + 面包屑 + 节点数」。
 *
 * 只有 44dp：上方已经有固定的伴侣页头，这里再叠一层大标题会把画布挤没。
 */
@Composable
internal fun GraphHeader(
    isAnchorLayer: Boolean,
    anchorCount: Int,
    crumb: String,
    nodeCount: Int,
    edgeCount: Int,
    onBack: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(44.dp)
            .padding(start = 4.dp, end = 4.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        if (isAnchorLayer) {
            Text(
                text = "$anchorCount 个地标 · 球越大，那天聊得越多",
                style = MaterialTheme.typography.bodySmall.copy(fontSize = 13.sp),
                color = TextTertiary,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.padding(start = 8.dp)
            )
            return@Row
        }

        Row(
            modifier = Modifier
                .clip(RoundedCornerShape(8.dp))
                .clickable(onClick = onBack)
                .padding(horizontal = 6.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(
                imageVector = Icons.AutoMirrored.Filled.KeyboardArrowLeft,
                contentDescription = "返回地标",
                tint = TextSecondary,
                modifier = Modifier.size(20.dp)
            )
            Text(
                text = "地标",
                style = MaterialTheme.typography.bodySmall.copy(fontSize = 14.sp),
                color = TextSecondary,
                maxLines = 1
            )
        }
        Spacer(modifier = Modifier.width(8.dp))
        Text(
            text = crumb,
            style = MaterialTheme.typography.bodySmall.copy(
                fontSize = 14.sp,
                fontWeight = FontWeight.Medium
            ),
            color = TextPrimary,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f)
        )
        Spacer(modifier = Modifier.width(8.dp))
        Text(
            text = "$nodeCount 个节点 · $edgeCount 条关联",
            style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp),
            color = TextTertiary,
            maxLines = 1
        )
    }
}

/**
 * 预览卡：话题 · 关系 · 第几跳 + 正文，再给「看全文 / 以它为中心」。
 *
 * 主按钮是「以它为中心」：选中一个节点通常是因为想顺着它往旁边看，
 * 而不是想读它本身。
 */
@Composable
internal fun MemoryGraphPreviewCard(
    relation: MemoryRelation,
    onOpen: () -> Unit,
    onRecenter: () -> Unit,
    modifier: Modifier = Modifier
) {
    val meta = listOfNotNull(
        relation.memory.topicLabel,
        relation.relationLabel.ifBlank { null },
        "第 ${relation.distance} 跳"
    ).joinToString(" · ")

    Column(
        modifier = modifier
            .clip(RoundedCornerShape(26.dp))
            .background(SurfaceHigh.copy(alpha = 0.94f))
            .border(BorderStroke(1.dp, Edge), RoundedCornerShape(26.dp))
            .padding(horizontal = 18.dp, vertical = 16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                modifier = Modifier
                    .size(8.dp)
                    .clip(CircleShape)
                    .background(memoryTopicColor(relation.memory.topicKey))
            )
            Spacer(modifier = Modifier.width(8.dp))
            Text(
                text = meta,
                style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.5.sp),
                color = TextTertiary,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
        }
        Text(
            text = relation.preview.ifBlank { "（无正文）" },
            style = MaterialTheme.typography.bodyLarge.copy(fontSize = 16.sp, lineHeight = 26.sp),
            color = TextPrimary,
            maxLines = 4,
            overflow = TextOverflow.Ellipsis
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            PreviewButton(
                label = "看全文",
                filled = false,
                onClick = onOpen,
                modifier = Modifier.weight(1f)
            )
            PreviewButton(
                label = "以它为中心",
                filled = true,
                onClick = onRecenter,
                modifier = Modifier.weight(1.3f)
            )
        }
    }
}

@Composable
private fun PreviewButton(
    label: String,
    filled: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    Box(
        modifier = modifier
            .height(44.dp)
            .clip(RoundedCornerShape(14.dp))
            .background(if (filled) TextPrimary else Color.Transparent)
            .then(
                if (filled) {
                    Modifier
                } else {
                    Modifier.border(BorderStroke(1.dp, Edge), RoundedCornerShape(14.dp))
                }
            )
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.labelLarge.copy(
                fontSize = 14.5.sp,
                fontWeight = if (filled) FontWeight.SemiBold else FontWeight.Medium
            ),
            color = if (filled) Background else TextPrimary
        )
    }
}

/** 地标标签拆成两行：话题名在上，「日期 · N 条」在下 */
internal fun anchorLabel(title: String, memberCount: Int): GraphLabel {
    val parts = title.split("·").map { it.trim() }.filter { it.isNotEmpty() }
    val topic = parts.lastOrNull() ?: title
    val date = parts.firstOrNull()?.takeIf { it != topic }.orEmpty()
    val meta = listOf(date, "$memberCount 条").filter { it.isNotBlank() }.joinToString(" · ")
    return GraphLabel(text = topic, meta = meta)
}

/** 标签截断：换行压成空格，超过 [limit] 个字符补省略号 */
internal fun previewLabel(text: String, limit: Int = LABEL_LIMIT): String {
    val clean = text.replace('\n', ' ').trim()
    return if (clean.length > limit) clean.take(limit) + "…" else clean
}
