package com.aveline.ai.mobile.presentation.components.controls

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Remove
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.AvelineRadius
import com.aveline.ai.mobile.presentation.theme.Background
import com.aveline.ai.mobile.presentation.theme.SurfaceHigh
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 开关（设计稿「开关」一行）：关 = 细描边空心 + 灰点；开 = 强调色实心 + 深色圆点。
 *
 * 强调色的唯一用处就是这里 —— 全 App 里只有"开启"和"危险"允许出现彩色。
 */
@Composable
fun AvelineSwitch(
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true
) {
    val shape = RoundedCornerShape(16.dp)
    val background by animateColorAsState(
        targetValue = if (checked) Accent else Color.Transparent,
        animationSpec = tween(durationMillis = 160),
        label = "aveline_switch_background"
    )
    val knobColor by animateColorAsState(
        targetValue = if (checked) Background else TextTertiary,
        animationSpec = tween(durationMillis = 160),
        label = "aveline_switch_knob_color"
    )
    val knobSize by animateDpAsState(
        targetValue = if (checked) 24.dp else 16.dp,
        animationSpec = tween(durationMillis = 160),
        label = "aveline_switch_knob_size"
    )

    Box(
        modifier = modifier
            .size(width = 52.dp, height = 32.dp)
            .alpha(if (enabled) 1f else 0.38f)
            .clip(shape)
            .background(background)
            .border(
                width = 1.5.dp,
                color = if (checked) Color.Transparent else Color.White.copy(alpha = 0.22f),
                shape = shape
            )
            // toggleable 会把「开/关」语义交给无障碍服务，clickable 不会
            .toggleable(value = checked, enabled = enabled, role = Role.Switch, onValueChange = onCheckedChange)
            .padding(4.dp),
        contentAlignment = if (checked) Alignment.CenterEnd else Alignment.CenterStart
    ) {
        Box(
            modifier = Modifier
                .size(knobSize)
                .clip(CircleShape)
                .background(knobColor)
        )
    }
}

/**
 * 分段选择（设计稿「分段选择」）：替代成组的 FilterChip，2–4 个互斥选项。
 *
 * 选中项是一块比容器浅一档的实心（[SurfaceHigh]），靠明度分层，不加彩色底。
 */
@Composable
fun AvelineSegmented(
    options: List<String>,
    selectedIndex: Int,
    onSelect: (Int) -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true
) {
    val shape = RoundedCornerShape(AvelineRadius)
    Row(
        modifier = modifier
            .clip(shape)
            .border(1.dp, Color.White.copy(alpha = 0.1f), shape)
            .padding(3.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        options.forEachIndexed { index, label ->
            val selected = index == selectedIndex
            val itemBackground by animateColorAsState(
                targetValue = if (selected) SurfaceHigh else Color.Transparent,
                animationSpec = tween(durationMillis = 160),
                label = "aveline_segment_$index"
            )
            Box(
                modifier = Modifier
                    .weight(1f)
                    .height(36.dp)
                    .alpha(if (enabled) 1f else 0.38f)
                    .clip(RoundedCornerShape(AvelineRadius - 3.dp))
                    .background(itemBackground)
                    .clickable(enabled = enabled) { onSelect(index) },
                contentAlignment = Alignment.Center
            ) {
                Text(
                    text = label,
                    color = if (selected) TextPrimary else TextTertiary,
                    fontSize = 14.sp,
                    fontWeight = if (selected) FontWeight.Medium else FontWeight.Normal,
                    maxLines = 1
                )
            }
        }
    }
}

/**
 * 标签（设计稿「标签」一行）：34dp 高、17dp 圆角，多选用。
 * 选中反白 + 勾，不加彩色底。
 */
@Composable
fun AvelineChip(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true
) {
    val shape = RoundedCornerShape(17.dp)
    Row(
        modifier = modifier
            .height(34.dp)
            .alpha(if (enabled) 1f else 0.38f)
            .clip(shape)
            .background(if (selected) TextPrimary else Color.Transparent)
            .then(
                if (selected) {
                    Modifier
                } else {
                    Modifier.border(1.dp, Color.White.copy(alpha = 0.14f), shape)
                }
            )
            .clickable(enabled = enabled, onClick = onClick)
            .padding(start = if (selected) 10.dp else 14.dp, end = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        if (selected) {
            Icon(
                imageVector = Icons.Filled.Check,
                contentDescription = null,
                tint = Background,
                modifier = Modifier.size(16.dp)
            )
        }
        Text(
            text = label,
            color = if (selected) Background else TextSecondary,
            fontSize = 13.5.sp,
            fontWeight = if (selected) FontWeight.Medium else FontWeight.Normal,
            maxLines = 1
        )
    }
}

/**
 * 步进器（设计稿「步进器」）：40dp 高，减到下限时减号只降到 50% 透明，不另画禁用态。
 */
@Composable
fun AvelineStepper(
    value: Int,
    onValueChange: (Int) -> Unit,
    modifier: Modifier = Modifier,
    min: Int = 1,
    max: Int = 99,
    enabled: Boolean = true
) {
    val shape = RoundedCornerShape(AvelineRadius)
    Row(
        modifier = modifier
            .height(40.dp)
            .alpha(if (enabled) 1f else 0.38f)
            .clip(shape)
            .border(1.dp, Color.White.copy(alpha = 0.14f), shape),
        verticalAlignment = Alignment.CenterVertically
    ) {
        StepperIcon(
            icon = Icons.Filled.Remove,
            description = "减少",
            active = enabled && value > min,
            onClick = { onValueChange((value - 1).coerceAtLeast(min)) }
        )
        Box(modifier = Modifier.width(44.dp), contentAlignment = Alignment.Center) {
            Text(
                text = value.toString(),
                color = TextPrimary,
                fontSize = 15.sp,
                fontWeight = FontWeight.Medium
            )
        }
        StepperIcon(
            icon = Icons.Filled.Add,
            description = "增加",
            active = enabled && value < max,
            onClick = { onValueChange((value + 1).coerceAtMost(max)) }
        )
    }
}

@Composable
private fun StepperIcon(
    icon: ImageVector,
    description: String,
    active: Boolean,
    onClick: () -> Unit
) {
    Box(
        modifier = Modifier
            .size(width = 44.dp, height = 38.dp)
            .clickable(enabled = active, onClick = onClick)
            .semantics { contentDescription = description },
        contentAlignment = Alignment.Center
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = if (active) TextPrimary else TextTertiary.copy(alpha = 0.5f),
            modifier = Modifier.size(18.dp)
        )
    }
}
