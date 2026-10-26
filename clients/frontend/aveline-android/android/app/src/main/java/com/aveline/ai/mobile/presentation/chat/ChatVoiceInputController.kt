package com.aveline.ai.mobile.presentation.chat

import com.aveline.ai.mobile.services.VoiceInputManager
import com.aveline.ai.mobile.services.VoiceInputState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * 负责语音输入（录音转文字）的状态观察与控制。
 *
 * 从 ChatViewModel 拆出，职责：
 * - 监听 [VoiceInputManager] 的 state / amplitude / partialText，写入 uiState
 * - 录音控制：开始 / 完成 / 取消
 * - 权限检查
 *
 * 关于「完成」为什么不等最终结果：
 * ASR 停止后还要跑一段收尾解码（native），等它返回会让用户对着空输入框干等。
 * 这里在点「完成」的瞬间就把**已经实时上屏**的中间文本落进输入框，
 * 最终结果回来后再原地替换这一小段（[committedVoiceText]），
 * 既不用等，也不会覆盖用户在这期间自己补的字。
 *
 * @param scope ViewModel 的协程作用域
 * @param uiState UI 状态流，语音输入状态写入此流
 * @param voiceInputManager 底层语音输入管理器
 */
class ChatVoiceInputController(
    private val scope: CoroutineScope,
    private val uiState: MutableStateFlow<ChatUiState>,
    private val voiceInputManager: VoiceInputManager
) {
    /** 上一次「完成」时已经写进输入框的临时文本，最终结果只替换这一段。 */
    private var committedVoiceText: String = ""

    /** 监听语音输入状态：录音状态、振幅、识别中间文本同步到 uiState。 */
    fun observeState() {
        scope.launch {
            voiceInputManager.state.collect { state ->
                if (state is VoiceInputState.Result) {
                    val committed = committedVoiceText
                    committedVoiceText = ""
                    uiState.update {
                        it.copy(
                            inputText = replaceCommittedText(it.inputText, committed, state.text),
                            voiceInputState = VoiceInputState.Idle,
                            isRecording = false,
                            // 最终文本已经落进输入框，清掉流式中间态，避免旧文字残留
                            voicePartialText = ""
                        )
                    }
                    // Result 已消费进输入框，立即把 Singleton 里的状态归零：
                    // VoiceInputManager 是 @Singleton，state 是 StateFlow，
                    // 不归零的话下次进聊天页重新 collect 会把旧识别结果重放回输入框
                    //（表现为：用户删掉的语音文本重新出现）
                    voiceInputManager.reset()
                } else {
                    if (state is VoiceInputState.Error) {
                        // 出错就不会再有 Result 了，别把上一轮的临时文本留给下一次
                        committedVoiceText = ""
                    }
                    uiState.update {
                        it.copy(
                            voiceInputState = state,
                            isRecording = state is VoiceInputState.Recording,
                            voicePartialText = if (state is VoiceInputState.Error) "" else it.voicePartialText
                        )
                    }
                }
            }
        }

        scope.launch {
            voiceInputManager.amplitude.collect { amplitude ->
                uiState.update { it.copy(voiceAmplitude = amplitude) }
            }
        }

        scope.launch {
            voiceInputManager.partialText.collect { text ->
                uiState.update { it.copy(voicePartialText = text) }
            }
        }
    }

    fun startRecording() {
        if (!voiceInputManager.hasRecordAudioPermission()) {
            uiState.update { it.copy(error = "缺少录音权限") }
            return
        }
        committedVoiceText = ""
        uiState.update { it.copy(voicePartialText = "") }
        voiceInputManager.startListening()
    }

    /**
     * 结束本轮录音（「完成」按钮 / 再点一次麦克风）。
     *
     * 先把当前实时文本落进输入框再停引擎：收尾解码要多久都不影响用户看到字。
     */
    fun stopRecording() {
        // 已经收工了就不再往引擎发一次 stop（系统通道会把状态留在 Processing）
        val current = uiState.value
        if (!current.isRecording && current.voiceInputState !is VoiceInputState.Recording) return

        val partial = current.voicePartialText.trim()
        committedVoiceText = partial
        uiState.update {
            it.copy(
                inputText = if (partial.isEmpty()) {
                    it.inputText
                } else {
                    appendVoiceText(it.inputText, partial)
                },
                isRecording = false,
                voicePartialText = ""
            )
        }
        voiceInputManager.stopListening()
    }

    fun cancelRecording() {
        committedVoiceText = ""
        uiState.update {
            it.copy(
                isRecording = false,
                voicePartialText = "",
                voiceInputState = VoiceInputState.Idle
            )
        }
        voiceInputManager.cancel()
    }

    fun hasPermission(): Boolean = voiceInputManager.hasRecordAudioPermission()

    /**
     * 把已实时上屏的文本接在输入框末尾。
     *
     * 中文之间不补空格；只有两边都是西文字符时才补一个，避免 "hello" + "world" 粘成 "helloworld"。
     */
    private fun appendVoiceText(existing: String, spoken: String): String {
        if (existing.isBlank()) return spoken
        val last = existing.last()
        val first = spoken.first()
        val needSpace = last.code < 128 && first.code < 128
        return existing + if (needSpace) " $spoken" else spoken
    }

    /**
     * 用最终识别结果替换「完成」时写进去的那一段。
     *
     * - 最终结果为空：保持原样（用户已经能看到字，不必再抹掉）
     * - 没有临时文本：输入框仍为空时直接填最终结果，否则不碰用户正在写的内容
     * - 输入框仍以临时文本结尾：只替换这一段，前面用户自己打的内容保留
     * - 用户已经改过那段文本：完全不碰
     */
    private fun replaceCommittedText(current: String, committed: String, finalText: String): String {
        val text = finalText.trim()
        return when {
            text.isEmpty() -> current
            committed.isEmpty() -> if (current.isBlank()) text else current
            current.endsWith(committed) -> current.dropLast(committed.length) + text
            else -> current
        }
    }
}
