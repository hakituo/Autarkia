package com.aveline.ai.mobile.presentation.study.vocab

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.theme.Background
import com.aveline.ai.mobile.presentation.theme.Danger
import com.aveline.ai.mobile.presentation.theme.Edge
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/** 评分区：四个按钮等宽，只有【认识】是实心。 */
@Composable
internal fun GradeBar(onSubmitReview: (String) -> Unit) {
    val haptic = LocalHapticFeedback.current
    // 评分是背词里最高频的动作：给一下轻触感，确认这一下按到了
    val submit: (String) -> Unit = { quality ->
        haptic.performHapticFeedback(HapticFeedbackType.TextHandleMove)
        onSubmitReview(quality)
    }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .navigationBarsPadding()
            .padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 24.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        GradeButton(
            label = "不认识",
            sub = "本轮再背",
            style = VocabGradeStyle.Danger,
            modifier = Modifier.weight(1f),
            onClick = { submit("1") }
        )
        GradeButton(
            label = "模糊",
            sub = "明天优先",
            style = VocabGradeStyle.Normal,
            modifier = Modifier.weight(1f),
            onClick = { submit("2") }
        )
        GradeButton(
            label = "认识",
            sub = "间隔复习",
            style = VocabGradeStyle.Primary,
            modifier = Modifier.weight(1f),
            onClick = { submit("3") }
        )
        GradeButton(
            label = "太简单",
            sub = "延后复习",
            style = VocabGradeStyle.Normal,
            modifier = Modifier.weight(1f),
            onClick = { submit("4") }
        )
    }
}

private enum class VocabGradeStyle { Danger, Normal, Primary }

@Composable
private fun GradeButton(
    label: String,
    sub: String,
    style: VocabGradeStyle,
    modifier: Modifier = Modifier,
    onClick: () -> Unit
) {
    val shape = RoundedCornerShape(14.dp)
    val background = if (style == VocabGradeStyle.Primary) TextPrimary else Color.Transparent
    val labelColor = when (style) {
        VocabGradeStyle.Primary -> Background
        VocabGradeStyle.Danger -> Danger
        VocabGradeStyle.Normal -> TextPrimary
    }
    val subColor = if (style == VocabGradeStyle.Primary) {
        Background.copy(alpha = 0.6f)
    } else {
        TextTertiary
    }
    val border = when (style) {
        VocabGradeStyle.Primary -> null
        VocabGradeStyle.Danger -> Danger.copy(alpha = 0.35f)
        VocabGradeStyle.Normal -> Edge
    }

    Column(
        modifier = modifier
            .height(60.dp)
            .clip(shape)
            .background(background)
            .then(if (border != null) Modifier.border(1.dp, border, shape) else Modifier)
            .clickable(onClick = onClick),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text(
            text = label,
            fontSize = 14.5.sp,
            fontWeight = if (style == VocabGradeStyle.Primary) FontWeight.SemiBold else FontWeight.Medium,
            color = labelColor,
            maxLines = 1
        )
        Spacer(modifier = Modifier.height(2.dp))
        Text(
            text = sub,
            fontSize = 11.sp,
            color = subColor,
            maxLines = 1
        )
    }
}
