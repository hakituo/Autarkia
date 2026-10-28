package com.aveline.ai.mobile.presentation.chat

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.theme.ControlAccent
import com.aveline.ai.mobile.presentation.theme.ControlInk
import com.aveline.ai.mobile.presentation.theme.ControlMute
import com.aveline.ai.mobile.presentation.theme.ControlOnInk
import kotlinx.coroutines.delay
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.sin

/**
 * 输入栏的语音态（设计稿「输入栏 v2」）。
 *
 * 输入栏原位变成一条 48dp 的录音条，高度不变：
 * 左侧关闭本轮，中间是音量波形 + 计时，右侧「完成」把已识别文本落进输入框。
 * 容器圆角、底色和强调色呼吸描边由 [com.aveline.ai.mobile.presentation.components.InputArea]
 * 统一负责，这里只画内容。
 */
@Composable
internal fun ChatVoiceInputPanel(
    amplitude: Float,
    onCancel: () -> Unit,
    onFinish: () -> Unit,
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .height(40.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp)
    ) {
        VoiceCircleAction(
            contentDescription = "取消录音",
            onClick = onCancel
        ) {
            Icon(
                imageVector = Icons.Filled.Close,
                contentDescription = null,
                tint = ControlMute,
                modifier = Modifier.size(21.dp)
            )
        }

        Row(
            modifier = Modifier.weight(1f),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            VoiceWaveBars(
                amplitude = amplitude,
                modifier = Modifier.height(20.dp)
            )
            RecordingTimer()
        }

        VoiceCircleAction(
            contentDescription = "完成录音",
            onClick = onFinish
        ) {
            Box(
                modifier = Modifier
                    .size(30.dp)
                    .clip(CircleShape)
                    .background(ControlInk),
                contentAlignment = Alignment.Center
            ) {
                Icon(
                    imageVector = Icons.Filled.Check,
                    contentDescription = null,
                    tint = ControlOnInk,
                    modifier = Modifier.size(18.dp)
                )
            }
        }
    }
}

@Composable
private fun VoiceCircleAction(
    contentDescription: String,
    onClick: () -> Unit,
    content: @Composable () -> Unit
) {
    Box(
        modifier = Modifier
            .size(40.dp)
            .clip(CircleShape)
            .clickable(onClick = onClick)
            .semantics { this.contentDescription = contentDescription },
        contentAlignment = Alignment.Center
    ) {
        content()
    }
}

/** 录音计时：0:00 起每秒 +1，离开语音态即销毁。 */
@Composable
private fun RecordingTimer() {
    var seconds by remember { mutableIntStateOf(0) }
    LaunchedEffect(Unit) {
        while (true) {
            delay(1_000)
            seconds += 1
        }
    }

    Text(
        text = "${seconds / 60}:${(seconds % 60).toString().padStart(2, '0')}",
        color = ControlInk,
        fontSize = 13.sp,
        fontFamily = FontFamily.Monospace,
        maxLines = 1
    )
}

/**
 * 音量波形：一条相位动画驱动全部竖条，只改绘制缩放、不触发布局。
 * 12 根 2.5dp 强调色竖条，说话时随音量抬得更高，静音时也保留细起伏。
 */
@Composable
private fun VoiceWaveBars(
    amplitude: Float,
    modifier: Modifier = Modifier
) {
    val transition = rememberInfiniteTransition(label = "voice_wave")
    val phase by transition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 900, easing = LinearEasing),
            repeatMode = RepeatMode.Restart
        ),
        label = "voice_wave_phase"
    )

    val level = amplitude.coerceIn(0f, 1f)

    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(3.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        repeat(BAR_COUNT) { index ->
            val wave = abs(sin((phase + index * 0.08f) * 2f * PI)).toFloat()
            val barScale = (0.25f + 0.75f * wave) * (0.55f + 0.45f * level)
            Box(
                modifier = Modifier
                    .width(2.5.dp)
                    .height(20.dp)
                    .graphicsLayer {
                        scaleY = barScale
                        transformOrigin = TransformOrigin(0.5f, 0.5f)
                    }
                    .clip(RoundedCornerShape(2.dp))
                    .background(ControlAccent)
            )
        }
    }
}

private const val BAR_COUNT = 12
