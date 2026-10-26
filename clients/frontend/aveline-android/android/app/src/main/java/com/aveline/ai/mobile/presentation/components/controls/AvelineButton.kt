package com.aveline.ai.mobile.presentation.components.controls

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.theme.AvelineRadius
import com.aveline.ai.mobile.presentation.theme.Background
import com.aveline.ai.mobile.presentation.theme.Danger
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary

/**
 * 设计稿「Aveline Android Controls」的按钮族：
 * 一个组件替换 M3 的 Button / OutlinedButton / TextButton / 危险按钮。
 *
 * 规则（设计稿 01/02/03）：
 * - 一屏只有一个实心按钮：Primary 是这一屏最重要的动作，其余一律描边或纯文字；
 * - 层级不靠颜色：填充 / 描边 / 文字三档，颜色只留给「危险」与「开启」；
 * - 高度 48dp（文字按钮 44dp），圆角与输入框、弹层共用 [AvelineRadius]。
 *
 * 按下态统一是「缩到 0.98 + 变暗/浮一层浅底」，禁用态只降透明度到 38%（不另画禁用态）。
 */
enum class AvelineButtonVariant {
    /** 实心暖白底 + 深色字：这一屏唯一的主动作 */
    Primary,

    /** 1dp 描边 + 透明底 */
    Secondary,

    /** 纯文字，无底无边 */
    Text,

    /** 危险操作：描边红（[dangerFilled] 时才是实心红确认态） */
    Danger
}

@Composable
fun AvelineButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    variant: AvelineButtonVariant = AvelineButtonVariant.Secondary,
    icon: ImageVector? = null,
    enabled: Boolean = true,
    loading: Boolean = false,
    dangerFilled: Boolean = false
) {
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    val scale by animateFloatAsState(
        targetValue = if (pressed) 0.98f else 1f,
        animationSpec = tween(durationMillis = 100),
        label = "aveline_button_scale"
    )
    val shape = RoundedCornerShape(AvelineRadius)

    // 危险确认态是整屏唯一该实心的红色（e.g. 确认清空），其余危险操作只描边
    val filledDanger = variant == AvelineButtonVariant.Danger && dangerFilled

    val background = when {
        variant == AvelineButtonVariant.Primary -> TextPrimary.copy(alpha = if (pressed) 0.86f else 1f)
        filledDanger -> Danger
        pressed -> Color.White.copy(alpha = 0.06f)
        else -> Color.Transparent
    }
    val content = when (variant) {
        AvelineButtonVariant.Primary -> Background
        AvelineButtonVariant.Danger -> if (filledDanger) Color(0xFF1A0F0C) else Danger
        AvelineButtonVariant.Text -> if (pressed) TextPrimary else TextSecondary
        AvelineButtonVariant.Secondary -> TextPrimary
    }
    val stroke = when {
        variant == AvelineButtonVariant.Secondary ->
            Color.White.copy(alpha = if (pressed) 0.26f else 0.16f)
        variant == AvelineButtonVariant.Danger && !filledDanger ->
            Danger.copy(alpha = if (pressed) 0.6f else 0.4f)
        else -> null
    }

    Row(
        modifier = modifier
            .height(if (variant == AvelineButtonVariant.Text) 44.dp else 48.dp)
            .scale(scale)
            .alpha(if (enabled) 1f else 0.38f)
            .clip(shape)
            .background(background)
            .then(if (stroke != null) Modifier.border(1.dp, stroke, shape) else Modifier)
            .clickable(
                interactionSource = interaction,
                indication = null,
                enabled = enabled && !loading,
                onClick = onClick
            )
            .padding(horizontal = 20.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterHorizontally),
        verticalAlignment = Alignment.CenterVertically
    ) {
        when {
            loading -> CircularProgressIndicator(
                modifier = Modifier.size(14.dp),
                color = content,
                strokeWidth = 2.dp
            )
            icon != null -> Icon(
                imageVector = icon,
                contentDescription = null,
                tint = content.copy(alpha = 0.7f),
                modifier = Modifier.size(18.dp)
            )
        }
        Text(
            text = text,
            color = content,
            fontSize = 15.sp,
            fontWeight = if (variant == AvelineButtonVariant.Primary || filledDanger) {
                FontWeight.SemiBold
            } else {
                FontWeight.Medium
            },
            maxLines = 1,
            overflow = TextOverflow.Ellipsis
        )
    }
}

/**
 * 图标按钮四态（设计稿「图标按钮」一行）。
 *
 * - [AvelineIconVariant.Ghost]：常态，透明底
 * - [AvelineIconVariant.Pressed]：按下 / 选中，8% 白圆底
 * - [AvelineIconVariant.Outlined]：1dp 描边空心（输入栏麦克风那种）
 * - [AvelineIconVariant.Filled]：实心暖白圆底 + 深色图标（发送）
 */
enum class AvelineIconVariant { Ghost, Pressed, Outlined, Filled }

@Composable
fun AvelineIconButton(
    icon: ImageVector,
    contentDescription: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    variant: AvelineIconVariant = AvelineIconVariant.Ghost,
    size: Dp = 44.dp,
    iconSize: Dp = 20.dp,
    enabled: Boolean = true
) {
    val background = when (variant) {
        AvelineIconVariant.Pressed -> Color.White.copy(alpha = 0.08f)
        AvelineIconVariant.Filled -> TextPrimary
        AvelineIconVariant.Ghost, AvelineIconVariant.Outlined -> Color.Transparent
    }
    val tint = when (variant) {
        AvelineIconVariant.Filled -> Background
        AvelineIconVariant.Pressed -> TextPrimary
        AvelineIconVariant.Ghost, AvelineIconVariant.Outlined -> TextSecondary
    }

    Box(
        modifier = modifier
            .size(size)
            .alpha(if (enabled) 1f else 0.38f)
            .clip(CircleShape)
            .background(background)
            .then(
                if (variant == AvelineIconVariant.Outlined) {
                    Modifier.border(1.dp, Color.White.copy(alpha = 0.16f), CircleShape)
                } else {
                    Modifier
                }
            )
            .clickable(enabled = enabled, onClick = onClick)
            .semantics { this.contentDescription = contentDescription },
        contentAlignment = Alignment.Center
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = tint,
            modifier = Modifier.size(iconSize)
        )
    }
}
