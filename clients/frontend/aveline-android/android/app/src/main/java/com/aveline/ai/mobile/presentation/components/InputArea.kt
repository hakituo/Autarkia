package com.aveline.ai.mobile.presentation.components

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateContentSize
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxWidth
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
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material3.Icon
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.Layout
import androidx.compose.ui.layout.layoutId
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.PlatformTextStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.theme.ControlAccent
import com.aveline.ai.mobile.presentation.theme.ControlBarSurface
import com.aveline.ai.mobile.presentation.theme.ControlFaint
import com.aveline.ai.mobile.presentation.theme.ControlInk
import com.aveline.ai.mobile.presentation.theme.ControlMute
import com.aveline.ai.mobile.presentation.theme.ControlOnInk
import com.aveline.ai.mobile.presentation.theme.Line

// 关闭字体额外留白，24sp 行高才是真实的 24dp：单行 40dp = 8 + 24 + 8，
// 多行态的 14dp 顶部间距也不会被字形上下留白撑大。
private val InputTextStyle = TextStyle(
    color = ControlInk,
    fontSize = 16.sp,
    lineHeight = 24.sp,
    platformStyle = PlatformTextStyle(includeFontPadding = false)
)

/**
 * 聊天输入栏（设计稿「Aveline Android Composer · 输入栏 v2」）。
 *
 * 默认是一行 48dp：「+ | 输入区 | 麦克风 | 发送」，发送键只在有内容时出现；
 * 文字换成两行以上时整栏切成上下两层，输入区铺满宽度，动作键落到下面一行。
 * 录音态由外部通过 [voicePanel] 原位替换，容器圆角、底色和强调色呼吸描边保持不变。
 *
 * @param isRecording 语音态：容器描边换成强调色呼吸圈
 * @param voicePanel 语音态内容（取消 + 波形 + 计时 + 完成），为空时显示普通输入态
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
    // 录音期间普通输入框不会参与组合，不会在录音时抢焦点，也就不会出现"键盘突然掉下去"。
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

    // 录音时容器描边按 1.6s 在 35% ~ 90% 之间呼吸，别的状态用一条 8% 白描边
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
    val shape = RoundedCornerShape(24.dp)
    val outline = if (isRecording) ControlAccent.copy(alpha = ringAlpha) else Line

    val density = LocalDensity.current
    val textMeasurer = rememberTextMeasurer()
    var containerWidthPx by remember { mutableIntStateOf(0) }
    // 单行输入区比多行窄一圈（两侧是三个 40dp 按钮），
    // 所以"要不要换行"必须按单行宽度量，否则会在两种布局之间来回跳。
    val singleInputWidthPx = with(density) {
        val chrome = 8.dp + 40.dp + 8.dp +
            (if (onVoiceInput != null) 40.dp else 0.dp) +
            (if (canSend) 40.dp else 0.dp)
        (containerWidthPx - chrome.roundToPx()).coerceAtLeast(0)
    }
    val multiline = remember(text, singleInputWidthPx) {
        singleInputWidthPx > 0 && textMeasurer.measure(
            text = AnnotatedString(text),
            style = InputTextStyle,
            constraints = Constraints(maxWidth = singleInputWidthPx)
        ).lineCount > 1
    }

    Surface(
        modifier = modifier
            .fillMaxWidth()
            .then(bottomInsetsModifier)
            .padding(start = 12.dp, end = 12.dp, top = 6.dp, bottom = 16.dp),
        color = Color.Transparent,
        tonalElevation = 0.dp
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .onSizeChanged { containerWidthPx = it.width }
                .animateContentSize()
                .clip(shape)
                .background(ControlBarSurface)
                .border(1.dp, outline, shape)
        ) {
            when {
                voicePanel != null -> Box(modifier = Modifier.padding(4.dp)) {
                    voicePanel()
                }

                // 单行 / 多行共用同一个 ComposerLayout，输入框始终在同一个组合位置。
                // 以前两种形态是两个分支，各放一个 DraftInput：跨行时旧输入框被销毁、
                // 新输入框没有焦点，键盘就被收起来了（输入第二行、删回一行都会掉键盘）。
                else -> ComposerLayout(multiline = multiline) {
                    Box(Modifier.layoutId(SlotAttach)) { AttachButton(onAttach) }
                    Box(Modifier.layoutId(SlotInput)) {
                        DraftInput(
                            text = text,
                            onTextChange = onTextChange,
                            onInputPressed = onInputPressed,
                            onInputFocused = onInputFocused,
                            interactionSource = interactionSource,
                            multiline = multiline,
                            modifier = Modifier.fillMaxWidth()
                        )
                    }
                    Box(Modifier.layoutId(SlotMic)) { MicButton(onVoiceInput) }
                    Box(Modifier.layoutId(SlotSend)) { SendSlot(canSend = canSend, onSend = onSend) }
                }
            }
        }
    }
}

private const val SlotAttach = "attach"
private const val SlotInput = "input"
private const val SlotMic = "mic"
private const val SlotSend = "send"

/**
 * 输入栏摆放：只改位置，不改子节点结构。
 *
 * - 单行：「+ | 输入区 | 麦克风 | 发送」一行，四周 4dp。
 * - 多行：输入区铺满宽度在上（左右 6dp、顶 14dp），下一行左边「+」、右边麦克风和发送（底 6dp、间距 4dp）。
 */
