package com.aveline.ai.mobile.presentation.components

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.union
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.theme.ControlAccent
import com.aveline.ai.mobile.presentation.theme.ControlBarSurface
import com.aveline.ai.mobile.presentation.theme.ControlFaint
import com.aveline.ai.mobile.presentation.theme.ControlInk
import com.aveline.ai.mobile.presentation.theme.ControlMute
import com.aveline.ai.mobile.presentation.theme.ControlOnInk

/**
 * 聊天输入栏（控件语言来自设计稿「Aveline Android Controls」）。
 *
 * 结构：一个 26dp 圆角的中性底容器，上面是可换行的输入区，下面一排动作
 * 「+ / 麦克风 / 发送」。语音态由外部通过 [voicePanel] 原位替换掉这三行，
 * 容器本身（圆角、底色、描边、录音时的强调色呼吸描边）保持不变，
 * 所以点麦克风时输入栏是"变形"而不是"多出一条横幅"。
 *
 * @param isRecording 语音态：容器描边换成强调色呼吸圈
 * @param voicePanel 语音态内容（实时转写 + 波形 + 取消/完成），为空时显示普通输入态
 */
@Composable
fun InputArea(
    text: String,
    onTextChange: (String) -> Unit,
    onSend: () -> Unit,
    onAttach: (() -> Unit)? = null,
    onVoiceInput: (() -> Unit)? = null,
    onInputPressed: (() -> Unit)? = null,
    onInputFocused: (() -> Unit)? = null,
    // 录音期间不再禁用输入框：语音态直接把输入区换掉了，
    // 普通输入框不会在录音时抢焦点，也就不会出现"键盘突然掉下去"。
    isRecording: Boolean = false,
    hasPendingAttachment: Boolean = false,
    applyBottomInsets: Boolean = true,
    voicePanel: (@Composable () -> Unit)? = null,
    modifier: Modifier = Modifier
) {
    val interactionSource = remember { MutableInteractionSource() }
    val canSend = text.isNotBlank() || hasPendingAttachment
    val bottomInsetsModifier = if (applyBottomInsets) {
        Modifier.windowInsetsPadding(WindowInsets.ime.union(WindowInsets.navigationBars))
    } else {
        Modifier
    }

    // 录音时容器描边按 1.6s 在 35% ~ 90% 之间呼吸，别的状态用一条 9% 白描边
    val ringTransition = rememberInfiniteTransition(label = "voice_ring")
    val ringAlpha by ringTransition.animateFloat(
        initialValue = 0.35f,
        targetValue = 0.9f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 1_600, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "voice_ring_alpha"
    )
    val shape = RoundedCornerShape(26.dp)
    val outline = if (isRecording) ControlAccent.copy(alpha = ringAlpha) else Color(0x17FFFFFF)

    Surface(
        modifier = modifier
            .fillMaxWidth()
            .then(bottomInsetsModifier)
            .padding(horizontal = 12.dp, vertical = 8.dp),
        color = Color.Transparent,
        tonalElevation = 0.dp
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .clip(shape)
                .background(ControlBarSurface)
                .border(1.dp, outline, shape)
                .padding(start = 18.dp, end = 8.dp, top = 14.dp, bottom = 8.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            if (voicePanel != null) {
                voicePanel()
            } else {
                DraftInput(
                    text = text,
                    onTextChange = onTextChange,
                    onInputPressed = onInputPressed,
                    onInputFocused = onInputFocused,
                    interactionSource = interactionSource,
                    modifier = Modifier.fillMaxWidth()
                )
                ActionRow(
                    canSend = canSend,
                    onAttach = onAttach,
                    onVoiceInput = onVoiceInput,
                    onSend = onSend
                )
            }
        }
    }
}

/** 输入区：多行、无占位文案（空就是空，和传统 IM 一致）。 */
@Composable
private fun DraftInput(
    text: String,
    onTextChange: (String) -> Unit,
    onInputPressed: (() -> Unit)?,
    onInputFocused: (() -> Unit)?,
    interactionSource: MutableInteractionSource,
    modifier: Modifier = Modifier
) {
    Box(
        modifier = modifier
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
            .padding(end = 10.dp),
        contentAlignment = Alignment.CenterStart
    ) {
        BasicTextField(
            value = text,
            onValueChange = onTextChange,
            textStyle = TextStyle(color = ControlInk, fontSize = 15.5.sp, lineHeight = 24.sp),
            cursorBrush = SolidColor(ControlAccent),
            // 输入法自带的动作键不发送：回车只负责换行，发送只走右侧箭头，
            // 否则用户想换行却被发了出去。
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Default),
            interactionSource = interactionSource,
            maxLines = 4,
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = 24.dp)
                .onFocusChanged { state ->
                    if (state.isFocused) onInputFocused?.invoke()
                }
                .semantics { contentDescription = "消息输入框" }
        )
    }
}

/**
 * 动作行：「+」在左，麦克风与发送在右。
 *
 * 发送键常驻，没内容时按 38% 透明压暗（设计稿的禁用口径：只降透明度，不另画禁用态）；
 * 附件、文件入口统一收进「+」的更多面板。
 */
@Composable
private fun ActionRow(
    canSend: Boolean,
    onAttach: (() -> Unit)?,
    onVoiceInput: (() -> Unit)?,
    onSend: () -> Unit
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically
    ) {
        IconButton(
            onClick = { onAttach?.invoke() },
            enabled = onAttach != null,
            modifier = Modifier.size(40.dp)
        ) {
            Icon(
                imageVector = Icons.Filled.Add,
                contentDescription = "更多",
                tint = if (onAttach != null) ControlFaint else ControlFaint.copy(alpha = 0.38f),
                modifier = Modifier.size(22.dp)
            )
        }

        Spacer(modifier = Modifier.weight(1f))

        if (onVoiceInput != null) {
            IconButton(
                onClick = onVoiceInput,
                modifier = Modifier.size(40.dp)
            ) {
                Icon(
                    imageVector = Icons.Filled.Mic,
                    contentDescription = "语音输入",
                    tint = ControlMute,
                    modifier = Modifier.size(20.dp)
                )
            }
        }

        Spacer(modifier = Modifier.width(4.dp))

        Box(
            modifier = Modifier
                .size(36.dp)
                .alpha(if (canSend) 1f else 0.38f)
                .clip(CircleShape)
                .background(ControlInk)
                .clickable(enabled = canSend, onClick = onSend)
                .semantics { contentDescription = "发送" },
            contentAlignment = Alignment.Center
        ) {
            Icon(
                imageVector = Icons.Filled.ArrowUpward,
                contentDescription = null,
                tint = ControlOnInk,
                modifier = Modifier.size(20.dp)
            )
        }
    }
}
