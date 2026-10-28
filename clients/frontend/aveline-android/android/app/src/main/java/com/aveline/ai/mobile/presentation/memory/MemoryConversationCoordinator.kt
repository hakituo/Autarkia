package com.aveline.ai.mobile.presentation.memory

import android.util.Log
import com.aveline.ai.mobile.domain.models.Message
import com.aveline.ai.mobile.domain.repository.ChatRepository
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.launch

/**
 * 「聊天记录」视图的数据源。
 *
 * 本地消息树先上屏，服务端历史随后补进来；这条订阅与记忆列表翻页无关，
 * 单独成一个职责单元，ViewModel 只负责把结果写进 UI 状态。
 */
class MemoryConversationCoordinator(
    private val chatRepository: ChatRepository,
    private val scope: CoroutineScope,
    private val dispatcher: CoroutineDispatcher = Dispatchers.IO
) {

    private companion object {
        const val TAG = "MemoryConversation"
    }

    private var conversationJob: Job? = null
    private var sessionId: String? = null

    /**
     * 切换正在查看的会话。
     *
     * @param onLocalMessages 本地消息树更新时回调（含重新生成产生的平行分支）
     * @param onRemoteMessages 服务端历史到齐时回调；断网时给空列表
     */
    fun setSession(
        sessionId: String?,
        onLocalMessages: (List<Message>) -> Unit,
        onRemoteMessages: (List<Message>) -> Unit
    ) {
        val target = sessionId?.trim().orEmpty().ifBlank { null }
        if (target == this.sessionId) return
        this.sessionId = target
        conversationJob?.cancel()
        conversationJob = null

        if (target == null) {
            onLocalMessages(emptyList())
            onRemoteMessages(emptyList())
            return
        }

        conversationJob = scope.launch(dispatcher) {
            launch {
                chatRepository.observeAllMessages(target)
                    .catch { e -> Log.w(TAG, "聊天记录树订阅失败: ${e.message}") }
                    .collect { messages -> onLocalMessages(messages) }
            }
            val remote = chatRepository.fetchRemoteHistory(target).getOrElse { emptyList() }
            onRemoteMessages(remote)
        }
    }
}
