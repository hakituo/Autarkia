package com.aveline.ai.mobile.presentation.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

// 中文字距一律 0；只有大标题用负字距收紧
private fun style(
    size: Int,
    line: Int,
    weight: FontWeight,
    spacing: Double = 0.0,
    color: androidx.compose.ui.graphics.Color = TextPrimary
) = TextStyle(
    fontFamily = FontFamily.Default,
    fontSize = size.sp,
    lineHeight = line.sp,
    fontWeight = weight,
    letterSpacing = spacing.sp,
    color = color
)

val AvelineTypography = Typography(
    displaySmall  = style(30, 38, FontWeight.SemiBold, -0.4),   // 页面标题
    headlineSmall = style(22, 30, FontWeight.SemiBold, -0.2),   // 弹层标题
    titleLarge    = style(18, 26, FontWeight.SemiBold),
    titleMedium   = style(16, 22, FontWeight.Medium),           // 列表主行
    titleSmall    = style(15, 21, FontWeight.Medium),
    bodyLarge     = style(16, 26, FontWeight.Normal, color = TextBody),      // 聊天正文
    bodyMedium    = style(14, 21, FontWeight.Normal, color = TextSecondary),
    bodySmall     = style(13, 19, FontWeight.Normal, color = TextSecondary),
    labelLarge    = style(15, 20, FontWeight.Medium),           // 按钮、Tab
    labelMedium   = style(13, 18, FontWeight.Medium, color = TextSecondary),
    labelSmall    = style(12, 16, FontWeight.Normal, 0.1, TextTertiary),     // 时间戳
)

object AvelineTextStyles {
    val message   = AvelineTypography.bodyLarge
    val timestamp = AvelineTypography.labelSmall
    val numeric   = TextStyle(
        fontSize = 34.sp,
        lineHeight = 38.sp,
        fontWeight = FontWeight.Medium,
        letterSpacing = (-1).sp,
        color = TextPrimary,
        fontFeatureSettings = "tnum"
    )
}
