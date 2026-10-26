package com.aveline.ai.mobile.presentation.theme

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

// ── 中性色：暖调近黑 + 暖白（替换 Tailwind slate） ──
val Background    = Color(0xFF0C0C0D)
val Surface       = Color(0xFF151516)
val SurfaceHigh   = Color(0xFF1C1C1E)   // 弹层、用户气泡、按下态
val TextPrimary   = Color(0xFFECEBE7)
val TextBody      = Color(0xFFCFCEC9)   // 长段落：聊天正文、文章
val TextSecondary = Color(0xFFA3A29D)
val TextTertiary  = Color(0xFF82817C)
val Line          = Color(0x14FFFFFF)   // 8% 白：分隔线
val Edge          = Color(0x29FFFFFF)   // 16% 白：描边按钮、输入框

// ── 强调与语义：与生活色同一明度带 ──
val Accent           = Color(0xFFB9D4C6)
val Danger           = Color(0xFFE3A092)
val StatusOnline     = Accent
val StatusConnecting = Color(0xFFD6BF94)
val StatusOffline    = Danger

// ── 生活面板（保留原值） ──
val LifeHealth    = Color(0xFF86A99A)
val LifeHunger    = Color(0xFFC0A36E)
val LifeHappiness = Color(0xFFB18FA2)
val LifeEnergy    = Color(0xFF809EAE)

val AvelineRadius = 14.dp

// ── 旧名兼容：先映射到新值，逐个页面替换后删除 ──
@Deprecated("用 Accent") val Primary = Accent
@Deprecated("用 Accent") val PrimaryVariant = Accent
@Deprecated("用 TextTertiary") val TextMuted = TextTertiary
@Deprecated("用 TextSecondary") val TitleText = TextSecondary
@Deprecated("用 Line") val BorderColor = Line
@Deprecated("去掉卡片底") val CardBackground = Color.Transparent
@Deprecated("用 Line") val CardBorder = Line
@Deprecated("用 AvelineRadius") val CardRadius = AvelineRadius
val SelectionSurface = Color(0x14FFFFFF)   // 保留：选中行底色
@Deprecated("用 TextPrimary") val SelectionContent = TextPrimary
@Deprecated("情绪色见 EmotionPalette") val EmotionGreen = Color(0xFF95CCBC)
@Deprecated("情绪色见 EmotionPalette") val EmotionRed = Danger
@Deprecated("用 StatusConnecting") val EmotionYellow = StatusConnecting
@Deprecated("用 SurfaceHigh") val OverlayLight = SurfaceHigh
@Deprecated("用 SurfaceHigh") val OverlayMedium = SurfaceHigh

// ── 输入栏 token：沿用上一版设计稿，取值映射到同一套中性色 ──
val ControlInk = TextPrimary
val ControlMute = TextSecondary
val ControlFaint = TextTertiary
val ControlAccent = Accent
val ControlBarSurface = Color(0xE01C1C1E)
val ControlOnInk = Background

// ── 情绪光晕色：L≈0.80 C≈0.06，只改色相 ──
object EmotionPalette {
    private val map = mapOf(
        EmotionState.NEUTRAL  to Color(0xFFA5A9B4),
        EmotionState.HAPPY    to Color(0xFFD6BF8F),
        EmotionState.SHY      to Color(0xFFDCB4BF),
        EmotionState.ANGRY    to Color(0xFFD99D94),
        EmotionState.JEALOUS  to Color(0xFFB5ABD6),
        EmotionState.WRONGED  to Color(0xFFA4B7D6),
        EmotionState.COQUETRY to Color(0xFFD6ACC4),
        EmotionState.LOST     to Color(0xFF9C9CA3),
        EmotionState.EXCITED  to Color(0xFF95CCBC),
    )

    fun of(emotion: String?): Color =
        map[EmotionState.fromString(emotion ?: "neutral")] ?: map.getValue(EmotionState.NEUTRAL)
}
