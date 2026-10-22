package com.aveline.ai.mobile.presentation.study

/**
 * 背单词前台计时器（纯逻辑，不依赖 Android / Compose，可单测）。
 *
 * 只累加「计时运行中」的时间：调用方在页面可见且 App 在前台时 [resume]，
 * 切后台或离开复习页时 [pause]，因此后台时间不会被计入。
 *
 * 默认时钟用 [System.nanoTime]，单调递增，不受系统时间修改影响。
 */
class VocabStudyTimer(
    private val nowMillis: () -> Long = { System.nanoTime() / 1_000_000L }
) {
    private var accumulatedMillis: Long = 0L
    private var runningSince: Long? = null

    /** 当前是否处于计时状态。 */
    val isRunning: Boolean get() = runningSince != null

    /** 以 [initialMillis] 为起点开始计时（断点续背时传入已累计的时长）。 */
    fun start(initialMillis: Long = 0L) {
        accumulatedMillis = initialMillis.coerceAtLeast(0L)
        runningSince = nowMillis()
    }

    /** 恢复计时；已在计时则忽略，避免重复叠加。 */
    fun resume() {
        if (runningSince == null) runningSince = nowMillis()
    }

    /** 暂停计时并把这段运行时间结算进累计值。 */
    fun pause() {
        val since = runningSince ?: return
        accumulatedMillis += (nowMillis() - since).coerceAtLeast(0L)
        runningSince = null
    }

    /** 清空累计值并停止计时。 */
    fun reset() {
        accumulatedMillis = 0L
        runningSince = null
    }

    /** 截至当前的累计毫秒数（含正在运行的这一段）。 */
    fun elapsedMillis(): Long {
        val running = runningSince?.let { (nowMillis() - it).coerceAtLeast(0L) } ?: 0L
        return accumulatedMillis + running
    }

    /** 截至当前的累计秒数。 */
    fun elapsedSeconds(): Int = (elapsedMillis() / 1000L).toInt()
}
