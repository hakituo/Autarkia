package com.aveline.ai.mobile.presentation.study.focus

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.study.FocusPhase
import com.aveline.ai.mobile.presentation.theme.AvelineTextStyles

/**
 * 专注计时圆环。
 *
 * 12dp 粗环 + 56sp 粗体 → 3dp 细环 + 64sp Light 数字：阶段名放在数字上方，
 * 下面用一排小点表示本轮走到第几个番茄，眼睛先看到时间，其余信息退到两侧。
 */
@Composable
internal fun FocusRing(
    phase: FocusPhase,
    remainingSeconds: Int,
    totalSeconds: Int,
    dotStates: List<FocusDotState>,
    modifier: Modifier = Modifier
) {
    val phaseColor = focusPhaseColor(phase)
    val target = focusRingProgress(remainingSeconds, totalSeconds)
    val animatedProgress by animateFloatAsState(
        targetValue = target,
        animationSpec = tween(durationMillis = 1000, easing = LinearEasing),
        label = "focus-ring-progress"
    )

    Box(
        modifier = modifier.size(256.dp),
        contentAlignment = Alignment.Center
    ) {
        Canvas(modifier = Modifier.fillMaxSize()) {
            val stroke = 3.dp.toPx()
            val radius = size.minDimension / 2 - stroke / 2
            drawCircle(
                color = Color(0x14FFFFFF),
                radius = radius,
                style = Stroke(width = stroke)
            )
            drawArc(
                color = phaseColor,
                startAngle = -90f,
                sweepAngle = 360f * animatedProgress,
                useCenter = false,
                topLeft = Offset(stroke / 2, stroke / 2),
                size = Size(size.width - stroke, size.height - stroke),
                style = Stroke(width = stroke, cap = StrokeCap.Round)
            )
        }

        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            Text(
                text = focusPhaseLabel(phase),
                fontSize = 14.sp,
                color = phaseColor
            )
            Text(
                text = focusClockText(remainingSeconds),
                style = AvelineTextStyles.focusClock
            )
            Row(
                modifier = Modifier.padding(top = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                dotStates.forEach { dot ->
                    Box(
                        modifier = Modifier
                            .size(6.dp)
                            .clip(CircleShape)
                            .background(focusDotColor(dot))
                    )
                }
            }
        }
    }
}
