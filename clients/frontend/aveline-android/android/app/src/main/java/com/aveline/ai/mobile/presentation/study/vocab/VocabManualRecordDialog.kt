package com.aveline.ai.mobile.presentation.study.vocab

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.components.controls.AvelineButton
import com.aveline.ai.mobile.presentation.components.controls.AvelineButtonVariant
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.Edge
import com.aveline.ai.mobile.presentation.theme.SurfaceHigh
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/** 手动记录 App 外背的单词数量，只收数字，避免脏输入打到后端。 */
@Composable
internal fun VocabManualRecordDialog(
    onConfirm: (Int) -> Unit,
    onDismiss: () -> Unit
) {
    var input by remember { mutableStateOf("") }
    val count = input.toIntOrNull() ?: 0
    val canConfirm = count in 1..MAX_MANUAL_STUDY_COUNT

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("手动记录") },
        text = {
            Column {
                Text(
                    text = "今天在 App 外背了多少个词？",
                    fontSize = 14.sp,
                    color = TextSecondary
                )
                Spacer(modifier = Modifier.height(12.dp))
                BasicTextField(
                    value = input,
                    onValueChange = { value ->
                        input = value.filter { it.isDigit() }.take(4)
                    },
                    singleLine = true,
                    textStyle = TextStyle(
                        fontSize = 24.sp,
                        color = TextPrimary,
                        fontFeatureSettings = "tnum"
                    ),
                    cursorBrush = SolidColor(Accent),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    decorationBox = { innerTextField ->
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(52.dp)
                                .clip(RoundedCornerShape(14.dp))
                                .background(SurfaceHigh)
                                .border(1.dp, Edge, RoundedCornerShape(14.dp))
                                .padding(horizontal = 14.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Box(modifier = Modifier.weight(1f)) {
                                if (input.isEmpty()) {
                                    Text(
                                        text = "0",
                                        fontSize = 24.sp,
                                        color = TextTertiary
                                    )
                                }
                                innerTextField()
                            }
                            Text(text = "个", fontSize = 14.sp, color = TextTertiary)
                        }
                    }
                )
            }
        },
        confirmButton = {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                AvelineButton(
                    text = "取消",
                    onClick = onDismiss,
                    variant = AvelineButtonVariant.Text
                )
                AvelineButton(
                    text = "记录",
                    onClick = { onConfirm(count) },
                    enabled = canConfirm,
                    variant = AvelineButtonVariant.Primary
                )
            }
        }
    )
}

private const val MAX_MANUAL_STUDY_COUNT = 999
