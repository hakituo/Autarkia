package com.aveline.ai.mobile.services.tts

import android.content.Context
import android.util.Log
import dagger.hilt.android.qualifiers.ApplicationContext
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton

/**
 * TTS 音频文件缓存。
 *
 * 从 [com.aveline.ai.mobile.services.TTSEngine] 抽出：直连云端与后端合成两条链路
 * 都要落盘同一套文件，缓存命名、扩展名清理与 LRU 淘汰放在一处，避免两边行为漂移。
 *
 * - key = messageId + 音色指纹（见 TTSEngine.audioCacheKey），切音色不会复用旧音频；
 * - 同一 key 可能先直连(mp3)失败后回退后端(wav)，写入前清掉其它扩展名；
 * - 总量上限 50MB，按 lastModified 最旧优先淘汰。
 */
@Singleton
class TtsAudioCache @Inject constructor(
    @ApplicationContext private val context: Context
) {
    companion object {
        private const val TAG = "TtsAudioCache"
        private const val CACHE_DIR = "tts_cache"
        private const val MAX_CACHE_BYTES = 50L * 1024L * 1024L
        private val KNOWN_EXTENSIONS = listOf("mp3", "wav", "ogg", "aac", "flac", "bin")
    }

    fun find(cacheKey: String): File? {
        val dir = cacheDir()
        for (ext in KNOWN_EXTENSIONS) {
            val file = File(dir, "tts_$cacheKey.$ext")
            if (file.isFile && file.length() > 0) return file
        }
        return null
    }

    fun write(cacheKey: String, bytes: ByteArray, extension: String): File {
        val dir = cacheDir()
        val ext = extension.ifBlank { "wav" }.trimStart('.')
        val audioFile = File(dir, "tts_$cacheKey.$ext")
        for (other in KNOWN_EXTENSIONS) {
            if (other != ext) {
                File(dir, "tts_$cacheKey.$other").takeIf { it.exists() }?.delete()
            }
        }
        trimIfNeeded(bytes.size.toLong())
        audioFile.writeBytes(bytes)
        return audioFile
    }

    fun clear() {
        try {
            cacheDir().deleteRecursively()
        } catch (e: Exception) {
            Log.e(TAG, "清理 TTS 缓存失败", e)
        }
    }

    private fun cacheDir(): File {
        val dir = File(context.cacheDir, CACHE_DIR)
        if (!dir.exists()) dir.mkdirs()
        return dir
    }

    /** 写入前按总量淘汰，保证落盘后不超过上限。 */
    @Synchronized
    private fun trimIfNeeded(incomingBytes: Long) {
        try {
            val files = cacheDir().listFiles()?.toMutableList() ?: return
            var total = files.sumOf { it.length() } + incomingBytes
            if (total <= MAX_CACHE_BYTES) return

            files.sortBy { it.lastModified() }
            for (file in files) {
                if (total <= MAX_CACHE_BYTES) break
                val size = file.length()
                if (file.delete()) {
                    total -= size
                    Log.d(TAG, "LRU淘汰 TTS 缓存: ${file.name}, ${size}字节")
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "TTS 缓存淘汰失败(忽略)", e)
        }
    }
}
