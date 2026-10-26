package com.aveline.ai.mobile.services.media

import android.content.Context
import android.net.Uri
import android.util.Log
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.utils.DataUriImage
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
 * - **data URI（后端表情包）同样落盘**：key 对 URI 全串取 SHA-256，首次预取或显示时
 *   解码写入本地仓库，冷启动直接读文件，不再每次重新 Base64 解码；
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

        /** data URI 稳定 key 的缓存条数上限（几百 KB 的 URI 反复哈希不值得）。 */
        private const val MAX_DATA_URI_KEY_CACHE = 64

        /** 批量预热失败的 URL 冷却时长：后端离线时避免每轮消息刷新都重等连接超时。 */
        private const val PREFETCH_RETRY_COOLDOWN_MS = 5 * 60 * 1000L
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val downloadLocks = ConcurrentHashMap<String, Mutex>()
    // 批量预热失败记录：url -> 失败时间，冷却期内不再重试
    private val prefetchFailedAt = ConcurrentHashMap<String, Long>()
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
     * @return 本地文件；content URI / data URI 解码失败 / 下载失败返回 null
     */
    suspend fun cache(rawUrl: String, resolvedUrl: String = resolveRemote(rawUrl)): File? {
        val key = stableKey(rawUrl) ?: return null
        return try {
            lookup(rawUrl)?.let { return it }

            val lock = downloadLocks.getOrPut(key) { Mutex() }
            lock.withLock {
                lookup(rawUrl)?.let { return@withLock it }
                val cached = if (DataUriImage.isDataUri(rawUrl)) {
                    // 表情包是内嵌 base64：解码写盘即可，不走网络下载
                    storeDataUriBytes(key, rawUrl)
                } else {
                    downloadPermits.withPermit { download(key, resolvedUrl) }
                }
                cached?.also { trimIfNeeded() }
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

    /**
     * 批量预热：进聊天页时把历史消息里的媒体一次性后台落盘。
     *
     * 旧行为只在消息被渲染到屏幕上时才触发下载，未滚动到的历史表情包/图片永远不落盘；
     * 后端一关就整屏转圈等网络超时。这里不依赖渲染，本窗口消息一加载就开始补。
     *
     * 与 [prefetch] 的差别：失败的 URL 记冷却时间 —— 消息流每次刷新（新消息落库、
     * 翻页）都会重进这里，后端不可达时不能每轮都去等一遍连接超时。
     */
    fun prefetchAll(rawUrls: Collection<String>) {
        val pending = rawUrls.map { it.trim() }.filter { it.isNotEmpty() }.distinct()
        if (pending.isEmpty()) return
        scope.launch {
            val now = System.currentTimeMillis()
            pending.forEach { url ->
                if (stableKey(url) == null) return@forEach
                if (lookup(url) != null) return@forEach
                val failedAt = prefetchFailedAt[url]
                if (failedAt != null && now - failedAt < PREFETCH_RETRY_COOLDOWN_MS) return@forEach
                val cached = runCatching { cache(url) }.getOrNull()
                if (cached != null) {
                    prefetchFailedAt.remove(url)
                } else {
                    prefetchFailedAt[url] = now
                }
            }
        }
    }

    // ==================== 内部实现 ====================

    /**
     * 稳定 key：只保留 URL 的 path。
     *
     * - `http://host:8000/output/image/a.png` -> `output/image/a.png`
     * - `/output/image/a.png` -> `output/image/a.png`
     * - `data:image/png;base64,...` -> `data/<sha256>.png`（对 URI 全串哈希，跨会话稳定）
     * - `content:` / `file:` 本来就是本地数据，不参与落盘
     */
    private fun stableKey(rawUrl: String): String? {
        val trimmed = rawUrl.trim()
        if (trimmed.isEmpty()) return null
        // 后端表情包以 data URI 下发：必须落盘，否则每次冷启动都要重新 Base64 解码
        if (DataUriImage.isDataUri(trimmed)) return cachedDataUriKey(trimmed)
        if (trimmed.startsWith("content:", ignoreCase = true) ||
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

    // data URI 动辄几百 KB，聊天列表滚动时同一批 URI 会被反复 lookup；
    // 稳定 key 只按原文算一次，之后纯内存查表
    private val dataUriKeyCache = object : LinkedHashMap<String, String>(32, 0.75f, false) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, String>): Boolean =
            size > MAX_DATA_URI_KEY_CACHE
    }

    @Synchronized
    private fun cachedDataUriKey(uri: String): String {
        dataUriKeyCache[uri]?.let { return it }
        val key = "data/${sha256(uri)}.${mimeExtension(DataUriImage.mimeTypeOf(uri))}"
        dataUriKeyCache[uri] = key
        return key
    }

    /** 从 MIME 类型推断扩展名（image/png -> png）；未知类型用 bin（Coil 按内容识别）。 */
    private fun mimeExtension(mime: String?): String {
        val ext = mime?.substringAfter('/')?.lowercase()
        return ext?.takeIf { it in KNOWN_EXTENSIONS } ?: "bin"
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

    /** data URI 落盘：解码 base64 写入本地仓库，key 与内容一一对应。 */
    private fun storeDataUriBytes(key: String, rawUri: String): File? {
        val bytes = DataUriImage.decode(rawUri) ?: return null
        val target = File(root, fileName(key))
        if (target.isFile && target.length() > 0) return target

        val temp = File(root, "${target.name}.tmp")
        return try {
            root.mkdirs()
            temp.writeBytes(bytes)
            if (!temp.renameTo(target)) {
                temp.copyTo(target, overwrite = true)
                temp.delete()
            }
            target.setLastModified(System.currentTimeMillis())
            target.takeIf { it.isFile && it.length() > 0 }
        } catch (e: Exception) {
            Log.w(TAG, "data URI 落盘失败: ${e.message}")
            temp.delete()
            null
        }
    }

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
