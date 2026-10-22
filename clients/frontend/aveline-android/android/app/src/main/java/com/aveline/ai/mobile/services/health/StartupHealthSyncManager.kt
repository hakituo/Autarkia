package com.aveline.ai.mobile.services.health

import android.util.Log
import com.aveline.ai.mobile.data.samsung.SamsungHealthReader
import com.aveline.ai.mobile.data.samsung.toSyncJson
import com.aveline.ai.mobile.domain.repository.HealthRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import javax.inject.Inject
import javax.inject.Singleton

/**
 * App 启动时的三星健康静默同步。
 *
 * 背景：三星健康读取原先只在 Life 页面（健康子 tab）触发，用户打开 App 后
 * 不点「生活 → 健康」就一直是旧数据，聊天与健康上下文也跟着陈旧。
 *
 * 行为：
 * - App 进入前台（[com.aveline.ai.mobile.presentation.MainActivity.onCreate]）立即拉一次
 *   全量数据并上报后端；
 * - 未授权时静默跳过（启动阶段不弹权限窗，授权入口仍留在 Life 页）；
 * - [lastSyncAt] 供 Life 页判断「刚同步过」，避免进入页面后重复读取。
 */
@Singleton
class StartupHealthSyncManager @Inject constructor(
    private val reader: SamsungHealthReader,
    private val healthRepository: HealthRepository
) {
    /** 最近一次成功同步的完成时间（毫秒）；0 表示本次进程尚未同步成功。 */
    @Volatile
    var lastSyncAt: Long = 0L
        private set

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val mutex = Mutex()

    @Volatile
    private var startupJob: Job? = null

    /**
     * 启动时触发一次同步。
     *
     * 幂等：同一进程 60 秒内不重复，正在同步时直接复用当前任务；
     * 不阻塞主线程，失败只记日志。
     */
    fun syncOnAppStart() {
        if (System.currentTimeMillis() - lastSyncAt < MIN_INTERVAL_MS) return
        if (startupJob?.isActive == true) return
        startupJob = scope.launch {
            runCatching { syncNow() }
                .onFailure { Log.w(TAG, "启动同步失败: ${it.message}") }
        }
    }

    /**
     * 立即同步一次；未授权（或读取/上报失败）返回 false。
     *
     * 用 Mutex 串行化，避免启动同步与 Life 页同步同时读 SDK。
     */
    suspend fun syncNow(): Boolean = mutex.withLock {
        if (!reader.hasPermissions()) {
            Log.i(TAG, "未授权三星健康，启动同步跳过")
            return@withLock false
        }
        val snapshot = runCatching { reader.readAll(includeBodyComposition = true) }
            .getOrElse { error ->
                Log.w(TAG, "读取三星健康失败: ${error.message}")
                return@withLock false
            }
        healthRepository.syncHealthData(snapshot.toSyncJson())
            .onSuccess {
                lastSyncAt = System.currentTimeMillis()
                Log.i(TAG, "启动同步完成")
            }
            .onFailure { Log.w(TAG, "启动同步上报失败: ${it.message}") }
            .isSuccess
    }

    /** Life 页三星同步成功后回写时间，避免进入页面立刻重复同步。 */
    fun markSynced() {
        lastSyncAt = System.currentTimeMillis()
    }

    /**
     * 串行化 Samsung SDK 读取。
     *
     * 启动同步与 Life 页同步可能同时发生（用户启动后立刻点进生活），
     * SDK 并发读取既慢又可能报错，统一用同一把锁排队。
     */
    suspend fun <T> withSamsungLock(block: suspend () -> T): T = mutex.withLock { block() }

    private companion object {
        private const val TAG = "StartupHealthSync"
        private const val MIN_INTERVAL_MS = 60_000L
    }
}
