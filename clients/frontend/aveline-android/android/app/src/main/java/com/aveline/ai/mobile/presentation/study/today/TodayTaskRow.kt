package com.aveline.ai.mobile.presentation.study.today

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.domain.models.PlanItem
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.Background
import com.aveline.ai.mobile.presentation.theme.Sand
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 今日任务的一行。
 *
 * 卡片改成细线分隔的行：状态交给左侧图形（空心圈 / 半圈 / 实心勾 / 虚线圈），
 * 右侧只留「时间 + 时长」，高优先才额外标沙金色；播放键是无底色的灰图标。
 */
@Composable
internal fun TodayTaskRow(
    item: PlanItem,
    onOpen: () -> Unit,
    onToggle: () -> Unit,
    onStart: () -> Unit
) {
    val done = item.isDone || item.status == "completed"
    val skipped = item.status == "skipped"
    val inProgress = isInProgress(item)
    val muted = done || skipped

    Column(modifier = Modifier.fillMaxWidth()) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(1.dp)
                .background(Color(0x0FFFFFFF))
        )
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable(onClick = onOpen)
                .padding(vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(
                modifier = Modifier
                    .offset(x = (-8).dp)
                    .size(36.dp)
                    .clip(CircleShape)
                    .clickable(enabled = !skipped, onClick = onToggle),
                contentAlignment = Alignment.Center
            ) {
                TaskStatusGlyph(done = done, inProgress = inProgress, skipped = skipped)
            }

            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(3.dp)
            ) {
                Text(
                    text = item.titleText(),
                    fontSize = 15.5f.sp,
                    lineHeight = 22.sp,
                    fontWeight = if (muted) FontWeight.Normal else FontWeight.Medium,
                    color = if (muted) TextTertiary else TextPrimary,
                    textDecoration = if (muted) TextDecoration.LineThrough else TextDecoration.None,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Text(
                        text = item.time.ifBlank { "灵活" },
                        fontSize = 12.sp,
                        fontFamily = FontFamily.Monospace,
                        color = TextTertiary
                    )
                    Text(
                        text = taskDurationText(item),
                        fontSize = 12.5f.sp,
                        color = TextTertiary
                    )
                    if (isHighPriority(item)) {
                        Text(
                            text = priorityLabel(item.priority),
                            fontSize = 12.5f.sp,
                            color = Sand
                        )
                    }
                }
            }

            if (!muted) {
                Box(
                    modifier = Modifier
                        .size(36.dp)
                        .clip(CircleShape)
                        .clickable(onClick = onStart),
                    contentAlignment = Alignment.Center
                ) {
                    Icon(
                        imageVector = Icons.Default.PlayArrow,
                        contentDescription = "开始专注",
                        tint = TextTertiary,
                        modifier = Modifier.size(22.dp)
                    )
                }
            } else {
                Box(modifier = Modifier.size(36.dp))
            }
        }
    }
}

/** 四种状态各用一个形状，不再写字。 */
@Composable
private fun TaskStatusGlyph(done: Boolean, inProgress: Boolean, skipped: Boolean) {
    when {
        done -> Box(
            modifier = Modifier
                .size(20.dp)
                .clip(CircleShape)
                .background(Accent),
            contentAlignment = Alignment.Center
        ) {
            Icon(
                imageVector = Icons.Default.Check,
                contentDescription = "已完成",
                tint = Background,
                modifier = Modifier.size(14.dp)
            )
        }

        inProgress -> Canvas(modifier = Modifier.size(20.dp)) {
            val ring = 1.5.dp.toPx()
            val arc = 4.5.dp.toPx()
            drawCircle(
                color = Accent.copy(alpha = 0.35f),
                radius = size.minDimension / 2 - ring / 2,
                style = Stroke(width = ring)
            )
            val inset = arc / 2
            drawArc(
                color = Accent,
                startAngle = -90f,
                sweepAngle = 144f,
                useCenter = false,
                topLeft = Offset(inset, inset),
                size = Size(size.width - arc, size.height - arc),
                style = Stroke(width = arc, cap = StrokeCap.Butt)
            )
        }

        skipped -> Canvas(modifier = Modifier.size(20.dp)) {
            val ring = 1.5.dp.toPx()
            drawCircle(
                color = Color(0x38FFFFFF),
                radius = size.minDimension / 2 - ring / 2,
                style = Stroke(
                    width = ring,
                    pathEffect = PathEffect.dashPathEffect(
                        floatArrayOf(3.dp.toPx(), 3.dp.toPx())
                    )
                )
            )
        }

        else -> Box(
            modifier = Modifier
                .size(20.dp)
                .clip(CircleShape)
                .border(1.5.dp, Color(0x4DFFFFFF), CircleShape)
        )
    }
}
