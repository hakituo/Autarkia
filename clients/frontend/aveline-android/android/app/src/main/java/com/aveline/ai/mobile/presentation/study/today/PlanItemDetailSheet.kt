package com.aveline.ai.mobile.presentation.study.today

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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.domain.models.PlanItem
import com.aveline.ai.mobile.presentation.theme.Background
import com.aveline.ai.mobile.presentation.theme.Edge
import com.aveline.ai.mobile.presentation.theme.Line
import com.aveline.ai.mobile.presentation.theme.Sand
import com.aveline.ai.mobile.presentation.theme.SurfaceHigh
import com.aveline.ai.mobile.presentation.theme.TextBody
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import kotlinx.coroutines.launch

/**
 * 任务详情：AlertDialog 的三个文字按钮改成底部面板。
 *
 * 主次动作只剩两个 —— 标记完成（描边次按钮）+ 开始专注（浅色主按钮）；
 * 调整原因与结转次数降级成两行附注，不再和按钮抢注意力。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun PlanItemDetailSheet(
    item: PlanItem,
    onDismiss: () -> Unit,
    onToggle: () -> Unit,
    onStart: () -> Unit
) {
    val done = item.isDone || item.status == "completed"
    val skipped = item.status == "skipped"
    val notes = buildList {
        item.settlementReason?.takeIf { it.isNotBlank() }?.let { add("调整原因" to it) }
        if (item.carryoverCount > 0) add("已结转" to "${item.carryoverCount} 次")
    }
    val sheetState = rememberModalBottomSheetState()
    val scope = rememberCoroutineScope()

    ModalBottomSheet(
        onDismissRequest = {
            // 先让面板自己滑下去再摘掉组合，否则下拉关闭会瞬间消失。
            scope.launch { sheetState.hide() }.invokeOnCompletion { onDismiss() }
        },
        sheetState = sheetState,
        containerColor = SurfaceHigh,
        contentColor = TextPrimary,
        dragHandle = {
            Box(
                modifier = Modifier
                    .padding(top = 12.dp, bottom = 6.dp)
                    .size(width = 36.dp, height = 4.dp)
                    .clip(RoundedCornerShape(2.dp))
                    .background(Color(0x33FFFFFF))
            )
        }
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = 20.dp, end = 20.dp, bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Text(
                text = item.subject?.takeIf { it.isNotBlank() } ?: "计划详情",
                fontSize = 13.sp,
                color = TextTertiary
            )
            Text(
                text = item.titleText(),
                fontSize = 22.sp,
                fontWeight = FontWeight.SemiBold,
                lineHeight = 30.sp,
                letterSpacing = (-0.2f).sp,
                color = TextPrimary
            )
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                Text(
                    text = item.time.ifBlank { "灵活" },
                    fontSize = 13.sp,
                    fontFamily = FontFamily.Monospace,
                    color = TextSecondary
                )
                Text(
                    text = taskDurationText(item),
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
                    fontSize = 14.5f.sp,
                    lineHeight = 25.sp,
                    color = TextBody
                )
            }

            if (notes.isNotEmpty()) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 4.dp)
                ) {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(1.dp)
                            .background(Line)
                    )
                    notes.forEach { (label, value) ->
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = 9.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text(text = label, fontSize = 13.5f.sp, color = TextTertiary)
                            Text(text = value, fontSize = 13.5f.sp, color = TextBody)
                        }
                    }
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(1.dp)
                            .background(Line)
                    )
                }
            }

            Spacer(modifier = Modifier.height(2.dp))

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                if (!skipped) {
                    Row(
                        modifier = Modifier
                            .weight(1f)
                            .height(48.dp)
                            .clip(RoundedCornerShape(14.dp))
                            .border(1.dp, Edge, RoundedCornerShape(14.dp))
                            .clickable(onClick = onToggle),
                        horizontalArrangement = Arrangement.Center,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Icon(
                            imageVector = Icons.Default.Check,
                            contentDescription = null,
                            tint = TextSecondary,
                            modifier = Modifier.size(18.dp)
                        )
                        Spacer(modifier = Modifier.width(6.dp))
                        Text(
                            text = if (done) "标记未完成" else "标记完成",
                            fontSize = 15.sp,
                            fontWeight = FontWeight.Medium,
                            color = TextPrimary
                        )
                    }
                }
                if (!done && !skipped) {
                    Row(
                        modifier = Modifier
                            .weight(1.4f)
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
                            text = "开始专注",
                            fontSize = 15.sp,
                            fontWeight = FontWeight.SemiBold,
                            color = Background
                        )
                    }
                }
            }
        }
    }
}
