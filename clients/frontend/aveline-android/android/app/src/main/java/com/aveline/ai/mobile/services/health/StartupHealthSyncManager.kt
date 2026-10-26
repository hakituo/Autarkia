package com.aveline.ai.mobile.services.health

import android.util.Log
import com.aveline.ai.mobile.data.samsung.SamsungHealthReader
import com.aveline.ai.mobile.data.samsung.SamsungHealthSnapshot
import com.aveline.ai.mobile.data.samsung.toSyncJson
import com.aveline.ai.mobile.domain.repository.HealthRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withTimeoutOrNull
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 一次三星健康读取的结果及其读取时间。
 *
 * 快照必须带上读取时间：UI 层要靠它判断"这份数据有多旧"，
 * 只有时间戳和快照绑在一起才不会读到"旧快照配新时间"的假象。
 */
data class SamsungHealthSnapshotCache(
    val snapshot: SamsungHealthSnapshot,
    val readAt: Long,
    /** 这份快照是否已经成功上报过后端；false 时 Life 页需要补报一次。 */
    val reported: Boolean = false
)

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
 * - 读取到的快照会留在 [cache] 里，Life 页直接复用，不必再读一次 SDK
 *   （以前快照"用完即弃"，Life 页只能自己再读一遍全量 SDK，这就是"进 Life 页要卡几秒"的根因）。
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

    /** 最近一次从 SDK 读到的快照（可能尚未上报成功，UI 仍可直接用）。 */
    private val _cache = MutableStateFlow<SamsungHealthSnapshotCache?>(null)
    val cache: StateFlow<SamsungHealthSnapshotCache?> = _cache.asStateFlow()

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
        // 先把快照放进缓存：即使上报后端失败，UI 层也能直接用这份数据，
        // 不必再读一次 SDK（那要好几秒）。
        val readAt = System.currentTimeMillis()
        _cache.value = SamsungHealthSnapshotCache(snapshot, readAt, reported = false)
        healthRepository.syncHealthData(snapshot.toSyncJson())
            .onSuccess {
                lastSyncAt = readAt
                _cache.value = SamsungHealthSnapshotCache(snapshot, readAt, reported = true)
                Log.i(TAG, "启动同步完成")
            }
            .onFailure { Log.w(TAG, "启动同步上报失败: ${it.message}") }
            .isSuccess
    }

    /** Life 页三星同步成功后回写时间与快照，避免进入页面立刻重复同步。 */
    fun markSynced(snapshot: SamsungHealthSnapshot) {
        val readAt = System.currentTimeMillis()
        _cache.value = SamsungHealthSnapshotCache(snapshot, readAt, reported = true)
        lastSyncAt = readAt
    }

    /**
     * 串行化 Samsung SDK 读取。
     *
     * 启动同步与 Life 页同步可能同时发生（用户启动后立刻点进生活），
     * SDK 并发读取既慢又可能报错，统一用同一把锁排队。
     */
    suspend fun <T> withSamsungLock(block: suspend () -> T): T = mutex.withLock { block() }

    /** 启动同步是否正在进行。 */
    val isSyncing: Boolean
        get() = startupJob?.isActive == true

    /**
     * 等启动同步结束并取回它的结果。
     *
     * Life 页在启动同步还没跑完时被打开时，调用方应当等它而不是自己再读一次 SDK
     * ——两个任务都去读几十个 SDK 查询，只会一起变慢。
     */
    suspend fun awaitStartupSync(maxWaitMs: Long): SamsungHealthSnapshotCache? {
        val job = startupJob
        if (job != null && job.isActive) {
            withTimeoutOrNull(maxWaitMs) { job.join() }
        }
        return _cache.value
    }

    private companion object {
        private const val TAG = "StartupHealthSync"
        private const val MIN_INTERVAL_MS = 60_000L
    }
}
