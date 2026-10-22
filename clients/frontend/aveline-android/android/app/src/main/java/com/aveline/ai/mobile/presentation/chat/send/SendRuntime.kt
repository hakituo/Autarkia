package com.aveline.ai.mobile.presentation.chat.send

import android.util.Log
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineExceptionHandler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * 发送/生成流水线的**进程级**运行状态。
 *
 * 为什么必须是进程级而不是 ChatSendController 的实例字段：生成事务不能绑定聊天页
 * ViewModel 生命周期。用户发完消息返回会话列表时 ChatViewModel 会被销毁，
 * 若 SSE collect 或最终 Room 写入还跑在 viewModelScope，页面一退出就可能主动取消请求，
 * 后端即使生成完成，本地也永远只有用户消息。
 *
 * 同理，HTTP SSE 活跃数也必须是进程级的：旧页面销毁后重新进入聊天，新的
 * ChatFlushManager 仍要知道此时应抑制 WebSocket response_chunk/done，避免双通道重复回复。
 */
internal object SendRuntime {
    private const val TAG = "SendRuntime"

    /** 拿不到会话 ID 时的占位去重键（此时发送本来就会走「记录尚未加载」分支）。 */
    const val DEFAULT_SEND_KEY = "(no-session)"

    /**
     * 后台生成协程未捕获异常的最后一道网。
     *
     * SupervisorJob 只保证"一条生成失败不取消其它并发生成"，它**不**负责兜住异常：
     * 未捕获异常会一路交到线程默认异常处理器，被 `CrashHandler` 记档后直接杀掉进程。
     * 回复生成失败应该是"这一轮报错"，不该赔上整个 App。
     */
    private val backgroundExceptionHandler = CoroutineExceptionHandler { _, e ->
        Log.e(TAG, "后台生成协程未捕获异常（已拦截，不再导致进程闪退）", e)
    }

    /** 聊天生成属于 App 进程，而不是某个 Compose 页面；进程被系统回收时自然结束。 */
    private val backgroundGenerationScope =
        CoroutineScope(SupervisorJob() + Dispatchers.IO + backgroundExceptionHandler)

    /** 后台并发生成统一使用线程安全 ID，避免竞争 ViewModel 内的普通计数器。 */
    private val backgroundMessageIdCounter = AtomicLong(0L)

    /** HTTP SSE 活跃计数（>0 时抑制 WebSocket 流式事件）。 */
    private val backgroundHttpStreamCount = AtomicLong(0L)
    private val _backgroundHttpStreamingActive = MutableStateFlow(false)
    val backgroundHttpStreamingActive: StateFlow<Boolean> =
        _backgroundHttpStreamingActive.asStateFlow()

    /**
     * 正在生成回复的后台任务，按会话 ID 索引。
     *
     * 用途有两个：同一会话起新一轮时取消上一轮；取消收尾时判断自己是否已被顶替。
     * 按会话索引而不是只存一个：用户在 A 角色发完消息、切到 B 角色再发，
     * 两个生成会同时在跑，取消只能作用于**触发它的那个会话**。
     */
    private val activeGenerationJobs = ConcurrentHashMap<String, Job>()

    fun generateMessageId(): String =
        "${System.currentTimeMillis()}-bg-${backgroundMessageIdCounter.incrementAndGet()}"

    /**
     * 记一轮 HTTP SSE 开始。
     *
     * 调用方必须用返回值同步 flushManager，**不要**自己写死 true：
     * 同一会话可能有一轮正在收尾、下一轮已经在跑，旧轮收尾时无脑 set(false)
     * 会把新轮的 WS 抑制一起放开，两个通道同时上屏就重复了。
     */
    fun markHttpStreamStarted(): Boolean {
        if (backgroundHttpStreamCount.incrementAndGet() == 1L) {
            _backgroundHttpStreamingActive.value = true
        }
        return backgroundHttpStreamingActive.value
    }

    /** @return 收尾后是否仍有 HTTP 流在跑（即 WS 是否还要继续被抑制）。 */
    fun markHttpStreamFinished(): Boolean {
        val remaining = backgroundHttpStreamCount.decrementAndGet()
        if (remaining <= 0L) {
            backgroundHttpStreamCount.set(0L)
            _backgroundHttpStreamingActive.value = false
        }
        return backgroundHttpStreamingActive.value
    }

    /**
     * 在进程级作用域里跑一轮「发送 / 重生成」，并登记到 [activeGenerationJobs]。
     *
     * 登记点放在**协程体最开头**（预检之前），而不是等 SSE 真正开始：
     * 图片/视频路径在进入发送前就把 isTyping 置成了 true，这一轮如果早早被取消，
     * 预检里的兜底收尾需要靠这张表判断「自己还是不是当前这一轮」。
     *
     * @param sessionId 这一轮归属的会话，用作表键；为 null 时只跑不登记
     * @param onCancelled 取消发生在任意阶段时的幂等收尾（由调用方实现）
     */
    fun launch(
        sessionId: String?,
        onCancelled: suspend (selfJob: Job?) -> Unit = {},
        block: suspend () -> Unit
    ) {
        backgroundGenerationScope.launch {
            val selfJob = currentCoroutineContext()[Job]
            if (sessionId != null && selfJob != null) {
                // 同一会话又起了一轮：先把上一轮停掉。
                // 后端本来就只允许每个会话一轮在跑，上一轮注定拿不到完整回复；
                // 客户端提前取消让旧 SSE 立刻断开，并以"被取代"收尾（不发完成通知）。
                // 用 put 的返回值拿旧值：替换与读取是一步原子操作，不会漏掉并发替换。
                val previous = activeGenerationJobs.put(sessionId, selfJob)
                if (previous != null && previous !== selfJob) {
                    previous.cancel(CancellationException("同一会话发起了新一轮生成"))
                }
            }
            try {
                block()
            } catch (e: CancellationException) {
                onCancelled(selfJob)
                throw e
            } finally {
                if (sessionId != null && selfJob != null) {
                    // 带 selfJob 做原子比对：并发替换成新一轮时不能把别人的表项摘掉。
                    activeGenerationJobs.remove(sessionId, selfJob)
                }
            }
        }
    }

    /** 某一轮是否仍是该会话的当前任务（取消收尾前用来避免覆盖新一轮的界面状态）。 */
    fun isCurrentJob(sessionId: String?, selfJob: Job?): Boolean {
        if (sessionId == null || selfJob == null) return true
        val registered = activeGenerationJobs[sessionId] ?: return true
        return registered === selfJob
    }
}
