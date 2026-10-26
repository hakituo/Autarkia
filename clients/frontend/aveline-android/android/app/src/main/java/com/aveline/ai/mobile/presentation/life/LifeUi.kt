package com.aveline.ai.mobile.presentation.life

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** 分组小标题：13sp，中性 Faint。 */
internal val LifeGroupLabelStyle = TextStyle(
    fontSize = 13.sp,
    lineHeight = 18.sp,
    color = LifeFaint
)

/** 主要数值：15sp，Ink，等宽数字。 */
internal val LifeValueStyle = TextStyle(
    fontSize = 15.sp,
    lineHeight = 20.sp,
    color = LifeInk,
    fontFeatureSettings = "tnum"
)

/** 行标签：14sp，Mute。 */
internal val LifeRowLabelStyle = TextStyle(
    fontSize = 14.sp,
    lineHeight = 20.sp,
    color = LifeMute
)

/** 次级说明：13sp，Faint。 */
internal val LifeSecondaryStyle = TextStyle(
    fontSize = 13.sp,
    lineHeight = 18.sp,
    color = LifeFaint
)

/** 段落说明：12.5sp，Faint，较宽行高。 */
internal val LifeBodyStyle = TextStyle(
    fontSize = 12.5.sp,
    lineHeight = 20.sp,
    color = LifeFaint
)

/** 时间等窄字段：等宽字体。 */
internal val LifeMonoStyle = TextStyle(
    fontFamily = FontFamily.Monospace,
    fontSize = 11.5.sp,
    lineHeight = 16.sp,
    color = LifeFaint
)

/**
 * 细分隔线，替代卡片边框。
 *
 * @param color 默认分组线 [LifeHairline]；列表行用 [LifeTrackFaint]。
 */
@Composable
internal fun LifeDivider(
    modifier: Modifier = Modifier,
    color: Color = LifeHairline
) {
    Box(
        modifier = modifier
            .fillMaxWidth()
            .height(1.dp)
            .background(color)
    )
}

/**
 * 无卡片分组：顶部细线 + 小标题 + 内容。
 *
 * @param topSpacing 与上一组的间距（设计稿 28-32dp）
 * @param contentSpacing 小标题与内容之间的间距
 * @param trailing 标题行右侧内容（如睡眠得分、最近一次测量）
 */
@Composable
internal fun LifeGroup(
    title: String,
    modifier: Modifier = Modifier,
    topSpacing: Dp = 28.dp,
    contentSpacing: Dp = 14.dp,
    trailing: (@Composable RowScope.() -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(top = topSpacing)
    ) {
        LifeDivider()
        Spacer(modifier = Modifier.height(18.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(text = title, style = LifeGroupLabelStyle)
            trailing?.invoke(this)
        }
        Spacer(modifier = Modifier.height(contentSpacing))
        content()
    }
}

/**
 * 明细行：左标签右值，顶部一条 6% 白线（设计稿的细分隔列表）。
 */
@Composable
internal fun LifeRow(
    label: String,
    value: String,
    modifier: Modifier = Modifier
) {
    Column(modifier = modifier.fillMaxWidth()) {
        LifeDivider(color = LifeTrackFaint)
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 11.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(text = label, style = LifeRowLabelStyle)
            Text(text = value, style = LifeValueStyle)
        }
    }
}

/**
 * 顶部英雄数字：小标签 + 30sp 数值 + 可选单位。
 */
@Composable
internal fun LifeHeroStat(
    label: String,
    value: String,
    unit: String,
    modifier: Modifier = Modifier
) {
    Column(modifier = modifier) {
        Text(text = label, style = LifeGroupLabelStyle)
        Spacer(modifier = Modifier.height(6.dp))
        Row {
            Text(
                text = value,
                style = TextStyle(
                    fontSize = 30.sp,
                    lineHeight = 34.sp,
                    fontWeight = FontWeight.Medium,
                    letterSpacing = (-1).sp,
                    color = LifeInk,
                    fontFeatureSettings = "tnum"
                ),
                maxLines = 1,
                softWrap = false,
                modifier = Modifier.alignByBaseline()
            )
            if (unit.isNotBlank()) {
                Spacer(modifier = Modifier.width(3.dp))
                Text(
                    text = unit,
                    style = TextStyle(fontSize = 13.sp, lineHeight = 18.sp, color = LifeFaint),
                    maxLines = 1,
                    modifier = Modifier.alignByBaseline()
                )
            }
        }
    }
}

