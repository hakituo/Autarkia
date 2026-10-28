package com.aveline.ai.mobile.presentation.companion

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.domain.models.LifeStatus
import com.aveline.ai.mobile.presentation.theme.Edge
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/** 名字字号与行高（设计稿 30/38，字距 -0.4） */
private val NameSize = 30.sp
private val NameLineHeight = 38.sp

/**
 * 伴侣详情页头。
 *
 * 五个 Tab 共用同一份页头：进这页最想知道的是「她是谁、此刻在做什么、会不会回」，
 * 这三件事原来被塞在「此刻」卡片里，切到日程 / 模型 / 人设 / 记忆就看不见了。
 *
 * **高度固定**：不随 Tab 收起、不随滑动变化。曾经在记忆 Tab 收成一行给图让位置，
 * 结果是左右翻页时上半屏突然矮一大截，看起来像页面自己抖了一下——一致性比省那 44dp 重要。
 *
 * 唤醒 / 打断 / 跳过只在真的需要时出现（睡觉或专心做事），其余时候页头只有两行字。
 *
 * @param name 伴侣展示名
 * @param lifeStatus 当前生命状态，为空时按「正在放松 · 会正常回复」兜底
 * @param actionsEnabled 控制动作是否可点（执行中为 false，行尾显示转圈）
 * @param actionMessage 控制动作的结果文案
 */
@Composable
internal fun CompanionHeader(
    name: String,
    lifeStatus: LifeStatus?,
    actionsEnabled: Boolean,
    actionMessage: String?,
    onWake: () -> Unit,
    onInterrupt: () -> Unit,
    onSkip: () -> Unit
) {
    val dotColor = companionStatusColor(lifeStatus)
    val headline = companionActivityHeadline(lifeStatus)

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = CompanionGutter)
    ) {
        Text(
            text = name,
            style = MaterialTheme.typography.displaySmall.copy(
                fontSize = NameSize,
                lineHeight = NameLineHeight,
                letterSpacing = (-0.4).sp
            ),
            color = TextPrimary,
            fontWeight = FontWeight.SemiBold,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis
        )
        Spacer(modifier = Modifier.height(6.dp))

        Row(verticalAlignment = Alignment.CenterVertically) {
            StatusDot(color = dotColor, size = 7.dp)
            Spacer(modifier = Modifier.width(8.dp))
            Text(
                text = headline,
                style = MaterialTheme.typography.bodyLarge.copy(fontSize = 15.sp),
                color = TextPrimary,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
            if (!actionsEnabled) {
                Spacer(modifier = Modifier.width(8.dp))
                CircularProgressIndicator(
                    modifier = Modifier.size(13.dp),
                    color = dotColor,
                    strokeWidth = 1.5.dp
                )
            }
        }

        Text(
            text = companionStatusHint(lifeStatus),
            style = MaterialTheme.typography.bodySmall,
            color = TextTertiary,
            modifier = Modifier.padding(start = 15.dp, top = 4.dp)
        )

        if (companionNeedsActions(lifeStatus)) {
            Spacer(modifier = Modifier.height(12.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                if (companionIsSleeping(lifeStatus)) {
                    CompanionActionButton(
                        label = "唤醒",
                        enabled = actionsEnabled,
                        onClick = onWake,
                        modifier = Modifier.weight(1f)
                    )
                } else {
                    CompanionActionButton(
                        label = "打断",
                        enabled = actionsEnabled,
                        onClick = onInterrupt,
                        modifier = Modifier.weight(1f)
                    )
                    CompanionActionButton(
                        label = "跳过活动",
                        enabled = actionsEnabled,
                        onClick = onSkip,
                        modifier = Modifier.weight(1f)
                    )
                }
            }
        }

        actionMessage?.takeIf { it.isNotBlank() }?.let { message ->
            Text(
                text = message,
                style = MaterialTheme.typography.bodySmall,
                color = TextTertiary,
                modifier = Modifier.padding(top = 8.dp)
            )
        }
    }
}

@Composable
private fun StatusDot(color: Color, size: Dp) {
    Box(
        modifier = Modifier
            .size(size)
            .clip(CircleShape)
            .background(color)
    )
}

/**
 * 页头下的控制按钮：等宽描边、44dp 高。
 *
 * 不用 [Surface] 自带的 disabled 淡化，而是显式降透明度——
 * 执行中按钮要「看得见但点不动」，直接置灰会让人以为入口消失了。
 */
@Composable
private fun CompanionActionButton(
    label: String,
    enabled: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    Surface(
        onClick = onClick,
        modifier = modifier.height(44.dp),
        enabled = enabled,
        shape = RoundedCornerShape(14.dp),
        color = Color.Transparent,
        contentColor = TextPrimary.copy(alpha = if (enabled) 1f else 0.45f),
        border = BorderStroke(1.dp, Edge)
    ) {
        Box(contentAlignment = Alignment.Center) {
            Text(
                text = label,
                style = MaterialTheme.typography.labelLarge.copy(fontSize = 14.5.sp),
                fontWeight = FontWeight.Medium
            )
        }
    }
}
