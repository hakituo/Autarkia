package com.aveline.ai.mobile.services.tts

import android.os.SystemClock
import android.util.Log
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.data.remote.api.AvelineApiService
import com.aveline.ai.mobile.data.remote.dto.TtsDirectConfigDto
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withTimeoutOrNull
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 拉取并缓存「客户端直连云端 TTS」的配置。
 *
 * 设计要点：
 * - 后端换地址（局域网 / 组网 / 公网切换）后配置可能不同，缓存按生效后端地址隔离；
 * - 云端 provider 配置成功缓存 10 分钟；失败 / 本地 provider 只缓存 60 秒，
 *   避免用户在后端改完配置后客户端长时间不生效；
 * - 拉取最多等 5 秒：直连只是加速链路，不能因为后端不可达把 TTS 一起卡死，
 *   超时后 [get] 返回 null，调用方自动回退 `/api/v1/media/tts`。
 */
@Singleton
class CloudTtsConfigRepository @Inject constructor(
    private val apiService: AvelineApiService,
    private val appPreferences: AppPreferences
) {
    companion object {
        private const val TAG = "CloudTtsConfig"
        private const val SUCCESS_TTL_MS = 10 * 60 * 1000L
        private const val NON_DIRECT_TTL_MS = 60 * 1000L
        private const val FETCH_TIMEOUT_MS = 5_000L
    }

    private val mutex = Mutex()

    @Volatile
    private var cached: TtsDirectConfigDto? = null

    @Volatile
    private var cachedBackend: String = ""

    @Volatile
    private var cachedAt: Long = 0L

    /** 拉取失败的时间戳：失败也要在短时间内缓存，避免每次播报都重新等超时。 */
    @Volatile
    private var failureAt: Long = 0L

    /** 取直连配置；返回 null 表示「本次不要走直连」。 */
    suspend fun get(force: Boolean = false): TtsDirectConfigDto? {
        val backend = appPreferences.effectiveBackendUrl.trim()
        val now = SystemClock.elapsedRealtime()
        val ttl = if (cached?.enabled == true) SUCCESS_TTL_MS else NON_DIRECT_TTL_MS
        if (!force && cached != null && cachedBackend == backend && now - cachedAt < ttl) {
            return cached
        }
        if (!force && cached == null && now - failureAt < NON_DIRECT_TTL_MS) {
            return null
        }

        return mutex.withLock {
            val recheckNow = SystemClock.elapsedRealtime()
            if (!force && cached != null && cachedBackend == backend &&
                recheckNow - cachedAt < ttl
            ) {
                return@withLock cached
            }

            val fetched = withTimeoutOrNull(FETCH_TIMEOUT_MS) {
                runCatching { apiService.getTtsDirectConfig() }
                    .onFailure { Log.w(TAG, "拉取直连配置失败: ${it.message}") }
                    .getOrNull()
                    ?.data
            }

            cached = fetched
            cachedBackend = backend
            cachedAt = SystemClock.elapsedRealtime()
            if (fetched == null) {
                failureAt = cachedAt
                Log.w(TAG, "拉取直连配置失败，60 秒内走后台合成")
            } else if (!fetched.enabled) {
                Log.i(TAG, "直连 TTS 未启用(${fetched.reason})，回退后端合成")
            }
            fetched
        }
    }

}
