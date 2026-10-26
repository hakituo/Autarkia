// statusBarColor / navigationBarColor 在 API 35 标记废弃，但透明系统栏仍要用这两个 API；
// 文件级抑制只覆盖平台废弃调用，不再用于旧色名兼容。
@file:Suppress("DEPRECATION")

package com.aveline.ai.mobile.presentation.theme

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.os.Build
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.unit.dp
import androidx.core.view.WindowCompat

/**
 * Aveline dark color scheme.
 * The app primarily uses dark theme.
 */
private val AvelineDarkColorScheme = darkColorScheme(
    primary = Accent,
    onPrimary = Background,
    primaryContainer = SurfaceHigh,
    onPrimaryContainer = TextPrimary,

    secondary = Accent,
    onSecondary = Background,
    secondaryContainer = SurfaceHigh,
    onSecondaryContainer = TextPrimary,

    tertiary = LifeHealth,
    onTertiary = Background,
    tertiaryContainer = SurfaceHigh,
    onTertiaryContainer = TextPrimary,

    background = Background,
    onBackground = TextPrimary,

    surface = Surface,
    onSurface = TextPrimary,
    surfaceVariant = SurfaceHigh,
    onSurfaceVariant = TextSecondary,

    outline = Line,
    outlineVariant = Line,

    error = Danger,
    onError = Background,
    errorContainer = SurfaceHigh,
    onErrorContainer = Danger,

    inverseSurface = SurfaceHigh,
    inverseOnSurface = TextBody,
    inversePrimary = Accent
)

/**
 * Aveline light color scheme.
 * Provided for completeness, but the app primarily uses dark theme.
 */
private val AvelineLightColorScheme = lightColorScheme(
    primary = Accent,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFD0E4FF),
    onPrimaryContainer = Color(0xFF001D36),
    
    secondary = Accent,
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFE8DEF8),
    onSecondaryContainer = Color(0xFF1D192B),
    
    tertiary = Accent,
    onTertiary = Color.White,
    tertiaryContainer = Color(0xFFD1F8E7),
    onTertiaryContainer = Color(0xFF00210F),
    
    background = Color(0xFFFDFCFF),
    onBackground = Color(0xFF1A1C1E),
    
    surface = Color(0xFFFDFCFF),
    onSurface = Color(0xFF1A1C1E),
    surfaceVariant = Color(0xFFE1E2EC),
    onSurfaceVariant = Color(0xFF43474E),
    
    outline = Color(0xFF73777F),
    outlineVariant = Color(0xFFC3C6CF),
    
    error = Danger,
    onError = Color.White,
    errorContainer = Color(0xFFFFDAD6),
    onErrorContainer = Color(0xFF410002),
    
    inverseSurface = Color(0xFF2F3033),
    inverseOnSurface = Color(0xFFF1F0F4),
    inversePrimary = Color(0xFF9ECAFF)
)

/**
 * Aveline theme composable.
 * 
 * @param darkTheme Whether to use dark theme (defaults to system setting)
 * @param dynamicColor Whether to use dynamic colors (Android 12+)
 * @param content The content to theme
 */
@Composable
fun AvelineTheme(
    darkTheme: Boolean = true, // Always use dark theme by default
    dynamicColor: Boolean = false, // Disable dynamic color to maintain brand identity
    content: @Composable () -> Unit
) {
    val colorScheme = when {
        dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> {
            val context = LocalContext.current
            if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        }
        darkTheme -> AvelineDarkColorScheme
        else -> AvelineLightColorScheme
    }
    
    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            // 只有 Activity 的窗口才有 statusBarColor / navigationBarColor 这套东西。
            // 悬浮助手把 ComposeView 挂在 Service 的系统窗口上（AssistantOverlayService），
            // 那时 LocalView 的 context 是 Service 而不是 Activity —— 硬转会抛
            // ClassCastException: AssistantOverlayService cannot be cast to android.app.Activity。
            // 更要命的是这个 SideEffect 跑在 Composition 的 applyChanges 里，而 Composition 要等
            // ComposeView attach 到窗口之后才在 Choreographer 帧里开始，调用方在 setContent 外
            // 包的 try/catch 抓不到，异常会直接升级成进程级崩溃。
            val window = view.context.findActivity()?.window ?: return@SideEffect
            window.statusBarColor = android.graphics.Color.TRANSPARENT
            window.navigationBarColor = android.graphics.Color.TRANSPARENT
            
            val windowInsetsController = WindowCompat.getInsetsController(window, view)
            windowInsetsController.isAppearanceLightStatusBars = false
            windowInsetsController.isAppearanceLightNavigationBars = false
        }
    }
    
    MaterialTheme(
        colorScheme = colorScheme,
        typography = AvelineTypography,
        content = content
    )
}

/**
 * Spacing constants for consistent layout.
 */
object Spacing {
    val xxs = 2.dp
    val xs = 4.dp
    val sm = 8.dp
    val md = 12.dp
    val lg = 16.dp
    val xl = 24.dp
    val xxl = 32.dp
    val xxxl = 48.dp
}

/**
 * Corner radius constants.
 */
object CornerRadius {
    val small = 4.dp
    val medium = 8.dp
    val large = 12.dp
    val xlarge = 16.dp
    val xxlarge = 24.dp
    val round = 999.dp
}

/**
 * Animation duration constants.
 */
object AnimationDuration {
    const val fast = 150
    const val normal = 300
    const val slow = 500
}

/**
 * Elevation constants.
 */
object Elevation {
    val none = 0.dp
    val low = 2.dp
    val medium = 4.dp
    val high = 8.dp
}

/**
 * 沿 [ContextWrapper] 链找到宿主 Activity；不在 Activity 里（如 Service 挂的 ComposeView、
 * Application、单元测试）返回 null，由调用方决定降级行为。
 *
 * 为什么需要它：Compose 的 `LocalContext` / `LocalView.context` 在 Activity 里就是 Activity
 * 本身，但在 Service 的系统窗口（悬浮助手）里是 Service —— `as Activity` 会直接抛
 * ClassCastException，而且抛在 ComposeView attach 之后的 Choreographer 帧里，
 * 调用方包在 `setContent` 外的 try/catch 抓不到。
 */
private tailrec fun Context.findActivity(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> baseContext.findActivity()
    else -> null
}
