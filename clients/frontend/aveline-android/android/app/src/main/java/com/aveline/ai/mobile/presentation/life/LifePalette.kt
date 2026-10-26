package com.aveline.ai.mobile.presentation.life

import androidx.compose.ui.graphics.Color
import com.aveline.ai.mobile.presentation.theme.Background
import com.aveline.ai.mobile.presentation.theme.Line
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * Life 页设计稿取色（Aveline Android Life）。
 *
 * 文字与分隔线直接映射到全局暖调中性色，避免生活页出现第二套取值；
 * 只有睡眠阶段、餐食宏量这些「生活色」才使用下面的专用数据色。
 */
internal val LifeInk = TextPrimary
internal val LifeMute = TextSecondary
internal val LifeFaint = TextTertiary

/** 分组细线：与全局 Line 同值（白色 8%）。 */
internal val LifeHairline = Line

/** 进度条底色：与分组细线一致。 */
internal val LifeTrack = Line

/** 列表行细线 / 次级进度底色：白色 6%。 */
internal val LifeTrackFaint = Color(0x0FFFFFFF)

/** 睡眠分段：深睡（暗）与 REM（亮）；浅睡使用主题 LifeEnergy，清醒使用中性灰。 */
internal val LifeSleepDeep = Color(0xFF4F6C7C)
internal val LifeSleepRem = Color(0xFFB4C4CF)
internal val LifeSleepAwake = Color(0xFF3A3A3C)

/** 餐食宏量：蛋白质使用主题 LifeHunger，碳水与脂肪取设计稿的深浅沙金。 */
internal val LifeMacroLight = Color(0xFFD6BF94)
internal val LifeMacroDark = Color(0xFF8A7550)

/** AI 估算标签：沙金文字 + 40% 描边。 */
internal val LifeAiBorder = Color(0x66D6BF94)

/** 白底主按钮上的深色文字：与页面底色一致。 */
internal val LifeOnInk = Background
