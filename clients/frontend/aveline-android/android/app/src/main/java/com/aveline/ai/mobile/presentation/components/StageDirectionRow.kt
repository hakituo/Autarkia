package com.aveline.ai.mobile.presentation.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 「撤回 / 旁白」样式的一行：居中、淡色小字、两侧渐隐横线。
 *
 * 括号里的动作描写（`（把外套披上）`）统一用这一行渲染，视觉上等同微信的
 * "xxx撤回了一条消息"——它只交代动作，不参与对话节奏，所以不做成气泡。
 *
 * 判定与取文本都在 `utils/text/ReplySegmenter`，本组件**不判断括号**，
 * 只负责画：这样"什么时候算括号内容"只有一处口径。
 */
@Composable
fun StageDirectionRow(
    text: String,
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(vertical = 8.dp),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically
    ) {
        StageDirectionDivider()
        Text(
            text = text,
            style = MaterialTheme.typography.labelSmall.copy(letterSpacing = 1.2.sp),
            color = TextTertiary,
            textAlign = TextAlign.Center,
            // weight(fill = false)：长动作描写在可用宽度内折行，而不是把两侧横线挤出屏幕
            modifier = Modifier
                .weight(1f, fill = false)
                .padding(horizontal = 12.dp)
        )
        StageDirectionDivider()
    }
}

/** 两侧的渐隐短线：从透明到半透明白再回透明，避免一条实线把消息列表割断。 */
@Composable
private fun StageDirectionDivider() {
    Box(
        modifier = Modifier
            .widthIn(min = 48.dp, max = 64.dp)
            .height(1.dp)
            .background(
                Brush.horizontalGradient(
                    colors = listOf(Color.Transparent, Color(0x33FFFFFF), Color.Transparent)
                )
            )
    )
}
