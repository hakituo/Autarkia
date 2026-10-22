@file:Suppress("DEPRECATION")

package com.aveline.ai.mobile.presentation.components

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.union
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Send
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp

/** 输入区域组件（QQ/微信风格）。 */
@Composable
fun InputArea(
    text: String,
    onTextChange: (String) -> Unit,
    onSend: () -> Unit,
    onAttach: (() -> Unit)? = null,
    onVoiceInput: (() -> Unit)? = null,
    onInputPressed: (() -> Unit)? = null,
    onInputFocused: (() -> Unit)? = null,
    isRecording: Boolean = false,
    // 这里曾经有个 `enabled: Boolean = true` 形参，唯一调用方 ChatBottomBar 写死传 true，
    // 于是 `enabled && ...` 全是死逻辑、还让人误以为输入栏整体可以禁用。已删掉；
    // 真正需要禁用输入框的是录音态（见下面的 `!isRecording`）。
    hasPendingAttachment: Boolean = false,
    applyBottomInsets: Boolean = true,
    modifier: Modifier = Modifier
) {
    val interactionSource = remember { MutableInteractionSource() }
    val canSend = text.isNotBlank() || hasPendingAttachment
    val bottomInsetsModifier = if (applyBottomInsets) {
        Modifier.windowInsetsPadding(WindowInsets.ime.union(WindowInsets.navigationBars))
    } else {
        Modifier
    }

    Surface(
        modifier = modifier
            .fillMaxWidth()
            .then(bottomInsetsModifier)
            .padding(horizontal = 8.dp, vertical = 6.dp),
        color = Color.Transparent,
        tonalElevation = 0.dp
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 4.dp, vertical = 4.dp),
            verticalAlignment = Alignment.Bottom,
            horizontalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            if (onVoiceInput != null) {
                IconButton(
                    onClick = onVoiceInput,
                    modifier = Modifier
                        .size(40.dp)
                        .clip(CircleShape)
                        .background(if (isRecording) Color(0x1AEF4444) else Color(0x1AFFFFFF))
                ) {
                    Icon(
                        imageVector = Icons.Filled.Mic,
                        contentDescription = if (isRecording) "停止录音" else "语音输入",
                        tint = if (isRecording) Color(0xFFEF4444) else Color(0x99FFFFFF),
                        modifier = Modifier.size(22.dp)
                    )
                }
            }

            Box(
                modifier = Modifier
                    .weight(1f)
                    .heightIn(min = 40.dp, max = 120.dp)
                    .pointerInput(onInputPressed) {
                        val callback = onInputPressed ?: return@pointerInput
                        awaitEachGesture {
                            awaitFirstDown(
                                requireUnconsumed = false,
                                pass = PointerEventPass.Initial
                            )
                            callback()
                        }
                    }
                    .clip(RoundedCornerShape(20.dp))
                    .background(Color(0x1AFFFFFF))
                    .padding(horizontal = 16.dp, vertical = 10.dp),
                contentAlignment = Alignment.CenterStart
            ) {
                BasicTextField(
                    value = text,
                    onValueChange = onTextChange,
                    enabled = !isRecording,
                    textStyle = MaterialTheme.typography.bodyMedium.copy(color = Color.White),
                    cursorBrush = SolidColor(Color.White),
                    // 输入法自带的动作键不再发送：退回多行输入的默认行为，
                    // 回车 / 换行键只负责换行（配合 maxLines = 4），发送只由右侧纸飞机按钮触发。
                    // 之前是 ImeAction.Send + KeyboardActions(onSend = ...)，键盘上的"发送"键会
                    // 直接捅进 onSend()，用户想换行却被发了出去。
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Default),
                    interactionSource = interactionSource,
                    maxLines = 4,
                    // 不画占位文案（「输入消息…」/「正在输入…」）：空输入框就是空输入框，
                    // 和传统 IM 一致，也不再用输入栏暗示「她还没回」。
                    modifier = Modifier
                        .fillMaxWidth()
                        .onFocusChanged { state ->
                            if (state.isFocused) onInputFocused?.invoke()
                        }
                        .semantics { contentDescription = "消息输入框" }
                )
            }

            if (canSend || onAttach != null) {
                // 同一个按钮只有两种语义：发送 > 更多。生成期间**不再**切成红色「停止」键 ——
                // 那是等待态的残留视觉，和已经去掉的「正在输入」占位属于同一套提示。
                //
                // 生成期间允许再发一条：后端收到同一会话的新请求会 cancel 上一轮
                // （stream_orchestrator 的 prev_task），所以"边生成边发"只会有最新一轮产出。
                val actionEnabled = when {
                    // 录音中一切动作都停：结束录音有自己的入口（ChatVoiceTranscribingBar），
                    // 这里若可点，输入框里那段文字会在录音还没转完时被误发出去。
                    isRecording -> false
                    canSend -> true
                    else -> onAttach != null
                }
                val containerColor by animateColorAsState(
                    targetValue = if (canSend) Color(0x2A38BDF8) else Color(0x1AFFFFFF),
                    animationSpec = tween(durationMillis = 200),
                    label = "input_action_container"
                )
                val iconTint by animateColorAsState(
                    targetValue = if (canSend) Color(0xFFE2E8F0) else Color(0x99FFFFFF),
                    animationSpec = tween(durationMillis = 200),
                    label = "input_action_tint"
                )
                IconButton(
                    onClick = {
                        if (canSend) onSend() else onAttach?.invoke()
                    },
                    enabled = actionEnabled,
                    modifier = Modifier
                        .size(40.dp)
                        .clip(CircleShape)
                        .background(containerColor)
                        // M3 的"禁用变暗"是通过 LocalContentColor 生效的，而这里每个 Icon
                        // 都显式传了 tint，把它覆盖掉了 —— 不加这层 alpha 就会出现
                        // "亮着蓝底纸飞机、点下去没反应"的假按钮（这正是最初要查的问题）。
                        .alpha(if (actionEnabled) 1f else 0.45f)
                ) {
                    SendMoreIcon(canSend = canSend, tint = iconTint)
                }
            }
        }
    }
}

@Composable
private fun SendMoreIcon(
    canSend: Boolean,
    tint: Color,
    modifier: Modifier = Modifier
) {
    val sendProgress by animateFloatAsState(
        targetValue = if (canSend) 1f else 0f,
        animationSpec = tween(durationMillis = 220),
        label = "send_more_progress"
    )
    val plusProgress = 1f - sendProgress

    Box(
        modifier = modifier
            .size(22.dp)
            .semantics { contentDescription = if (canSend) "发送" else "更多" },
        contentAlignment = Alignment.Center
    ) {
        Icon(
            imageVector = Icons.Filled.Add,
            contentDescription = null,
            tint = tint,
            modifier = Modifier
                .size(22.dp)
                .graphicsLayer {
                    alpha = plusProgress
                    scaleX = 0.7f + 0.3f * plusProgress
                    scaleY = scaleX
                    rotationZ = 45f * sendProgress
                }
        )
        Icon(
            imageVector = Icons.Filled.Send,
            contentDescription = null,
            tint = tint,
            modifier = Modifier
                .size(20.dp)
                .graphicsLayer {
                    alpha = sendProgress
                    scaleX = 0.6f + 0.4f * sendProgress
                    scaleY = scaleX
                    rotationZ = -45f * plusProgress
                }
        )
    }
}

