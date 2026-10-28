package com.aveline.ai.mobile.services

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.util.Log
import androidx.core.content.ContextCompat
import com.k2fsa.sherpa.ncnn.SherpaNcnn
import com.k2fsa.sherpa.ncnn.RecognizerConfig
import com.k2fsa.sherpa.ncnn.getDecoderConfig
import com.k2fsa.sherpa.ncnn.getFeatureExtractorConfig
import com.k2fsa.sherpa.ncnn.getModelConfig
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import javax.inject.Inject
import javax.inject.Singleton

/**
 * sherpa-ncnn 端侧 ASR 引擎
 *
 * 职责:
 * 1. 加载 sherpa-ncnn 模型 (从 assets, 用 AssetManager)
 * 2. 用 AudioRecord 录制 16kHz 单声道 PCM
 * 3. 把 short[] PCM 转 FloatArray (-1.0~1.0) 喂给 SherpaNcnn.acceptSamples
 * 4. 循环 decode() 拿流式 partial 结果
 * 5. 检测 endpoint (一句话说完) 自动断句
 *
 * 与 VoiceInputManager 的关系:
 * - VoiceInputManager 根据 asr_provider 配置选择本引擎或系统 SpeechRecognizer
 * - 本引擎暴露 state/partialText/finalText 供 UI 观察
 *
 * 线程模型:
 * - 录音循环 + 收尾解码 + 取消后的 reset 都可能在不同线程（IO 多线程池 / 主线程触发），
 *   所有 native 调用统一在 [nativeLock] 下串行 —— C++ 侧不是线程安全的，并发进去会 SIGSEGV
 * - 会话代号 [sessionId] 标记「这一轮是否还有效」：旧会话的协程一律提前收手
 * - state/partialText 用 StateFlow 在主线程观察
 *
 * 端点检测 (endpoint):
 * - rule1MinTrailingSilence=2.4s: 连续 2.4s 静音判定一句话结束
 * - rule2MinTrailingSilence=1.0s: 已说够一定长度后, 1s 静音即结束
 * - rule3MinUtteranceLength=30s: 单句最长 30s 强制截断
 * - 断句时把当前句累积进 committedText, 因此 partialText 始终是
 *   "已确认句 + 当前句"的完整文本, UI 可以直接拿它做流式上屏;
 *   停止录音时也不会像原来那样只剩下最后一句
 */
