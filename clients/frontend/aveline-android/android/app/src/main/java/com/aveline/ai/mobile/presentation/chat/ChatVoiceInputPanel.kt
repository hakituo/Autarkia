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
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
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
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
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
 * 输入栏的语音态（设计稿「Chat · 输入栏」原位切换）。
 *
 * 点麦克风后输入栏本身变成这一态，不再另起一条横幅：
 * - 第一行是 ASR 的实时转写（说一句出一句，不等收尾解码）；
 * - 第二行是音量波形 + 录音计时；
 * - 底部「取消」丢弃本轮，「完成」把当前已识别的文本立刻落进输入框。
 *
 * 为什么「完成」不等最终结果：收尾解码还要跑一段 native 计算，
 * 等它返回会让用户对着"正在识别"干等几秒。这里先提交已经实时上屏的文本，
 * 最终结果回来后再由 [ChatVoiceInputController] 原地替换那一段。
 */
@Composable
internal fun ChatVoiceInputPanel(
    partialText: String,
    amplitude: Float,
    onCancel: () -> Unit,
    onFinish: () -> Unit,
    modifier: Modifier = Modifier
) {
    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        // 还没出字时保持设计稿的原始形态（只有波形 + 计时），
        // 一旦 ASR 吐出中间文本就立刻插到波形上方——这就是"边说边出字"
        if (partialText.isNotBlank()) {
            Text(
                text = partialText,
                color = ControlInk,
                fontSize = 15.5.sp,
                lineHeight = 24.sp,
                maxLines = 3,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 24.dp)
            )
        }

        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            VoiceWaveBars(
                amplitude = amplitude,
                modifier = Modifier
                    .weight(1f)
                    .height(24.dp)
            )
            RecordingTimer()
        }

        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            // 取消：纯文字按钮，按下给一层浅底，不占实心色
            Row(
                modifier = Modifier
                    .height(40.dp)
                    .clip(RoundedCornerShape(20.dp))
                    .clickable(onClick = onCancel)
                    .padding(horizontal = 10.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Icon(
                    imageVector = Icons.Filled.Close,
                    contentDescription = null,
                    tint = ControlMute,
                    modifier = Modifier.size(20.dp)
                )
                Spacer(modifier = Modifier.width(4.dp))
                Text(
                    text = "取消",
                    color = ControlMute,
                    fontSize = 14.sp,
                    fontWeight = FontWeight.Medium
                )
            }

            // 完成：整栏唯一的实心按钮
            Row(
                modifier = Modifier
                    .height(36.dp)
                    .clip(RoundedCornerShape(18.dp))
                    .background(ControlInk)
                    .clickable(onClick = onFinish)
                    .padding(start = 10.dp, end = 14.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Icon(
                    imageVector = Icons.Filled.Check,
                    contentDescription = null,
                    tint = ControlOnInk,
                    modifier = Modifier.size(18.dp)
                )
                Spacer(modifier = Modifier.width(6.dp))
                Text(
                    text = "完成",
                    color = ControlOnInk,
                    fontSize = 14.sp,
                    fontWeight = FontWeight.SemiBold
                )
            }
        }
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
 * 音量波形：一条相位动画驱动全部竖条，只改绘制缩放、不触发布局，
 * 每 5 根里第 3 根用强调色，和设计稿一致。
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
            val wave = abs(sin((phase + index * 0.09f) * 2f * PI)).toFloat()
            // 静音时也保留一点细起伏，说话时随音量抬到满格
            val barScale = 0.18f + (0.35f + level * 0.65f) * 0.82f * wave
            Box(
                modifier = Modifier
                    .width(3.dp)
                    .height(24.dp)
                    .graphicsLayer {
                        scaleY = barScale
                        transformOrigin = TransformOrigin(0.5f, 0.5f)
                    }
                    .clip(RoundedCornerShape(2.dp))
                    .background(
                        if (index % 5 == 2) ControlAccent else ControlInk.copy(alpha = 0.72f)
                    )
            )
        }
    }
}

private const val BAR_COUNT = 18
