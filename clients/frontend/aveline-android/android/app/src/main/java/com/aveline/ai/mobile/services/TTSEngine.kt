package com.aveline.ai.mobile.services

import android.media.AudioAttributes
import android.media.MediaPlayer
import android.util.Base64
import android.util.Log
import com.aveline.ai.mobile.data.remote.api.AvelineApiService
import com.aveline.ai.mobile.data.remote.dto.TTSRequest
import com.aveline.ai.mobile.services.tts.CloudTtsSynthesizer
import com.aveline.ai.mobile.services.tts.TtsAudioCache
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineExceptionHandler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlin.coroutines.resume
import java.io.File
import java.io.IOException
import javax.inject.Inject
import javax.inject.Singleton

sealed class TTSState {
    data object Idle : TTSState()
    /** 合成中。带 messageId 才能让 UI 知道是哪条消息在转圈（原先不带，导致按钮毫无反馈）。 */
    data class Loading(val messageId: String) : TTSState()
    data class Playing(val messageId: String, val progress: Float = 0f) : TTSState()
    /** position: 毫秒位置; duration: 总时长毫秒,用于UI计算进度 */
    data class Paused(val messageId: String, val position: Int = 0, val duration: Int = 0) : TTSState()
    data class Error(val message: String) : TTSState()
}

