package com.aveline.ai.mobile.presentation.chat.send

import com.aveline.ai.mobile.presentation.chat.ChatSessionController
import com.aveline.ai.mobile.presentation.chat.ChatUiState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.withContext

/**
 * 「这一轮还能不能往界面上写」的统一判据。
 *
 * 发送流水线跑在进程级后台作用域里，聊天页可能早已销毁；同时用户可能已经切到
 * 另一个角色的会话。两个条件任一不满足都不能再写 uiState —— 否则旧页面会拿
 * 别人的消息覆盖当前屏幕（曾经表现为"切角色后先闪一下上一个角色的记录"）。
 *
 * 抽成独立协作者是因为发送预检与流式收尾都要用，原先各自复制过一份判断。
 */
internal class ChatUiWriteGuard(
    private val scope: CoroutineScope,
    private val uiState: MutableStateFlow<ChatUiState>,
    private val sessionController: ChatSessionController
) {

    /** 页面销毁后后台生成继续，但旧 UI 和 TTS 不再接收更新。 */
    fun isScopeActive(): Boolean = scope.coroutineContext[Job]?.isActive == true

    /**
     * 这一轮是否还该往界面上写。
     *
     * `setPendingSwitch` 切角色时会先把 `currentSession` 置空，再等 Room 回填。
     * 原来要求 `currentSession.id == sessionId` 才算命中，这个空窗期里点发送的整段
     * UI 写入（清输入框、气泡上屏、打字指示器）都会被静默跳过 —— 用户看到"点了没反应"。
     * 所以判据是「**明确切走了**才丢弃」：只有已经落到别的 session 上才算过期。
     */
    fun isStillShowing(sessionId: String?): Boolean {
        if (sessionId == null) return true
        val controllerSession = sessionController.conversationSessionId
        if (controllerSession != null && controllerSession != sessionId) return false
        val uiSession = uiState.value.currentSession?.id
        return uiSession == null || uiSession == sessionId
    }

    /** 在主页面上安全执行一次 UI 写入；页面已销毁或会话已切走时整段跳过。 */
    suspend fun withUiIfActive(sessionId: String? = null, block: () -> Unit) {
        if (!isScopeActive()) return
        withContext(Dispatchers.Main.immediate) {
            if (isScopeActive() && isStillShowing(sessionId)) block()
        }
    }
}
