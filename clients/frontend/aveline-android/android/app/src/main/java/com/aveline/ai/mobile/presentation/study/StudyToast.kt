package com.aveline.ai.mobile.presentation.study

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.theme.AvelineRadius
import com.aveline.ai.mobile.presentation.theme.Danger
import com.aveline.ai.mobile.presentation.theme.Edge
import com.aveline.ai.mobile.presentation.theme.MotionDuration
import com.aveline.ai.mobile.presentation.theme.MotionEasing
import com.aveline.ai.mobile.presentation.theme.SurfaceHigh
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import kotlinx.coroutines.delay

/**
 * 学习页顶部的页内轻提示：同时承接 `error` 与 `successMessage`。
 *
 * 挂在学习页根层、词汇全屏层之上，背词会话里也看得到。
 * 几秒后自动收起并清掉消息；点一下立即收起。
 */
@Composable
internal fun StudyToast(
    error: String?,
    success: String?,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier
) {
    val message = error?.takeIf { it.isNotBlank() } ?: success?.takeIf { it.isNotBlank() }
    val isError = !error.isNullOrBlank()
    // 收起动画期间消息已被清空，保留最后一条用于离场绘制
    var shown by remember { mutableStateOf("" to false) }
    if (message != null) shown = message to isError

    LaunchedEffect(message) {
        if (message == null) return@LaunchedEffect
        delay(if (isError) 3_500L else 2_400L)
        onDismiss()
    }

    AnimatedVisibility(
        visible = message != null,
        modifier = modifier
            .fillMaxWidth()
            .statusBarsPadding()
            .padding(horizontal = 16.dp, vertical = 8.dp),
        enter = slideInVertically(
            tween(MotionDuration.Medium, easing = MotionEasing.EmphasizedDecelerate)
        ) { -it } + fadeIn(tween(MotionDuration.Short)),
        exit = slideOutVertically(
            tween(MotionDuration.Short, easing = MotionEasing.EmphasizedAccelerate)
        ) { -it } + fadeOut(tween(MotionDuration.Short))
    ) {
        val shape = RoundedCornerShape(AvelineRadius)
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .clip(shape)
                .background(SurfaceHigh)
                .border(1.dp, Edge, shape)
                .clickable(
                    interactionSource = remember { MutableInteractionSource() },
                    indication = null,
                    onClick = onDismiss
                )
                .padding(horizontal = 16.dp, vertical = 13.dp),
            contentAlignment = Alignment.CenterStart
        ) {
            Text(
                text = shown.first,
                fontSize = 14.sp,
                lineHeight = 20.sp,
                color = if (shown.second) Danger else TextPrimary
            )
        }
    }
}
