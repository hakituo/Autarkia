package com.aveline.ai.mobile.presentation.components

import android.os.SystemClock
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember

/** 连点保护的默认窗口时长（毫秒）。 */
const val DEFAULT_CLICK_GATE_WINDOW_MS = 600L

/**
 * 连点闸门：同一个窗口时长内的重复触发只放行第一次。
 *
 * 用于"列表项进详情页"这类重复触发会产生重复页面/重复请求的入口。
 * 计时用 [SystemClock.elapsedRealtime]（单调时钟），不受系统时间被修改的影响。
 */
class ClickGate(private val windowMillis: Long = DEFAULT_CLICK_GATE_WINDOW_MS) {
    private var lastAcquiredAtMillis = 0L

    /** 当前这次点击是否应当放行。 */
    fun tryAcquire(): Boolean {
        val now = SystemClock.elapsedRealtime()
        if (now - lastAcquiredAtMillis < windowMillis) return false
        lastAcquiredAtMillis = now
        return true
    }
}

/**
 * 记住一个连点闸门并返回可直接调用的判定函数。
 *
 * 返回值在同一个组合生命周期内保持稳定，可以安全地放进 lambda 或事件回调。
 */
@Composable
fun rememberClickGate(windowMillis: Long = DEFAULT_CLICK_GATE_WINDOW_MS): () -> Boolean {
    val gate = remember(windowMillis) { ClickGate(windowMillis) }
    return remember(gate) { { gate.tryAcquire() } }
}
