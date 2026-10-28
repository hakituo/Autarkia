package com.aveline.ai.mobile.presentation.study

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.components.controls.AvelineButton
import com.aveline.ai.mobile.presentation.components.controls.AvelineButtonVariant
import com.aveline.ai.mobile.presentation.theme.Edge
import com.aveline.ai.mobile.presentation.theme.Line
import com.aveline.ai.mobile.presentation.theme.SurfaceHigh
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import kotlinx.coroutines.launch

/**
 * 手动记录面板。
 *
 * 学习记录页把三个输入框收进底部按钮，点开才是这张面板：
 * 科目 / 时长 / 笔记写在同一个 `StudyUiState` 里，保存、开始会话、结束会话仍走原回调。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun StudyRecordSheet(
    topic: String,
    content: String,
    duration: Int,
    onTopicChange: (String) -> Unit,
    onContentChange: (String) -> Unit,
    onDurationChange: (Int) -> Unit,
    onSave: () -> Unit,
    onStart: () -> Unit,
    onFinish: () -> Unit,
    onDismiss: () -> Unit
) {
    val sheetState = rememberModalBottomSheetState()
    val scope = rememberCoroutineScope()
    val canSave = topic.isNotBlank() && content.isNotBlank()
    // 时长输入单独持有一份文本：直接绑定 Int 时，清空输入框会被 state 立刻回填成旧数字。
    var durationText by remember(duration) { mutableStateOf(duration.toString()) }
    val fieldColors = OutlinedTextFieldDefaults.colors(
        focusedTextColor = TextPrimary,
        unfocusedTextColor = TextPrimary,
        focusedBorderColor = Edge,
        unfocusedBorderColor = Line,
        focusedLabelColor = TextTertiary,
        unfocusedLabelColor = TextTertiary,
        cursorColor = TextPrimary
    )

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
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Text(
                text = "手动记录",
                fontSize = 22.sp,
                fontWeight = FontWeight.SemiBold,
                color = TextPrimary
            )
            Text(
                text = "补一条今天的学习记录，或直接开始 / 结束一次会话。",
                fontSize = 13.sp,
                lineHeight = 19.sp,
                color = TextTertiary
            )

            OutlinedTextField(
                value = topic,
                onValueChange = onTopicChange,
                label = { Text("科目") },
                singleLine = true,
                colors = fieldColors,
                modifier = Modifier.fillMaxWidth()
            )
            OutlinedTextField(
                value = durationText,
                onValueChange = { text ->
                    if (text.all { it.isDigit() }) {
                        durationText = text
                        text.toIntOrNull()?.let(onDurationChange)
                    }
                },
                label = { Text("时长（分钟）") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                colors = fieldColors,
                modifier = Modifier.fillMaxWidth()
            )
            OutlinedTextField(
                value = content,
                onValueChange = onContentChange,
                label = { Text("笔记") },
                minLines = 3,
                colors = fieldColors,
                modifier = Modifier.fillMaxWidth()
            )

            AvelineButton(
                text = "保存记录",
                onClick = onSave,
                variant = AvelineButtonVariant.Primary,
                enabled = canSave,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 4.dp)
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                AvelineButton(
                    text = "开始会话",
                    onClick = onStart,
                    variant = AvelineButtonVariant.Secondary,
                    enabled = topic.isNotBlank(),
                    modifier = Modifier.weight(1f)
                )
                AvelineButton(
                    text = "结束",
                    onClick = onFinish,
                    variant = AvelineButtonVariant.Text,
                    modifier = Modifier.weight(1f)
                )
            }
            Text(
                text = "保存只写入记录；开始会话会同时进入低打扰学习模式。",
                fontSize = 12.sp,
                lineHeight = 17.sp,
                color = TextSecondary
            )
        }
    }
}
