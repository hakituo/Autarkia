package com.aveline.ai.mobile.presentation.chat.send

import android.util.Log
import com.aveline.ai.mobile.data.repository.PersonaLocalMetaRepository
import com.aveline.ai.mobile.domain.models.Message
import com.aveline.ai.mobile.services.foreground.RoleReplyNotifier
import com.aveline.ai.mobile.utils.AppForegroundTracker
import com.aveline.ai.mobile.utils.text.TextSegmenter

/**
 * 回复完成后的未读标记与通知。
 *
 * 与主动关怀（WebSocket proactive_message）表现对齐：
 * - 用户没看到这条回复时，会话列表未读 +1，聊天页左上角小圆点也会亮；
 * - App 在后台时再弹一条 QQ/微信式通知（角色头像 + 昵称作标题 + 正文）。
 */
internal class ReplyOutcomeNotifier(
    private val personaLocalMetaRepository: PersonaLocalMetaRepository,
    private val replyNotifier: RoleReplyNotifier?
) {
    private companion object {
        const val TAG = "ReplyOutcomeNotifier"
    }

    /**
     * 「已读」的判据必须是**这条回复所属角色的聊天页是否正显示在屏幕上**，
     * 不能用整进程前后台：[AppForegroundTracker.isForeground] 为 true 时，
     * 用户可能正停在 A 的聊天页等 B 的回复 —— 进程是前台，但 B 的消息根本看不见。
     * 旧判据把这种情况当成已读直接 return，会话列表徽章和小圆点都不会亮，
     * 表现为「别人回了我消息，一点提示都没有」。
     */
    suspend fun notifyIfNeeded(message: Message, profileFilename: String?) {
        val filename = profileFilename?.takeIf { it.isNotBlank() } ?: return
        val role = RoleReplyNotifier.roleIdFromProfileFilename(filename)
        val seenOnScreen = AppForegroundTracker.isForeground &&
            replyNotifier?.isChatVisibleFor(role, filename) == true
        if (seenOnScreen) return

        runCatching {
            personaLocalMetaRepository.incrementUnread(filename)
        }.onFailure { e ->
            Log.w(TAG, "后台回复未读计数失败: ${e.message}", e)
        }

        val notifier = replyNotifier ?: return
        runCatching {
            notifier.notifyReplyIfBackground(
                RoleReplyNotifier.ReplyNotification(
                    role = role,
                    profileFilename = filename,
                    fallbackTitle = null,
                    body = TextSegmenter.clean(message.text)
                )
            )
        }.onFailure { e ->
            Log.w(TAG, "后台回复通知发布失败: ${e.message}", e)
        }
    }
}