@Composable
private fun ComposerLayout(
    multiline: Boolean,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit
) {
    Layout(content = content, modifier = modifier) { measurables, constraints ->
        val width = constraints.maxWidth
        fun slot(id: String) = measurables.first { it.layoutId == id }
        val loose = Constraints()
        val attach = slot(SlotAttach).measure(loose)
        val mic = slot(SlotMic).measure(loose)
        val send = slot(SlotSend).measure(loose)

        if (!multiline) {
            val pad = 4.dp.roundToPx()
            val inputWidth = (width - 2 * pad - attach.width - mic.width - send.width).coerceAtLeast(0)
            val input = slot(SlotInput).measure(Constraints.fixedWidth(inputWidth))
            val rowHeight = maxOf(attach.height, input.height, mic.height, send.height)
            layout(width, rowHeight + 2 * pad) {
                var x = pad
                for (p in listOf(attach, input, mic, send)) {
                    p.placeRelative(x, pad + (rowHeight - p.height) / 2)
                    x += p.width
                }
            }
        } else {
            val side = 6.dp.roundToPx()
            val top = 14.dp.roundToPx()
            val bottom = 6.dp.roundToPx()
            val gap = 4.dp.roundToPx()
            val input = slot(SlotInput).measure(
                Constraints.fixedWidth((width - 2 * side).coerceAtLeast(0))
            )
            val rowHeight = maxOf(attach.height, mic.height, send.height)
            val rowY = top + input.height + gap
            layout(width, rowY + rowHeight + bottom) {
                input.placeRelative(side, top)
                attach.placeRelative(side, rowY + (rowHeight - attach.height) / 2)
                val sendX = width - side - send.width
                send.placeRelative(sendX, rowY + (rowHeight - send.height) / 2)
                mic.placeRelative(sendX - mic.width, rowY + (rowHeight - mic.height) / 2)
            }
        }
    }
}

/** 输入区：16sp / 24sp 行高，多行最多 6 行，无占位文案（空就是空，和传统 IM 一致）。 */
@Composable
private fun DraftInput(
    text: String,
    onTextChange: (String) -> Unit,
    onInputPressed: (() -> Unit)?,
    onInputFocused: (() -> Unit)?,
    interactionSource: MutableInteractionSource,
    multiline: Boolean,
    modifier: Modifier = Modifier
) {
    BasicTextField(
        value = text,
        onValueChange = onTextChange,
        textStyle = InputTextStyle,
        cursorBrush = SolidColor(ControlAccent),
        // 输入法自带的动作键不发送：回车只负责换行，发送只走右侧箭头，
        // 否则用户想换行却被发了出去。
        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Default),
        interactionSource = interactionSource,
        maxLines = 6,
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
            .onFocusChanged { state ->
                if (state.isFocused) onInputFocused?.invoke()
            }
            .semantics { contentDescription = "消息输入框" }
            .padding(horizontal = if (multiline) 12.dp else 4.dp, vertical = if (multiline) 0.dp else 8.dp)
    )
}

/** 「+」：点开更多面板，附件、文件都收在里面。 */
@Composable
private fun AttachButton(onAttach: (() -> Unit)?) {
    RowAction(
        contentDescription = "更多",
        enabled = onAttach != null,
        onClick = { onAttach?.invoke() }
    ) {
        Icon(
            imageVector = Icons.Filled.Add,
            contentDescription = null,
            tint = if (onAttach != null) ControlFaint else ControlFaint.copy(alpha = 0.38f),
            modifier = Modifier.size(22.dp)
        )
    }
}

/** 麦克风：常驻；有字时也在发送键左边，识别结果接在已有文字后面。 */
@Composable
private fun MicButton(onVoiceInput: (() -> Unit)?) {
    if (onVoiceInput == null) return
    RowAction(
        contentDescription = "语音输入",
        onClick = onVoiceInput
    ) {
        Icon(
            imageVector = Icons.Filled.Mic,
            contentDescription = null,
            tint = ControlMute,
            modifier = Modifier.size(22.dp)
        )
    }
}

/**
 * 发送位：有字或有附件才出现，没字时不占位、不画禁用态。
 * 点击区 40dp，可见圆 30dp，和「+」、麦克风视觉上一样大。
 */
@Composable
private fun SendSlot(canSend: Boolean, onSend: () -> Unit) {
    AnimatedVisibility(
        visible = canSend,
        enter = fadeIn(tween(durationMillis = 120)) +
            scaleIn(tween(durationMillis = 120), initialScale = 0.6f),
        exit = fadeOut(tween(durationMillis = 120)) +
            scaleOut(tween(durationMillis = 120), targetScale = 0.6f)
    ) {
        RowAction(
            contentDescription = "发送",
            onClick = onSend
        ) {
            Box(
                modifier = Modifier
                    .size(30.dp)
                    .clip(CircleShape)
                    .background(ControlInk),
                contentAlignment = Alignment.Center
            ) {
                Icon(
                    imageVector = Icons.Filled.ArrowUpward,
                    contentDescription = null,
                    tint = ControlOnInk,
                    modifier = Modifier.size(18.dp)
                )
            }
        }
    }
}

@Composable
private fun RowAction(    contentDescription: String,
    onClick: () -> Unit,
    enabled: Boolean = true,
    content: @Composable () -> Unit
) {
    Box(
        modifier = Modifier
            .size(40.dp)
            .clip(CircleShape)
            .clickable(enabled = enabled, onClick = onClick)
            .semantics { this.contentDescription = contentDescription },
        contentAlignment = Alignment.Center
    ) {
        content()
    }
}