@Singleton
class TTSEngine @Inject constructor(
    private val apiService: AvelineApiService,
    /** 云端 TTS 直连：可用时音频不再经后端中转，失败自动回退 [apiService]。 */
    private val cloudTtsSynthesizer: CloudTtsSynthesizer,
    /** 两条合成链路共用的音频文件缓存（命名 / 扩展名清理 / LRU）。 */
    private val audioCache: TtsAudioCache
) {

    companion object {
        private const val TAG = "TTSEngine"
        private const val PROGRESS_UPDATE_INTERVAL = 100L
        private const val BASE64_PREFIX = "data:audio/wav;base64,"
    }

    private var mediaPlayer: MediaPlayer? = null
    private var progressJob: Job? = null
    // 保存合成协程引用,新播放前取消上一个,避免并发合成导致资源竞争和状态错乱
    private var synthesizeJob: Job? = null

    private val _state = MutableStateFlow<TTSState>(TTSState.Idle)
    val state: StateFlow<TTSState> = _state.asStateFlow()

    // 最后一道网：TTS 出任何未捕获异常（含 Error）都降级为 Error 状态，
    // 绝不能让「点一下播放」把整个进程带走。
    private val ttsExceptionHandler = CoroutineExceptionHandler { _, throwable ->
        Log.e(TAG, "TTS 协程未捕获异常", throwable)
        _state.value = TTSState.Error("语音播放出错: ${throwable.message ?: throwable.javaClass.simpleName}")
    }

    // 使用 SupervisorJob,避免单次异常取消整个 scope 导致后续 TTS 永久失效
    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob() + ttsExceptionHandler)

    private var currentMessageId: String? = null
    private var currentPosition: Int = 0

    // ==================== 流式分句播放 ====================
    // LLM 流式输出时边收边播: chunk -> 按标点切句 -> 句子入 sentenceChannel
    // -> 合成协程逐句请求 TTS -> 音频文件入 audioChannel -> 播放协程串行播放
    // 合成与播放解耦,合成可并行(网络),播放串行(避免音频重叠)
    private var streamSession: StreamTtsSession? = null

    private class StreamTtsSession(
        val messageId: String,
        val voiceId: String?,
        val buffer: StringBuilder = StringBuilder(),
        val sentenceChannel: Channel<String>,
        val audioChannel: Channel<File>,
        val synthJob: Job,
        val playJob: Job
    )

    // 流式切句标点: 句末标点 + 分号 + 换行
    private val STREAM_SENTENCE_END = Regex("[。！？!?；;\n]")

    fun playMessage(messageId: String, text: String, voiceId: String? = null) {
        if (_state.value is TTSState.Playing && currentMessageId == messageId) {
            pause()
            return
        }

        if (_state.value is TTSState.Paused && currentMessageId == messageId) {
            resume()
            return
        }

        stop()
        // 取消上一次合成协程,避免快速连续点击播放不同消息时,前一个协程继续写入文件、调用 playAudioFile 导致状态错乱
        synthesizeJob?.cancel()
        currentMessageId = messageId
        _state.value = TTSState.Loading(messageId)

        synthesizeJob = scope.launch {
            try {
                val audioFile = synthesizeAndCache(messageId, text, voiceId)
                if (audioFile != null) {
                    withContext(Dispatchers.Main) {
                        playAudioFile(messageId, audioFile)
                    }
                } else {
                    _state.value = TTSState.Error("语音合成失败")
                }
            } catch (e: CancellationException) {
                // 取消（用户点了停止 / 切消息）原样上抛，不能当失败处理
                throw e
            } catch (t: Throwable) {
                // Throwable：连 NoClassDefFoundError 这类 Error 也兜住，
                // 只显示错误状态，绝不闪退
                Log.e(TAG, "TTS合成失败", t)
                _state.value = TTSState.Error("语音合成失败: ${t.message ?: t.javaClass.simpleName}")
            }
        }
    }

    private suspend fun synthesizeAndCache(
        messageId: String,
        text: String,
        voiceId: String?
    ): File? = withContext(Dispatchers.IO) {
        try {
            // 同一条消息 + 同一音色重复播放时直接复用本地音频：
            // 直连链路绕过了后端的 TTS 缓存，这里必须自己兜住，否则每次点播放都打一次云端。
            val cacheKey = audioCacheKey(messageId, voiceId)
            audioCache.find(cacheKey)?.let { return@withContext it }

            // 1) 云端 provider 支持直连时，客户端直接请求云端，音频不再经后端中转。
            //    失败（未启用、网络异常、云端报错）自动落到下面的后端链路。
            synthesizeDirect(cacheKey, text, voiceId)?.let { return@withContext it }

            // 2) 回退：后端合成（本地引擎 qwen3 / gpt_sovits / f5 只能走这条）
            val request = TTSRequest(
                text = text,
                text_lang = "zh",
                speed = 1.0f,
                reference_audio = voiceId
            )

            val response = apiService.synthesizeTTS(request)

            val data = response.data
            if (data == null || data.audio_base64.isEmpty()) {
                Log.e(TAG, "TTS返回数据为空")
                return@withContext null
            }

            val base64Data = if (data.audio_base64.startsWith(BASE64_PREFIX)) {
                data.audio_base64.substring(BASE64_PREFIX.length)
            } else {
                data.audio_base64
            }

            val bytes = Base64.decode(base64Data, Base64.DEFAULT)
            val audioFile = audioCache.write(cacheKey, bytes, "wav")
            Log.d(TAG, "TTS音频已缓存(后端): ${audioFile.absolutePath}, 大小=${bytes.size}字节")
            audioFile
        } catch (e: Exception) {
            Log.e(TAG, "TTS合成请求失败", e)
            null
        }
    }

    /** 直连云端 TTS；未启用或失败返回 null。 */
    private suspend fun synthesizeDirect(
        cacheKey: String,
        text: String,
        voiceId: String?
    ): File? {
        val chunk = try {
            cloudTtsSynthesizer.synthesize(text, voiceId)
        } catch (e: Exception) {
            Log.w(TAG, "直连 TTS 异常，回退后端: ${e.message}")
            null
        } ?: return null

        if (chunk.bytes.isEmpty()) return null
        return try {
            val audioFile = audioCache.write(cacheKey, chunk.bytes, chunk.extension)
            Log.d(TAG, "TTS音频已缓存(直连): ${audioFile.absolutePath}, 大小=${chunk.bytes.size}字节")
            audioFile
        } catch (e: Exception) {
            Log.w(TAG, "直连 TTS 音频落盘失败，回退后端: ${e.message}")
            null
        }
    }

    /**
     * 缓存 key：消息 id + 音色指纹。
     *
     * 只按 messageId 会把「换了音色再播同一条消息」错误复用到旧音频；
     * 叠加音色哈希后，切音色自然会合成新文件，旧文件交给 LRU 淘汰。
     */
    private fun audioCacheKey(messageId: String, voiceId: String?): String {
        val voice = voiceId?.trim().orEmpty()
        if (voice.isEmpty()) return messageId
        return "${messageId}_v${Integer.toHexString(voice.hashCode())}"
    }

    private fun playAudioFile(messageId: String, audioFile: File) {
        try {
            mediaPlayer = MediaPlayer().apply {
                setAudioAttributes(
                    AudioAttributes.Builder()
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                        .setUsage(AudioAttributes.USAGE_MEDIA)
                        .build()
                )

                setOnPreparedListener {
                    start()
                    startProgressTracking()
                    _state.value = TTSState.Playing(messageId, 0f)
                }

                setOnCompletionListener {
                    stopProgressTracking()
                    _state.value = TTSState.Idle
                    currentMessageId = null
                    this@TTSEngine.currentPosition = 0
                }

                setOnErrorListener { _, what, extra ->
                    Log.e(TAG, "MediaPlayer error: what=$what, extra=$extra")
                    _state.value = TTSState.Error("播放失败")
                    false
                }

                setDataSource(audioFile.absolutePath)
                prepareAsync()
            }
        } catch (e: IOException) {
            Log.e(TAG, "Failed to setup MediaPlayer", e)
            _state.value = TTSState.Error("音频加载失败: ${e.message}")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to setup MediaPlayer", e)
            _state.value = TTSState.Error("播放失败: ${e.message}")
        }
    }

    fun pause() {
        mediaPlayer?.let { player ->
            if (player.isPlaying) {
                currentPosition = player.currentPosition
                player.pause()
                stopProgressTracking()
                currentMessageId?.let { id ->
                    _state.value = TTSState.Paused(id, currentPosition, player.duration)
                }
            }
        }
    }

    fun resume() {
        mediaPlayer?.let { player ->
            if (!player.isPlaying && currentMessageId != null) {
                player.start()
                startProgressTracking()
                currentMessageId?.let { id ->
                    _state.value = TTSState.Playing(id, currentPosition.toFloat() / player.duration.coerceAtLeast(1))
                }
            }
        }
    }

    fun stop() {
        // 清理流式播放会话(取消合成/播放协程,关闭通道)
        stopStreamingPlaybackInternal()
        stopProgressTracking()
        // 同时取消合成协程,避免 stop 后仍有后台合成任务回调到已释放的 MediaPlayer
        synthesizeJob?.cancel()
        synthesizeJob = null
        mediaPlayer?.apply {
            try {
                if (isPlaying) stop()
            } catch (_: Exception) {
            }
            reset()
            release()
        }
        mediaPlayer = null
        currentMessageId = null
        currentPosition = 0
        _state.value = TTSState.Idle
    }

    fun seekTo(position: Int) {
        mediaPlayer?.let { player ->
            player.seekTo(position)
            currentPosition = position
        }
    }

    fun setSpeed(speed: Float) {
        mediaPlayer?.let { player ->
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.M) {
                try {
                    player.playbackParams = player.playbackParams.apply {
                        this.speed = speed.coerceIn(0.5f, 2.0f)
                    }
                } catch (_: Exception) {
                }
            }
        }
    }

    private fun startProgressTracking() {
        progressJob?.cancel()
        progressJob = scope.launch {
            while (isActive) {
                mediaPlayer?.let { player ->
                    if (player.isPlaying) {
                        val progress = player.currentPosition.toFloat() / player.duration.coerceAtLeast(1)
                        currentMessageId?.let { id ->
                            _state.value = TTSState.Playing(id, progress)
                        }
                    }
                }
                delay(PROGRESS_UPDATE_INTERVAL)
            }
        }
    }

    private fun stopProgressTracking() {
        progressJob?.cancel()
        progressJob = null
    }

    fun clearCache() {
        audioCache.clear()
    }

    // ==================== 流式分句播放接口 ====================

    /**
     * 开始流式播放会话。LLM 流式输出前调用,初始化合成/播放管线。
     * 会先停止当前播放和上一个流式会话。
     *
     * 管线: chunk -> appendStreamingChunk 按标点切句 -> sentenceChannel
     *       -> 合成协程逐句请求 TTS -> audioChannel -> 播放协程串行播放
     */
    fun startStreamingPlayback(messageId: String, voiceId: String? = null) {
        stop()  // 停止单次播放和上一个流式会话
        currentMessageId = messageId
        _state.value = TTSState.Loading(messageId)

        val sentenceCh = Channel<String>(capacity = Channel.UNLIMITED)
        val audioCh = Channel<File>(capacity = Channel.UNLIMITED)
        val msgId = messageId
        val voice = voiceId

        // 合成协程: 从句子通道取句子,请求 TTS 合成,音频文件送入播放通道
        val synthJob = scope.launch(Dispatchers.IO) {
            var seq = 0
            try {
                for (sentence in sentenceCh) {
                    val file = synthesizeAndCache("${msgId}_stream_${seq}", sentence, voice)
                    seq++
                    if (file != null && isActive) {
                        audioCh.send(file)
                    }
                }
            } catch (_: Exception) {
                // 协程被取消或发送异常,忽略
            } finally {
                // 句子流结束,关闭播放通道,播放协程会自然结束
                audioCh.close()
            }
        }

        // 播放协程: 串行播放音频,前一句播完才播下一句
        val playJob = scope.launch(Dispatchers.Main) {
            try {
                for (file in audioCh) {
                    if (!isActive) break
                    playStreamingFile(msgId, file)
                }
            } catch (_: Exception) {
                // 忽略
            } finally {
                // 播放队列耗尽且无新音频,会话结束
                if (_state.value !is TTSState.Error && currentMessageId == msgId) {
                    _state.value = TTSState.Idle
                    currentMessageId = null
                }
                streamSession = null
            }
        }

        streamSession = StreamTtsSession(
            messageId = msgId,
            voiceId = voice,
            sentenceChannel = sentenceCh,
            audioChannel = audioCh,
            synthJob = synthJob,
            playJob = playJob
        )
    }

    /**
     * 追加流式文本增量。内部按标点切句,完整句子立即送合成。
     * 调用方: 收到 LLM chunk 时调用,传入增量文本。
     */
    fun appendStreamingChunk(text: String) {
        val session = streamSession ?: return
        if (text.isEmpty()) return
        session.buffer.append(text)
        val (sentences, remaining) = extractCompleteSentences(session.buffer.toString())
        session.buffer.clear()
        session.buffer.append(remaining)
        for (s in sentences) {
            session.sentenceChannel.trySend(s)
        }
    }

    /**
     * 流式输出结束。处理 buffer 剩余文本,关闭句子通道。
     * 调用方: LLM Done 事件后调用。
     */
    fun finishStreamingPlayback() {
        val session = streamSession ?: return
        if (session.buffer.isNotEmpty()) {
            val last = session.buffer.toString().trim()
            session.buffer.clear()
            if (last.isNotEmpty()) {
                session.sentenceChannel.trySend(last)
            }
        }
        session.sentenceChannel.close()
    }

    /**
     * 内部: 停止并清理流式会话(取消协程,关闭通道)
     */
    private fun stopStreamingPlaybackInternal() {
        streamSession?.let { session ->
            try { session.sentenceChannel.close() } catch (_: Exception) {}
            session.synthJob.cancel()
            session.playJob.cancel()
        }
        streamSession = null
    }

    /**
     * 流式串行播放单个音频文件,suspend 直到播放完成(或出错/取消)。
     */
    private suspend fun playStreamingFile(messageId: String, audioFile: File) =
        withContext(Dispatchers.Main) {
            suspendCancellableCoroutine<Unit> { cont ->
                var player: MediaPlayer? = null
                try {
                    player = MediaPlayer().apply {
                        setAudioAttributes(
                            AudioAttributes.Builder()
                                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                                .setUsage(AudioAttributes.USAGE_MEDIA)
                                .build()
                        )
                        setOnPreparedListener {
                            try {
                                start()
                                _state.value = TTSState.Playing(messageId, 0f)
                            } catch (e: Exception) {
                                Log.e(TAG, "流式播放 start 失败", e)
                                try { release() } catch (_: Exception) {}
                                if (cont.isActive) cont.resume(Unit)
                            }
                        }
                        setOnCompletionListener {
                            try { release() } catch (_: Exception) {}
                            if (cont.isActive) cont.resume(Unit)
                        }
                        setOnErrorListener { _, what, extra ->
                            Log.e(TAG, "流式播放 error: what=$what, extra=$extra")
                            try { release() } catch (_: Exception) {}
                            if (cont.isActive) cont.resume(Unit)
                            true
                        }
                        setDataSource(audioFile.absolutePath)
                        prepareAsync()
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "流式播放 setup 失败", e)
                    try { player?.release() } catch (_: Exception) {}
                    if (cont.isActive) cont.resume(Unit)
                }
                cont.invokeOnCancellation {
                    try { player?.release() } catch (_: Exception) {}
                }
            }
        }

    /**
     * 从 buffer 中切出完整句子(以句末标点/分号/换行结尾)。
     * @return (完整句子列表, 剩余未成句文本)
     */
    private fun extractCompleteSentences(buffer: String): Pair<List<String>, String> {
        if (buffer.isEmpty()) return emptyList<String>() to ""
        val sentences = mutableListOf<String>()
        var lastEnd = 0
        for (match in STREAM_SENTENCE_END.findAll(buffer)) {
            val end = match.range.last + 1
            val sentence = buffer.substring(lastEnd, end).trim()
            if (sentence.isNotEmpty()) sentences.add(sentence)
            lastEnd = end
        }
        val remaining = if (lastEnd < buffer.length) buffer.substring(lastEnd) else ""
        return sentences to remaining
    }

    fun destroy() {
        stop()
        clearCache()
    }
}
