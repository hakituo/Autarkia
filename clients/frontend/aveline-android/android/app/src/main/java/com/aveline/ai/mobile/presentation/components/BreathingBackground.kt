package com.aveline.ai.mobile.presentation.components

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import com.aveline.ai.mobile.presentation.theme.Background
import com.aveline.ai.mobile.presentation.theme.EmotionPalette

/**
 * 呼吸背景。
 *
 * 情绪是氛围，不是装饰：整个页面只保留右上角一团光晕，
 * 情绪切换时用 900ms 渐变换色，避免跳色。
 */
@Composable
fun BreathingBackground(
    modifier: Modifier = Modifier,
    emotion: String? = null,
    backgroundAlpha: Float = 1f
) {
    val glow by animateColorAsState(EmotionPalette.of(emotion), tween(900), label = "glow")
    val transition = rememberInfiniteTransition(label = "breath")
    val scale by transition.animateFloat(
        initialValue = 0.94f,
        targetValue = 1.06f,
        animationSpec = infiniteRepeatable(
            animation = tween(6000, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "scale"
    )

    Canvas(
        modifier = modifier
            .fillMaxSize()
            .background(Background.copy(alpha = backgroundAlpha))
    ) {
        // 只留一团：右上角，16% 不透明度
        val center = Offset(size.width * 0.85f, size.height * 0.03f)
        val radius = size.maxDimension * 0.42f * scale
        drawCircle(
            brush = Brush.radialGradient(
                colors = listOf(glow.copy(alpha = 0.16f), Color.Transparent),
                center = center,
                radius = radius
            ),
            radius = radius,
            center = center
        )
    }
}