/**
 * 大号主数值（饮水总量 / 摄入热量）：52sp + 单位。
 */
@Composable
internal fun LifeBigValue(
    value: String,
    unit: String,
    modifier: Modifier = Modifier
) {
    Row(modifier = modifier, verticalAlignment = Alignment.Bottom) {
        Text(
            text = value,
            style = TextStyle(
                fontSize = 52.sp,
                lineHeight = 52.sp,
                fontWeight = FontWeight.Medium,
                letterSpacing = (-2).sp,
                color = LifeInk,
                fontFeatureSettings = "tnum"
            ),
            maxLines = 1,
            softWrap = false,
            modifier = Modifier.alignByBaseline()
        )
        if (unit.isNotBlank()) {
            Spacer(modifier = Modifier.width(6.dp))
            Text(
                text = unit,
                style = TextStyle(fontSize = 16.sp, lineHeight = 22.sp, color = LifeFaint),
                maxLines = 1,
                modifier = Modifier.alignByBaseline()
            )
        }
    }
}

/** 缺数据说明（设计稿：整组无值时收成一句「未同步：…」）。 */
@Composable
internal fun LifeMissing(
    text: String,
    modifier: Modifier = Modifier
) {
    Text(text = text, style = LifeBodyStyle, modifier = modifier)
}

/** 设备上下文小标签：32dp 高、描边胶囊。 */
@Composable
internal fun LifeChip(
    icon: ImageVector,
    text: String,
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier
            .height(32.dp)
            .border(1.dp, LifeHairline, RoundedCornerShape(16.dp))
            .padding(horizontal = 12.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = LifeFaint,
            modifier = Modifier.size(16.dp)
        )
        Spacer(modifier = Modifier.width(6.dp))
        Text(
            text = text,
            style = TextStyle(fontSize = 13.sp, lineHeight = 18.sp, color = LifeMute),
            maxLines = 1
        )
    }
}

/** 毫秒时间戳转 "HH:mm"；无值返回 null（调用方据此隐藏该行）。 */
internal fun lifeClock(epochMillis: Long?): String? {
    if (epochMillis == null) return null
    return runCatching {
        SimpleDateFormat("HH:mm", Locale.getDefault()).format(Date(epochMillis))
    }.getOrNull()
}

/** 分钟数转 "7h 32m" / "24m"；0 或负数视为无数据。 */
internal fun lifeDuration(minutes: Long?): String? {
    if (minutes == null || minutes <= 0) return null
    val hours = minutes / 60
    val rest = minutes % 60
    return if (hours > 0) "${hours}h ${rest}m" else "${rest}m"
}

/** 整数千分位，如 6,240。 */
internal fun lifeCount(value: Long): String = String.format(Locale.US, "%,d", value)

/** 浮点四舍五入后千分位，如 1,420。 */
internal fun lifeCount(value: Double): String = String.format(Locale.US, "%,.0f", value)

/** 固定小数位。 */
internal fun lifeDecimal(value: Double, decimals: Int): String =
    String.format(Locale.US, "%.${decimals}f", value)

/** 去掉多余 0 的克数，如 62.4 -> "62.4"、62.0 -> "62"。 */
internal fun lifeGram(value: Double): String {
    val rounded = String.format(Locale.US, "%.1f", value)
    return if (rounded.endsWith(".0")) rounded.dropLast(2) else rounded
}

/** 0-1 的比例转 "97.0%"。 */
internal fun lifePercent(fraction: Double): String = "${lifeDecimal(fraction * 100, 1)}%"
