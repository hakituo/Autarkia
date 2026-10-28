package com.aveline.ai.mobile.presentation.study.today

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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.domain.models.PlanItem
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.Background
import com.aveline.ai.mobile.presentation.theme.Line
import com.aveline.ai.mobile.presentation.theme.Sand
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary

/**
 * 「下一项」：今天页唯一的主角。
 *
 * 从 SectionCard 里搬出来直接放在页面上：一条细线分隔、一个强调色小点、
 * 22sp 标题、跟状态走的实心主按钮（进行中 = 继续专注，否则 = 开始专注）。
 */
@Composable
internal fun TodayNextTask(
    item: PlanItem?,
    onOpen: () -> Unit,
    onStart: () -> Unit
) {
    Column(modifier = Modifier.fillMaxWidth()) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(1.dp)
                .background(Line)
        )
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = 20.dp, bottom = 32.dp)
                .clickable(enabled = item != null, onClick = onOpen),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Box(
                    modifier = Modifier
                        .size(6.dp)
                        .clip(CircleShape)
                        .background(Accent)
                )
                Text(
                    text = nextTaskLabel(item),
                    fontSize = 13.sp,
                    color = Accent
                )
            }

            if (item == null) {
                Text(
                    text = "今天没有待执行任务",
                    fontSize = 15.5f.sp,
                    lineHeight = 22.sp,
                    color = TextSecondary
                )
            } else {
                NextTaskBody(item = item, onStart = onStart)
            }
        }
    }
}

/** 「下一项」的正文；直接作为外层 Column 的子项排版，不再套一层盒子。 */
@Composable
private fun NextTaskBody(item: PlanItem, onStart: () -> Unit) {
    Text(
        text = item.titleText(),
        fontSize = 22.sp,
        fontWeight = FontWeight.SemiBold,
        lineHeight = 30.sp,
        letterSpacing = (-0.2f).sp,
        color = TextPrimary,
        maxLines = 2,
        overflow = TextOverflow.Ellipsis
    )
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        Text(
            text = nextTaskDetail(item),
            fontSize = 13.sp,
            color = TextSecondary
        )
        if (isHighPriority(item)) {
            Text(
                text = priorityLabel(item.priority),
                fontSize = 13.sp,
                color = Sand
            )
        }
    }
    item.description?.takeIf { it.isNotBlank() }?.let { description ->
        Text(
            text = description,
            fontSize = 14.sp,
            lineHeight = 23.sp,
            color = TextSecondary,
            maxLines = 3,
            overflow = TextOverflow.Ellipsis
        )
    }

    Spacer(modifier = Modifier.height(2.dp))

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(48.dp)
            .clip(RoundedCornerShape(14.dp))
            .background(TextPrimary)
            .clickable(onClick = onStart),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(
            imageVector = Icons.Default.PlayArrow,
            contentDescription = null,
            tint = Background,
            modifier = Modifier.size(20.dp)
        )
        Spacer(modifier = Modifier.width(6.dp))
        Text(
            text = if (isInProgress(item)) "继续专注" else "开始专注",
            fontSize = 15.sp,
            fontWeight = FontWeight.SemiBold,
            color = Background
        )
    }
}

/** 任务标题：有科目时拼成「物理 · 电磁感应 第二节」。 */
internal fun PlanItem.titleText(): String {
    val subject = subject?.takeIf { it.isNotBlank() }
    return if (subject != null) "$subject · $content" else content
}

internal fun isInProgress(item: PlanItem): Boolean = item.status == "in_progress"

private fun nextTaskLabel(item: PlanItem?): String = when {
    item == null -> "下一项"
    isInProgress(item) -> "下一项 · 进行中"
    else -> "下一项"
}