@Singleton
class SherpaNcnnAsrEngine @Inject constructor(
    @ApplicationContext private val context: Context
) {
    companion object {
        private const val TAG = "SherpaNcnnAsrEngine"

        // 音频参数: sherpa-ncnn 要求 16kHz 单声道 16-bit PCM
        private const val SAMPLE_RATE = 16000
        private const val CHANNEL_CONFIG = AudioFormat.CHANNEL_IN_MONO
        private const val AUDIO_FORMAT = AudioFormat.ENCODING_PCM_16BIT

        // 模型类型: 6 = streaming-zipformer-small-bilingual-zh-en (中英双语小模型)
        private const val MODEL_TYPE = 6

        // 录音每次读取的样本数 (32ms 一批, 平衡延迟和性能)
        private const val CHUNK_SAMPLES = 512 // 512 samples ≈ 32ms @ 16kHz

        // 单次录音最长时长 (防止无限录音)
        private const val MAX_RECORD_MS = 60_000L

        /**
         * 等录音循环退出的上限。
         *
         * AudioRecord.read 是阻塞 JNI 调用，协程 cancel 打断不了它，只能靠 AudioRecord.stop()
         * 把 read 踢回来。万一踢不回来（音频服务挂了等极端情况），宁可丢掉这一轮的结果，
         * 也绝不能并发进 native —— 那是进程级闪退。
         */
        private const val RECORD_JOIN_TIMEOUT_MS = 2_000L
    }

    private val engineScope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    /**
     * native 互斥锁。
     *
     * [SherpaNcnn] 的 acceptSamples / decode / inputFinished / reset 在 C++ 侧共用同一套解码状态
     * 和裸指针，本身不保证线程安全。两条线程同时进去就是 SIGSEGV —— 这类崩溃
     * CrashHandler 抓不到（它只管 Java 异常），用户看到的就是「App 突然没了、也没有日志」。
     *
     * 所以：录音循环、收尾解码、取消后的 reset 三处 native 调用必须在这把锁下串行。
     * 主线程上不放任何 native 调用，避免收尾解码跑起来时把 UI 卡住。
     */
    private val nativeLock = Any()

    /** 开录 / 停止 / 取消的状态机互斥：避免两次 stop 各起一支收尾解码。 */
    private val stateLock = Any()

    /**
     * AudioRecord 的 stop / release 互斥。
     *
     * 录音循环退出时会 release，停止 / 取消又会从别的线程 stop，两边同时打在同一支实例上
     * 一样是 native 竞态。注意 read() 不在这把锁里 —— 它就是要被 stop() 打断的，
     * 加锁反而会死锁。
     */
    private val recordLock = Any()

    @Volatile
    private var recognizer: SherpaNcnn? = null

    @Volatile
    private var audioRecord: AudioRecord? = null

    @Volatile
    private var recordJob: Job? = null

    /** 收尾解码协程（inputFinished + 余量 decode），与录音协程分开，避免它占住主线程。 */
    @Volatile
    private var flushJob: Job? = null

    @Volatile
    private var isInitialized = false

    @Volatile
    private var loadError: String? = null

    /**
     * 会话代号：每次开录 / 停止 / 取消都 +1。
     *
     * 旧会话残留的协程（录音循环、收尾解码、取消后的清理）靠它判断自己是否已经过期，
     * 过期就立刻收手 —— 不写 UI 状态、不碰 recognizer。少了这道闸，就会出现
     * 「上一轮的迟到结果覆盖这一轮」「旧循环又去读新 AudioRecord」这类并发问题。
     */
    @Volatile
    private var sessionId: Long = 0L

    private val _state = MutableStateFlow<AsrState>(AsrState.Idle)
    val state: StateFlow<AsrState> = _state.asStateFlow()

    private val _partialText = MutableStateFlow("")
    val partialText: StateFlow<String> = _partialText.asStateFlow()

    /**
     * 已通过 endpoint 断句确认的文本。
     *
     * [SherpaNcnn.text] 只反映"当前这一句"：endpoint 命中后 recognizer 会 reset，文本从空重新开始。
     * 若不在断句时累积，用户说完一句再说下一句时，前一句就会从流式结果里消失，
     * 停止录音也只能拿到最后一句。这里累积成"已确认句 + 当前句"的完整文本。
     */
    @Volatile
    private var committedText: String = ""

    /**
     * 把已确认文本与当前句拼成完整的流式文本（中文之间不补空格）。
     */
    private fun combineText(current: String): String {
        val committed = committedText.trim()
        val cur = current.trim()
        return when {
            committed.isEmpty() -> cur
            cur.isEmpty() -> committed
            else -> committed + cur
        }
    }

    private val _amplitude = MutableStateFlow(0f)
    val amplitude: StateFlow<Float> = _amplitude.asStateFlow()

    /**
     * 检查引擎是否可用 (.so 已加载 + 模型已初始化)
     *
     * .so 加载在 SherpaNcnn.companion.init 里, 失败会抛 UnsatisfiedLinkError
     * 这里用 try-catch 检测, 不影响 app 启动
     */
    fun isAvailable(): Boolean {
        return try {
            // 触发 SherpaNcnn 类加载, 看 System.loadLibrary 是否成功
            Class.forName("com.k2fsa.sherpa.ncnn.SherpaNcnn")
            true
        } catch (e: Throwable) {
            Log.w(TAG, "sherpa-ncnn 不可用: ${e.message}")
            false
        }
    }

    /** 模型是否已经加载好（[VoiceInputManager] 用它决定要不要先预热）。 */
    fun isModelLoaded(): Boolean = isInitialized

    /**
     * 初始化模型 (从 assets 加载)
     *
     * 应在 app 启动后或首次使用 ASR 前调用。
     * 耗时约 1-3s (取决于设备), 建议在 IO 线程。
     */
    @Synchronized
    fun initialize(): Boolean {
        if (isInitialized) return true
        if (!isAvailable()) {
            loadError = "sherpa-ncnn .so 库未加载, 请运行 download_assets.py 下载"
            Log.e(TAG, loadError!!)
            return false
        }

        return try {
            val modelConfig = getModelConfig(MODEL_TYPE, useGPU = false)
                ?: throw IllegalStateException("getModelConfig($MODEL_TYPE) 返回 null")

            // getModelConfig 返回的 path 不含 assets 子目录前缀
            // 模型实际放在 assets/sherpa_ncnn_models/ 下, 这里给每个 path 加前缀
            // SherpaNcnn.newFromAsset 用 AssetManager.open(path) 加载, path 相对 assets 根
            val assetsPrefix = "sherpa_ncnn_models/"
            modelConfig.encoderParam = assetsPrefix + modelConfig.encoderParam
            modelConfig.encoderBin = assetsPrefix + modelConfig.encoderBin
            modelConfig.decoderParam = assetsPrefix + modelConfig.decoderParam
            modelConfig.decoderBin = assetsPrefix + modelConfig.decoderBin
            modelConfig.joinerParam = assetsPrefix + modelConfig.joinerParam
            modelConfig.joinerBin = assetsPrefix + modelConfig.joinerBin
            modelConfig.tokens = assetsPrefix + modelConfig.tokens

            val recognizerConfig = RecognizerConfig(
                featConfig = getFeatureExtractorConfig(
                    sampleRate = SAMPLE_RATE.toFloat(),
                    featureDim = 80
                ),
                modelConfig = modelConfig,
                decoderConfig = getDecoderConfig(
                    method = "modified_beam_search",
                    numActivePaths = 4
                ),
                enableEndpoint = true,
                rule1MinTrailingSilence = 2.4f,
                rule2MinTrailingSilence = 1.0f,
                rule3MinUtteranceLength = 30.0f,
            )

            // 用 AssetManager 加载 (模型文件在 assets/sherpa_ncnn_models/ 下)
            recognizer = SherpaNcnn(recognizerConfig, context.assets)
            isInitialized = true
            loadError = null
            Log.i(TAG, "sherpa-ncnn 模型加载成功 (type=$MODEL_TYPE)")
            true
        } catch (e: UnsatisfiedLinkError) {
            loadError = "native 库加载失败: ${e.message}"
            Log.e(TAG, loadError!!, e)
            false
        } catch (e: Throwable) {
            // 连 Error 一起兜：这里抛出去就是进程级崩溃，而模型加载失败只该是「用不了 ASR」
            loadError = "模型初始化失败: ${e.message}"
            Log.e(TAG, loadError!!, e)
            false
        }
    }

    /**
     * 检查录音权限
     */
    fun hasRecordAudioPermission(): Boolean {
        return ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.RECORD_AUDIO
        ) == PackageManager.PERMISSION_GRANTED
    }

    /**
     * 开始录音 + 识别
     *
     * 流程:
     * 1. 检查权限和初始化
     * 2. 创建 AudioRecord
     * 3. 启动协程循环: 读 PCM → 转 Float → acceptSamples → decode → 更新 partialText
     * 4. 检测 endpoint → 自动断句, 累积到 finalText
     */
    fun startListening() = startListening(retriedOnce = false)

    /**
     * @param retriedOnce 上一轮录音循环还没退出时已经重试过一次，避免无限重试
     */
    private fun startListening(retriedOnce: Boolean) {
        if (!hasRecordAudioPermission()) {
            _state.value = AsrState.Error("缺少录音权限")
            return
        }

        // 模型没加载时先加载（1~3s）：放在锁外，否则会把 stop / cancel 一起堵在这把锁上
        if (!isInitialized && !initialize()) {
            _state.value = AsrState.Error(loadError ?: "sherpa-ncnn 初始化失败")
            return
        }

        synchronized(stateLock) {
            if (_state.value == AsrState.Recording) {
                stopListening()
                return
            }

            // 收尾解码还没跑完时不要重开：recognizer 正被 flush 协程占着，
            // 这时 reset / acceptSamples 会跟 decode 并发进 native。
            //
            // 这里判断用 isCompleted 而不是 isActive：Job 一旦被 cancel，isActive 立刻变 false，
            // 但 native 调用可能还在跑。用 isActive 放行就是「取消后马上再录」的闪退来源。
            if (_state.value == AsrState.Processing || flushJob?.isCompleted == false) {
                Log.w(TAG, "上一轮收尾解码未结束, 忽略本次开录")
                return
            }

            // 上一轮录音循环还卡在 AudioRecord.read 里（阻塞读，cancel 打断不了）：
            // 这时既不能释放它手上的 AudioRecord，也不能再起一支循环抢同一支麦克风。
            if (recordJob?.isCompleted == false) {
                if (retriedOnce) {
                    Log.w(TAG, "上一轮录音循环仍未退出, 放弃本次开录")
                    return
                }
                Log.i(TAG, "上一轮录音循环未退出, 等它结束后再开录")
                val staleRecord = recordJob
                engineScope.launch {
                    withTimeoutOrNull(RECORD_JOIN_TIMEOUT_MS) { staleRecord?.join() }
                    if (_state.value == AsrState.Idle) startListening(retriedOnce = true)
                }
                return
            }

            // 重置状态
            sessionId += 1
            val session = sessionId
            committedText = ""
            _partialText.value = ""
            _amplitude.value = 0f

            // 正常情况下上一轮的 AudioRecord 已由它的录音循环在 finally 里释放，这里只是兜底
            if (audioRecord != null) {
                Log.w(TAG, "上一轮 AudioRecord 未释放, 兜底释放")
                releaseAudioRecord()
            }

            val record = try {
                createAudioRecord()
            } catch (e: SecurityException) {
                _state.value = AsrState.Error("录音权限被拒绝")
                return
            } catch (e: Throwable) {
                Log.e(TAG, "创建 AudioRecord 失败", e)
                _state.value = AsrState.Error("启动录音失败: ${e.message}")
                return
            }

            if (record == null) {
                _state.value = AsrState.Error("AudioRecord 初始化失败")
                return
            }
            audioRecord = record

            try {
                record.startRecording()
            } catch (e: Throwable) {
                Log.e(TAG, "startRecording 失败", e)
                releaseAudioRecord()
                _state.value = AsrState.Error("启动录音失败: ${e.message}")
                return
            }

            _state.value = AsrState.Recording
            recordJob = engineScope.launch {
                recordLoop(session)
            }
        }
    }

    /**
     * 停止录音。
     *
     * 音频立刻停下，收尾解码（inputFinished + 余量 decode）丢到 IO 协程里做：
     * 这段是 native 计算，放在主线程会直接卡住 UI —— 用户看到的就是"点完停止要愣几秒"。
     * 状态先切 [AsrState.Processing]，结果在解码完成后通过 [state] 发出。
     *
     * 输入栏那边不会等这个结果：点「完成」时已经实时上屏的文本已经落进输入框了。
     */
    fun stopListening() {
        synchronized(stateLock) {
            if (_state.value != AsrState.Recording) {
                Log.w(TAG, "当前不在录音状态(${_state.value}), 忽略 stopListening")
                return
            }

            _state.value = AsrState.Processing
            // 换代：录音循环即使没来得及看到 Processing，也会因为代号对不上而退出
            sessionId += 1
            val session = sessionId

            val pendingRecord = recordJob
            pendingRecord?.cancel()

            // 阻塞在 AudioRecord.read 里的循环只有 stop() 能踢出来（cancel 对它无效）
            synchronized(recordLock) {
                try {
                    audioRecord?.stop()
                } catch (e: Throwable) {
                    Log.w(TAG, "AudioRecord.stop 异常: ${e.message}")
                }
            }
            _amplitude.value = 0f

            flushJob?.cancel()
            flushJob = engineScope.launch {
                // 等录音循环真正退出再碰 recognizer，否则可能和 acceptSamples 并发进 native
                val exited = pendingRecord == null || withTimeoutOrNull(RECORD_JOIN_TIMEOUT_MS) {
                    pendingRecord?.join()
                    true
                } == true
                if (!exited) {
                    // read 卡死时 native 可能还在跑：宁可丢掉这一轮，也不能并发进 native
                    Log.w(TAG, "录音循环 ${RECORD_JOIN_TIMEOUT_MS}ms 未退出, 跳过收尾解码")
                    if (_state.value == AsrState.Processing) {
                        _state.value = AsrState.Error("录音结束超时")
                    }
                    return@launch
                }

                // 期间被 cancel / 被新一轮顶掉：这一轮结果作废，也不再碰 recognizer
                if (sessionId != session) return@launch

                val result = try {
                    // native 调用统一在 nativeLock 下：和「取消后的 reset」互斥
                    synchronized(nativeLock) {
                        // 通知 recognizer 输入结束, flush 最后的解码
                        recognizer?.inputFinished()
                        while (recognizer?.isReady() == true) {
                            recognizer?.decode()
                        }
                        // 结果 = 已断句确认的文本 + recognizer 里还留着的最后一句
                        combineText(recognizer?.text ?: "").ifBlank { _partialText.value }
                    }
                } catch (e: Throwable) {
                    Log.w(TAG, "flush decode 异常: ${e.message}")
                    _partialText.value
                }

                // 期间可能被 cancel() 置回 Idle，那就不要再把结果抛回去
                if (_state.value != AsrState.Processing) return@launch

                _state.value = if (result.isNotBlank()) {
                    AsrState.Result(result)
                } else {
                    AsrState.Error("未识别到语音")
                }
            }
        }
    }

    /**
     * 取消录音 (不返回结果)
     */
    fun cancel() {
        var pendingRecord: Job? = null
        var pendingFlush: Job? = null

        val session = synchronized(stateLock) {
            // 换代：录音循环 / 迟到的收尾解码都会因为代号对不上而收手
            sessionId += 1

            pendingRecord = recordJob
            pendingRecord?.cancel()
            synchronized(recordLock) {
                try {
                    audioRecord?.stop()
                } catch (e: Throwable) {
                    Log.w(TAG, "AudioRecord.stop 异常: ${e.message}")
                }
            }

            pendingFlush = flushJob
            pendingFlush?.cancel()

            _state.value = AsrState.Idle
            committedText = ""
            _partialText.value = ""
            _amplitude.value = 0f

            sessionId
        }

        // 收尾解码 / 录音循环可能正在 native 里跑：等它们都退出，再 reset 与释放 AudioRecord。
        // 直接在这里 reset 会和 decode 并发进 native —— 那就是「录音相关操作偶发闪退」的来源。
        // flushJob 保留引用不清空，startListening 靠它挡住这段窗口里的重开。
        engineScope.launch {
            val recordExited = pendingRecord == null || withTimeoutOrNull(RECORD_JOIN_TIMEOUT_MS) {
                pendingRecord?.join()
                true
            } == true
            withTimeoutOrNull(RECORD_JOIN_TIMEOUT_MS) { pendingFlush?.join() }

            // 等待期间可能已经开了新一轮录音，那时 recognizer / AudioRecord 归新会话管，不能动
            if (sessionId != session) return@launch
            if (!recordExited) {
                // read 没退回来就 release 等于 use-after-free，宁可暂时不释放
                Log.w(TAG, "录音循环 ${RECORD_JOIN_TIMEOUT_MS}ms 未退出, 跳过 reset 与释放")
                return@launch
            }

            releaseAudioRecord()
            synchronized(nativeLock) {
                recognizer?.reset(recreate = false)
            }
        }
    }

    /**
     * 重置状态 (UI 用, 不影响 recognizer)
     */
    fun reset() {
        _state.value = AsrState.Idle
        committedText = ""
        _partialText.value = ""
        _amplitude.value = 0f
    }

    /**
     * 释放资源 (app 退出时调用)
     */
    fun destroy() {
        cancel()
        // 释放同样要等录音循环退出，否则会在 read 还在飞的时候 release
        engineScope.launch {
            withTimeoutOrNull(RECORD_JOIN_TIMEOUT_MS) { recordJob?.join() }
            releaseAudioRecord()
            synchronized(nativeLock) {
                recognizer = null
            }
            isInitialized = false
        }
    }

    // ── AudioRecord 生命周期 ─────────────────────────────

    /**
     * 创建一支 AudioRecord。初始化失败就地释放，返回 null 让调用方去报错。
     */
    private fun createAudioRecord(): AudioRecord? {
        val minBuf = AudioRecord.getMinBufferSize(SAMPLE_RATE, CHANNEL_CONFIG, AUDIO_FORMAT)
        // 至少够 2 个 chunk；getMinBufferSize 失败会返回负值，这里一并兜住
        val bufferSize = maxOf(minBuf * 2, CHUNK_SAMPLES * 2 * 2)

        @Suppress("MissingPermission")
        val record = AudioRecord(
            MediaRecorder.AudioSource.MIC,
            SAMPLE_RATE,
            CHANNEL_CONFIG,
            AUDIO_FORMAT,
            bufferSize
        )
        if (record.state != AudioRecord.STATE_INITIALIZED) {
            try {
                record.release()
            } catch (e: Throwable) {
                Log.w(TAG, "AudioRecord 初始化失败后释放异常: ${e.message}")
            }
            return null
        }
        return record
    }

    /**
     * 释放当前 AudioRecord。
     *
     * 只允许在确认没有 read() 在飞的时候调用（录音循环已退出）：read 是阻塞调用，
     * 提前 release 就是 use-after-free。这也是原先「每录一次 new 一支、永远不 release」
     * 的修复点 —— 一路漏下去会攒满 AudioFlinger 的录音客户端。
     */
    private fun releaseAudioRecord() {
        // stop() / release() 也不能跨线程同时打在同一支 AudioRecord 上
        synchronized(recordLock) {
            val record = audioRecord ?: return
            audioRecord = null
            try {
                record.stop()
            } catch (e: Throwable) {
                // 没开始录 / 已经停了都会抛，忽略
            }
            try {
                record.release()
            } catch (e: Throwable) {
                Log.w(TAG, "AudioRecord.release 异常: ${e.message}")
            }
        }
    }

    // ── 录音+识别循环 ────────────────────────────────────

    /**
     * 核心循环: 读 PCM → 转 Float → 喂 recognizer → decode → 更新 partialText
     *
     * 端点检测: isEndpoint() 返回 true 时表示一句话说完, 累积到 finalText
     */
    private suspend fun recordLoop(session: Long) {
        val shortBuffer = ShortArray(CHUNK_SAMPLES)
        val startTime = System.currentTimeMillis()
        // 本循环只读自己这一支：中途被换代也不会误读新一轮的 AudioRecord
        val record = audioRecord ?: return

        try {
            // 新一轮开录必须先把 recognizer 复位：上一轮收尾时调过 inputFinished()，
            // 带着那份状态继续 acceptSamples 会解不出东西。放在录音协程里而不是主线程，
            // 并且和收尾解码共用 nativeLock —— 否则又会变成两线程并发进 native。
            synchronized(nativeLock) {
                if (sessionId != session) return
                recognizer?.reset(recreate = false)
            }

            while (sessionId == session && _state.value == AsrState.Recording) {
                // 超时保护
                if (System.currentTimeMillis() - startTime > MAX_RECORD_MS) {
                    Log.w(TAG, "录音超时 ${MAX_RECORD_MS}ms, 自动停止")
                    stopListening()
                    return
                }

                val read = try {
                    record.read(shortBuffer, 0, CHUNK_SAMPLES)
                } catch (e: Throwable) {
                    Log.e(TAG, "AudioRecord.read 异常", e)
                    -1
                }

                if (read <= 0) {
                    // 点「完成」/ 取消时 stop() 会让 read 立刻返回 0 或错误码，那是正常收尾。
                    // 这里若再写一次 state，就会把 Processing 覆盖成 Error，收尾解码拿不到结果，
                    // 用户看到的就是「点了完成，输入框里的字没被最终结果替换」。
                    if (sessionId != session || _state.value != AsrState.Recording) {
                        Log.d(TAG, "AudioRecord.read 返回 $read, 会话已结束")
                        return
                    }
                    Log.w(TAG, "AudioRecord.read 返回 $read, 停止")
                    _state.value = AsrState.Error("录音读取失败")
                    return
                }

                // 计算音量 (RMS)
                var sum = 0L
                for (i in 0 until read) {
                    sum += shortBuffer[i].toLong() * shortBuffer[i]
                }
                val rms = kotlin.math.sqrt(sum.toDouble() / read).toFloat()
                if (sessionId == session) {
                    _amplitude.value = (rms / 32768f).coerceIn(0f, 1f)
                }

                // short[] → FloatArray (-1.0~1.0)
                val samples = FloatArray(read) { i ->
                    shortBuffer[i] / 32768.0f
                }

                try {
                    // native 不是线程安全的：和收尾解码、取消后的 reset 串行
                    synchronized(nativeLock) {
                        if (sessionId != session) return

                        // 喂给 recognizer
                        recognizer?.acceptSamples(samples)

                        // 解码所有可解码的
                        while (recognizer?.isReady() == true) {
                            recognizer?.decode()
                        }

                        // 更新 partial 文本(已确认句 + 当前句), UI 依靠它做流式上屏
                        val text = recognizer?.text ?: ""
                        val combined = combineText(text)
                        if (combined != _partialText.value) {
                            _partialText.value = combined
                        }

                        // 端点检测: 一句话说完
                        if (recognizer?.isEndpoint() == true) {
                            // 先把当前这句累积进已确认文本, 再 reset 开始下一句。
                            // 顺序不能反: reset 之后 recognizer.text 会变空, 那这句就丢了。
                            if (text.isNotBlank()) {
                                committedText = combineText(text)
                                if (committedText != _partialText.value) {
                                    _partialText.value = committedText
                                }
                            }
                            // 继续录下一句, 由用户手动停或超时停
                            recognizer?.reset(recreate = false)
                        }
                    }
                } catch (e: Throwable) {
                    Log.w(TAG, "识别循环异常: ${e.message}")
                }
            }
        } finally {
            // AudioRecord 由录音循环自己释放：此时 read 一定已经退出，没有跨线程 release 的竞态。
            // 换代之后 audioRecord 已经不是这一支了，别误放别人的。
            if (audioRecord === record) {
                releaseAudioRecord()
            }
        }
    }
}

/**
 * ASR 引擎状态
 */
sealed class AsrState {
    data object Idle : AsrState()
    data object Recording : AsrState()
    data object Processing : AsrState()
    data class Error(val message: String) : AsrState()
    data class Result(val text: String) : AsrState()
}
