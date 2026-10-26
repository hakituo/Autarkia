package com.aveline.ai.mobile.presentation.settings

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.BottomSheetDefaults
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
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.components.controls.AvelineButton
import com.aveline.ai.mobile.presentation.components.controls.AvelineButtonVariant
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.Danger
import com.aveline.ai.mobile.presentation.theme.Edge
import com.aveline.ai.mobile.presentation.theme.SurfaceHigh
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 地址编辑面板：一次只改一个槽位，「保存并探测」直接落盘并触发重探。
 *
 * 不再边打字边写配置，所以没有「改了但没保存」的状态；格式错误就地标红并禁用保存。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun SettingsAddressSheet(
    slot: SettingsAddressSlot,
    currentValue: String,
    onDismiss: () -> Unit,
    onSave: (String) -> Unit
) {
    var text by remember(slot, currentValue) { mutableStateOf(currentValue) }
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val invalid = isInvalidBackendUrl(text)
    val save = { if (!invalid) onSave(text.trim()) }

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState,
        containerColor = SurfaceHigh,
        contentColor = TextPrimary,
        dragHandle = { BottomSheetDefaults.DragHandle(color = Color.White.copy(alpha = 0.2f)) }
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .imePadding()
                .padding(start = 20.dp, end = 20.dp, bottom = 20.dp)
        ) {
            Text(
                text = slot.kicker,
                style = settingsMonoStyle(size = 11, color = TextTertiary)
            )
            Spacer(modifier = Modifier.height(6.dp))
            Text(
                text = slot.sheetTitle,
                fontSize = 20.sp,
                lineHeight = 26.sp,
                fontWeight = FontWeight.Medium,
                color = TextPrimary
            )
            Spacer(modifier = Modifier.height(16.dp))
            OutlinedTextField(
                value = text,
                onValueChange = { text = it },
                placeholder = {
                    Text(
                        text = slot.placeholder,
                        style = settingsMonoStyle(size = 12, color = TextTertiary)
                    )
                },
                singleLine = true,
                isError = invalid,
                textStyle = settingsMonoStyle(size = 13, color = TextPrimary),
                keyboardOptions = KeyboardOptions(
                    keyboardType = KeyboardType.Uri,
                    imeAction = ImeAction.Done
                ),
                keyboardActions = KeyboardActions(onDone = { save() }),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = Accent,
                    unfocusedBorderColor = Edge,
                    focusedContainerColor = Color.Transparent,
                    unfocusedContainerColor = Color.Transparent,
                    cursorColor = Accent,
                    focusedTextColor = TextPrimary,
                    unfocusedTextColor = TextPrimary
                ),
                modifier = Modifier.fillMaxWidth()
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = if (invalid) "地址需要以 http:// 或 https:// 开头" else slot.hint,
                fontSize = 12.sp,
                lineHeight = 18.sp,
                color = if (invalid) Danger else TextTertiary
            )
            Spacer(modifier = Modifier.height(20.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                AvelineButton(
                    text = "取消",
                    onClick = onDismiss,
                    modifier = Modifier.weight(1f),
                    variant = AvelineButtonVariant.Text
                )
                AvelineButton(
                    text = "保存并探测",
                    onClick = save,
                    modifier = Modifier.weight(1.6f),
                    variant = AvelineButtonVariant.Primary,
                    enabled = !invalid
                )
            }
        }
    }
}

/**
 * 访问令牌面板：默认按密码显示，可临时切到明文核对。
 *
 * 令牌参与探测鉴权，保存后网络页会立刻重探候选；这里只负责落盘，不展示探测过程。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun SettingsTokenSheet(
    currentToken: String,
    onDismiss: () -> Unit,
    onSave: (String) -> Unit
) {
    var text by remember(currentToken) { mutableStateOf(currentToken) }
    var visible by remember { mutableStateOf(false) }
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val save = { onSave(text.trim()) }

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState,
        containerColor = SurfaceHigh,
        contentColor = TextPrimary,
        dragHandle = { BottomSheetDefaults.DragHandle(color = Color.White.copy(alpha = 0.2f)) }
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .imePadding()
                .padding(start = 20.dp, end = 20.dp, bottom = 20.dp)
        ) {
            Text(
                text = "鉴权",
                style = settingsMonoStyle(size = 11, color = TextTertiary)
            )
            Spacer(modifier = Modifier.height(6.dp))
            Text(
                text = "访问令牌",
                fontSize = 20.sp,
                lineHeight = 26.sp,
                fontWeight = FontWeight.Medium,
                color = TextPrimary
            )
            Spacer(modifier = Modifier.height(16.dp))
            OutlinedTextField(
                value = text,
                onValueChange = { text = it },
                placeholder = {
                    Text(
                        text = "留空 = 不带令牌",
                        style = settingsMonoStyle(size = 12, color = TextTertiary)
                    )
                },
                singleLine = true,
                textStyle = settingsMonoStyle(size = 13, color = TextPrimary),
                visualTransformation = if (visible) {
                    VisualTransformation.None
                } else {
                    PasswordVisualTransformation()
                },
                trailingIcon = {
                    Text(
                        text = if (visible) "隐藏" else "显示",
                        fontSize = 12.5.sp,
                        color = TextTertiary,
                        modifier = Modifier
                            .clickable { visible = !visible }
                            .padding(horizontal = 10.dp, vertical = 8.dp)
                    )
                },
                keyboardOptions = KeyboardOptions(
                    keyboardType = KeyboardType.Password,
                    imeAction = ImeAction.Done
                ),
                keyboardActions = KeyboardActions(onDone = { save() }),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = Accent,
                    unfocusedBorderColor = Edge,
                    focusedContainerColor = Color.Transparent,
                    unfocusedContainerColor = Color.Transparent,
                    cursorColor = Accent,
                    focusedTextColor = TextPrimary,
                    unfocusedTextColor = TextPrimary
                ),
                modifier = Modifier.fillMaxWidth()
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = "令牌只保存在本机，探测和请求时随请求带上。后端未开启鉴权可以留空。",
                fontSize = 12.sp,
                lineHeight = 18.sp,
                color = TextTertiary
            )
            Spacer(modifier = Modifier.height(20.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                AvelineButton(
                    text = "取消",
                    onClick = onDismiss,
                    modifier = Modifier.weight(1f),
                    variant = AvelineButtonVariant.Text
                )
                AvelineButton(
                    text = "保存",
                    onClick = save,
                    modifier = Modifier.weight(1.6f),
                    variant = AvelineButtonVariant.Primary
                )
            }
        }
    }
}
