package com.aveline.ai.mobile.services.media

import android.content.Context
import android.net.Uri
import android.util.Log
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.utils.MediaUrlResolver
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.sync.withPermit
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 聊天媒体本地仓库（图片 / 动图 / 表情包 / 视频）。
 *
 * 目标与 QQ / 微信一致：**本地占大头**。后端 `output/` 里的媒体文件只属于当前那台
 * 后端机器，换后端（例如 Windows -> Linux）后旧消息里的 `/output/...` 会 404，
 * 表现为历史图片全部破图。这里在首次加载成功后把媒体落盘到 App 私有目录，
 * 之后无论后端地址怎么切换都优先读本地文件。
 *
 * 关键设计：
 * - **缓存 key 与后端地址无关**：只取 URL 的 path（如 `output/image/chat/a.png`），
 *   所以同一张图换后端后仍命中同一份本地文件；
 * - 落盘目录是 `filesDir/chat_media`（不是 cacheDir）：系统清理缓存不会把历史图片清掉；
 * - 下载走独立 OkHttpClient：不能复用后端的 client（它有 baseUrl 拦截器，会把
 *   外部 CDN 域名改写成本地后端），鉴权头由 AppPreferences 手动补上；
 * - 单文件上限 80MB、总量上限 1GB，超出按 lastModified 最旧优先淘汰；
 * - 同一 key 的并发下载用 Mutex 串行，避免重复写临时文件。
 */
