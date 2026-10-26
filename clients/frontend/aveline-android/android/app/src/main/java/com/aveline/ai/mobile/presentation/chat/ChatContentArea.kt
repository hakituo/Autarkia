package com.aveline.ai.mobile.presentation.chat

import androidx.compose.foundation.layout.Column
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import com.aveline.ai.mobile.presentation.components.HorizontalContentGestureState
import com.aveline.ai.mobile.presentation.components.MediaPreview
import com.aveline.ai.mobile.presentation.components.MediaViewer

/**
 * 聊天页内容区（从 ChatScreen.kt 拆出）：双角色对话折叠区 + 消息列表 + 消息动作。
 *
 * 左滑手势的参数仍在 ChatScreen 组装（那里才有屏幕尺寸与面板状态），
 * 通过 [modifier] 传进来，所以这里不感知手势细节。
 *
 * @param forceFollowLatestRequest 用户主动发送的事件序号（只影响滚动语义）
 * @param imeVisible 软键盘是否可见（由聊天页根层在 imePadding 之外读出后传下来）
 * @param onEditMessage 点某条消息的"编辑"时回调 (messageId, text)，用于打开编辑对话框
 */
@Composable
internal fun ChatContentArea(
    viewModel: ChatViewModel,
    uiState: ChatUiState,
    displayName: String,
    forceFollowLatestRequest: Int,
    imeVisible: Boolean,
    horizontalContentGestureState: HorizontalContentGestureState,
    onEditMessage: (String, String) -> Unit,
    modifier: Modifier = Modifier
) {
    // 点开媒体后的全屏查看：状态放在组装层，消息列表本身保持无状态
    var previewUrl by rememberSaveable { mutableStateOf<String?>(null) }
    var previewIsVideo by rememberSaveable { mutableStateOf(false) }

    Column(modifier = modifier) {
        ChatPeerChatArea(
            messages = uiState.peerChatMessages,
            topic = uiState.peerChatTopic,
            isActive = uiState.isPeerChatActive,
            visible = uiState.showPeerChat,
            onClose = { viewModel.togglePeerChat() }
        )

        ChatMessageList(
            messages = uiState.messages,
            sessionId = uiState.currentSession?.id,
            isLoading = uiState.isLoading,
            loadingState = uiState.loadingState,
            // 传统 IM 体验：消息发出去就只留自己的气泡，不显示"正在等待回复/正在输入"
            // 的占位动画，也不给回复预留位置（空白占位在 ChatMessageList 内部就被过滤掉了）。
            // 她的回复（含延迟回复、主动补发）到了才出现新气泡。
            playingMessageId = uiState.playingMessageId,
            ttsLoadingMessageId = uiState.ttsLoadingMessageId,
            displayName = displayName,
            horizontalContentGestureState = horizontalContentGestureState,
            forceFollowLatestRequest = forceFollowLatestRequest,
            imeVisible = imeVisible,
            hasOlderMessages = uiState.hasOlderMessages,
            onLoadOlderMessages = viewModel::loadOlderMessages,
            onMediaClick = { media ->
                previewUrl = media.url
                previewIsVideo = media.isVideo
            },
            stageDirectionEnabled = uiState.stageDirectionEnabled,
            actions = remember(viewModel) {
                ChatMessageActions(
                    onPlayTTS = viewModel::toggleTTS,
                    onCopy = viewModel::copyMessage,
                    onDelete = viewModel::deleteMessage,
                    onRegenerate = { viewModel.regenerateMessage(it) },
                    onEdit = { id, text -> onEditMessage(id, text) },
                    onSwitchVariant = viewModel::selectMessageVariant
                )
            },
            modifier = Modifier.weight(1f)
        )
    }

    previewUrl?.let { url ->
        MediaViewer(
            preview = MediaPreview(url, isVideo = previewIsVideo),
            onDismiss = { previewUrl = null }
        )
    }
}
