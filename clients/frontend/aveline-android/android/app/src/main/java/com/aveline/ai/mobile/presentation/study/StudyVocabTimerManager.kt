package com.aveline.ai.mobile.presentation.study

import com.aveline.ai.mobile.domain.repository.StudyRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * 背单词前台计时管理器。
 *
 * 计时只在「会话进行中 && 页面处于前台」时运行：
 * - 进入背单词 / 复习（[startSession]）开始计时；
 * - 切后台、离开学习页（[pauseSession]）暂停并上报一次；
 * - 回到前台（[resumeSession]）继续累加；
 * - 一组背完（[endSession]）结算并上报最终时长。
 *
 * 上报的是**累计秒数**，服务端按 session_id 覆盖同一条每日记录，重复上报不叠加。
 * 运行期间每 [reportIntervalMillis] 上报一次，避免 App 被杀进程丢掉整段时长。
 *
 * @param onReported 上报成功回调；`final=true` 表示本次是暂停/结束时的结算上报
 */
class StudyVocabTimerManager(
    private val scope: CoroutineScope,
    private val studyRepository: StudyRepository,
    private val timer: VocabStudyTimer = VocabStudyTimer(),
    private val tickIntervalMillis: Long = 1_000L,
    private val reportIntervalMillis: Long = 30_000L,
    private val onReported: (Boolean) -> Unit = {}
) {
    private val _elapsedSeconds = MutableStateFlow(0)

    /** 当前会话累计秒数，供复习页顶部实时展示。 */
    val elapsedSeconds: StateFlow<Int> = _elapsedSeconds.asStateFlow()

    private var sessionId: String = ""
    private var mode: String = "review"
    private var sessionActive = false

    /** App / 页面是否在前台；默认 true（用户刚点进复习页时就是前台）。 */
    private var foreground = true
    private var lastReportedSeconds = 0
    private var tickJob: Job? = null
    private var pendingReport: Job? = null

    /** 当前累计秒数（快照落盘时读取）。 */
    fun currentSeconds(): Int = timer.elapsedSeconds()

    /**
     * 开始或继续一次会话。
     *
     * 同一个 sessionId 重复调用不会重置累计值（断点续背），只有换 id 才重新计时。
     */
    fun startSession(sessionId: String, mode: String, initialSeconds: Int = 0) {
        if (sessionActive && this.sessionId == sessionId) {
            resumeSession()
            return
        }
        this.sessionId = sessionId
        this.mode = mode
        sessionActive = sessionId.isNotBlank()
        lastReportedSeconds = initialSeconds.coerceAtLeast(0)
        timer.start(initialSeconds.coerceAtLeast(0).toLong() * 1000L)
        _elapsedSeconds.value = initialSeconds.coerceAtLeast(0)
        if (sessionActive && foreground) {
            timer.resume()
            startTicker()
        } else {
            timer.pause()
        }
    }

    /** 页面 / App 回到前台：继续计时。 */
    fun onForeground() {
        foreground = true
        if (!sessionActive) return
        timer.resume()
        startTicker()
    }

    /** 切到后台：立即暂停并结算上报，后台时间不计入。 */
    fun onBackground() {
        foreground = false
        pauseSession()
    }

    /** 暂停计时（离开复习页 / 切后台），并把当前累计值上报。 */
    fun pauseSession() {
        timer.pause()
        stopTicker()
        syncElapsed()
        report(final = true)
    }

    /** 回到复习页：沿用同一会话继续计时。 */
    fun resumeSession() {
        if (!sessionActive) return
        if (!foreground) return
        timer.resume()
        startTicker()
    }

    /** 一组背完：结算最终时长并重置。 */
    fun endSession() {
        timer.pause()
        stopTicker()
        syncElapsed()
        report(final = true)
        sessionActive = false
        timer.reset()
    }

    /** 退出 ViewModel 时停止计时，避免协程泄漏。 */
    fun clear() {
        stopTicker()
        timer.pause()
    }

    private fun syncElapsed() {
        _elapsedSeconds.value = timer.elapsedSeconds()
    }

    private fun startTicker() {
        if (tickJob?.isActive == true) return
        tickJob = scope.launch {
            while (isActive && timer.isRunning) {
                delay(tickIntervalMillis)
                if (!timer.isRunning) break
                syncElapsed()
                if (timer.elapsedSeconds() - lastReportedSeconds >=
                    (reportIntervalMillis / 1000L).toInt()
                ) {
                    report(final = false)
                }
            }
        }
    }

    private fun stopTicker() {
        tickJob?.cancel()
        tickJob = null
    }

    private fun report(final: Boolean) {
        val id = sessionId
        if (!sessionActive || id.isBlank()) return
        val seconds = timer.elapsedSeconds()
        if (seconds <= 0) return
        if (!final && seconds == lastReportedSeconds) return
        lastReportedSeconds = seconds

        val previous = pendingReport
        pendingReport = scope.launch {
            previous?.join()
            studyRepository.reportVocabStudyTime(
                sessionId = id,
                seconds = seconds,
                mode = mode
            ).onSuccess {
                if (final) onReported(true)
            }
        }
    }
}