@Singleton
class LocalMediaStore @Inject constructor(
    @ApplicationContext private val context: Context,
    private val appPreferences: AppPreferences
) {
    companion object {
        private const val TAG = "LocalMediaStore"
        private const val DIR_NAME = "chat_media"
        private const val MAX_TOTAL_BYTES = 1024L * 1024L * 1024L
        private const val MAX_FILE_BYTES = 80L * 1024L * 1024L
        private val KNOWN_EXTENSIONS = setOf(
            "png", "jpg", "jpeg", "gif", "webp", "bmp", "heic", "avif",
            "mp4", "webm", "mov", "m4v", "mkv",
            "mp3", "wav", "ogg", "m4a", "aac", "flac"
        )
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val downloadLocks = ConcurrentHashMap<String, Mutex>()
    // 同时最多 3 个媒体下载：历史消息一次渲染多条时不把后端/带宽打满
    private val downloadPermits = Semaphore(3)
    private val root: File by lazy {
        File(context.filesDir, DIR_NAME).apply { mkdirs() }
    }

    // 云端媒体 / 外部 CDN 不能走后端 client 的 baseUrl 拦截器
    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .build()

    /** 同步查询本地是否已有该媒体；命中直接返回 File，供 Compose/ExoPlayer 使用。 */
    fun lookup(rawUrl: String): File? {
        val key = stableKey(rawUrl) ?: return null
        return runCatching {
            File(root, fileName(key)).takeIf { it.isFile && it.length() > 0 }
        }.getOrNull()
    }

    /**
     * 确保媒体已落盘。
     *
     * @param rawUrl 后端下发的原始地址（相对路径或绝对 URL），用于计算稳定 key
     * @param resolvedUrl 已补全的绝对地址；不传则用当前生效后端补全
     * @return 本地文件；data URI / content URI / 下载失败返回 null
     */
    suspend fun cache(rawUrl: String, resolvedUrl: String = resolveRemote(rawUrl)): File? {
        val key = stableKey(rawUrl) ?: return null
        return try {
            lookup(rawUrl)?.let { return it }

            val lock = downloadLocks.getOrPut(key) { Mutex() }
            lock.withLock {
                lookup(rawUrl)?.let { return@withLock it }
                downloadPermits.withPermit { download(key, resolvedUrl) }?.also {
                    trimIfNeeded()
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "媒体本地缓存失败: ${e.message}")
            null
        }
    }

    /** 后台预取：收到新图/视频时立刻落盘，用户不用等到滚到那条消息。 */
    fun prefetch(rawUrl: String) {
        if (stableKey(rawUrl) == null) return
        if (lookup(rawUrl) != null) return
        scope.launch {
            runCatching { cache(rawUrl) }
                .onFailure { Log.w(TAG, "预取媒体失败: ${it.message}") }
        }
    }

    // ==================== 内部实现 ====================

    /**
     * 稳定 key：只保留 URL 的 path。
     *
     * - `http://host:8000/output/image/a.png` -> `output/image/a.png`
     * - `/output/image/a.png` -> `output/image/a.png`
     * - `data:` / `content:` / `file:` 本来就是本地或内嵌数据，不参与落盘
     */
    private fun stableKey(rawUrl: String): String? {
        val trimmed = rawUrl.trim()
        if (trimmed.isEmpty()) return null
        if (trimmed.startsWith("data:", ignoreCase = true) ||
            trimmed.startsWith("content:", ignoreCase = true) ||
            trimmed.startsWith("file:", ignoreCase = true)
        ) {
            return null
        }
        val path = runCatching { Uri.parse(trimmed).path }.getOrNull()
            ?.trim()
            ?.trimStart('/')
            .orEmpty()
        if (path.isNotEmpty()) return path
        return trimmed.trimStart('/').takeIf { it.isNotEmpty() }
    }

    private fun fileName(key: String): String = "${sha256(key)}.${extensionOf(key)}"

    private fun extensionOf(key: String): String {
        val name = key.substringAfterLast('/')
        val dot = name.lastIndexOf('.')
        if (dot <= 0 || dot == name.length - 1) return "bin"
        val ext = name.substring(dot + 1).lowercase()
        return if (ext in KNOWN_EXTENSIONS) ext else "bin"
    }

    private fun sha256(value: String): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(value.toByteArray())
        return digest.joinToString("") { "%02x".format(it) }
    }

    private fun resolveRemote(rawUrl: String): String =
        MediaUrlResolver.resolve(appPreferences.effectiveBackendUrl, rawUrl)

    private fun download(key: String, resolvedUrl: String): File? {
        if (!resolvedUrl.startsWith("http://", ignoreCase = true) &&
            !resolvedUrl.startsWith("https://", ignoreCase = true)
        ) {
            return null
        }

        val target = File(root, fileName(key))
        if (target.isFile && target.length() > 0) return target

        val temp = File(root, "${target.name}.tmp")

        try {
            val builder = Request.Builder().url(resolvedUrl).get()
            val token = appPreferences.accessToken
            if (token.isNotBlank()) {
                builder.addHeader("Authorization", "Bearer $token")
                builder.addHeader("x-internal-token", token)
            }
            client.newCall(builder.build()).execute().use { response ->
                if (!response.isSuccessful) {
                    Log.w(TAG, "媒体下载失败 HTTP ${response.code}: $resolvedUrl")
                    return null
                }
                val body = response.body ?: return null
                if (body.contentLength() > MAX_FILE_BYTES) {
                    Log.w(TAG, "媒体超过单文件上限，跳过: $resolvedUrl")
                    return null
                }
                root.mkdirs()
                body.byteStream().use { input ->
                    temp.outputStream().use { output ->
                        val buffer = ByteArray(64 * 1024)
                        var total = 0L
                        while (true) {
                            val read = input.read(buffer)
                            if (read < 0) break
                            total += read
                            if (total > MAX_FILE_BYTES) {
                                Log.w(TAG, "媒体超过单文件上限，跳过: $resolvedUrl")
                                temp.delete()
                                return null
                            }
                            output.write(buffer, 0, read)
                        }
                    }
                }
            }
            if (!temp.renameTo(target)) {
                temp.copyTo(target, overwrite = true)
                temp.delete()
            }
            target.setLastModified(System.currentTimeMillis())
            return target.takeIf { it.isFile && it.length() > 0 }
        } catch (e: Exception) {
            Log.w(TAG, "媒体下载异常: ${e.message}")
            temp.delete()
            return null
        }
    }

    /** 总量超限时按最旧优先删除。 */
    @Synchronized
    private fun trimIfNeeded() {
        val files = root.listFiles()?.filter { it.isFile && !it.name.endsWith(".tmp") } ?: return
        var total = files.sumOf { it.length() }
        if (total <= MAX_TOTAL_BYTES) return

        files.sortedBy { it.lastModified() }.forEach { file ->
            if (total <= MAX_TOTAL_BYTES) return@forEach
            val size = file.length()
            if (file.delete()) {
                total -= size
                Log.d(TAG, "LRU 淘汰本地媒体: ${file.name} ($size 字节)")
            }
        }
    }
}
