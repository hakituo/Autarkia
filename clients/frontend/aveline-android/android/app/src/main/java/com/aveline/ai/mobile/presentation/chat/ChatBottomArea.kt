package com.aveline.ai.mobile.presentation.chat

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.union
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.Dp

/**
 * 聊天页底部区域（从 ChatScreen.kt 拆出）：上传/待发/识别提示条 + 输入栏（含原位语音态）+ “+”更多面板。
 *
 * 底部 inset 统一在这一层处理，输入栏与更多面板共享同一份：
 * 输入栏自己不再随“面板是否展开”改内边距，高度恒定，
 * 否则开关面板时输入栏（以及“+”按钮）会额外跳一下。
 *
 * @param morePanelHeight “+”面板高度（由 ChatScreen 按最近一次真实键盘高度算好并带下限）
 * @param resolveImageUrl 把后端返回的相对图片地址解析成可加载 URL
 */
@Composable
internal fun ChatBottomArea(
    uiState: ChatUiState,
    morePanelHeight: Dp,
    showMorePanel: Boolean,
    resolveImageUrl: (String) -> String,
    onTextChange: (String) -> Unit,
    onSend: (String) -> Unit,
    onToggleMore: () -> Unit,
    onVoiceInput: () -> Unit,
    onRemovePendingAttachment: (Int) -> Unit,
    onVoiceFinish: () -> Unit,
    onVoiceCancel: () -> Unit,
    onPickImages: () -> Unit,
    onPickDocuments: () -> Unit
) {
    Column(
        modifier = Modifier.windowInsetsPadding(
            WindowInsets.ime.union(WindowInsets.navigationBars)
        )
    ) {
        UploadProgressIndicator(
            uploadState = uiState.uploadState,
            modifier = Modifier.fillMaxWidth()
        )

        if (uiState.pendingAttachments.isNotEmpty()) {
            PendingAttachmentsBar(
                attachments = uiState.pendingAttachments,
                resolveImageUrl = resolveImageUrl,
                onRemove = onRemovePendingAttachment,
                modifier = Modifier.fillMaxWidth()
            )
        } else {
            uiState.lastUploadedImageUrl?.let { pendingUrl ->
                PendingImageBar(
                    imageUrl = resolveImageUrl(pendingUrl),
                    onCancel = { onRemovePendingAttachment(-1) },
                    modifier = Modifier.fillMaxWidth()
                )
            }
        }

        if (uiState.isAnalyzingImage) {
            ImageAnalyzingBar(modifier = Modifier.fillMaxWidth())
        }

        // 语音态不另挂横幅：录音时输入栏自己原位变成转写面板（见 ChatBottomBar）。
        // 收尾解码期间也不再显示"正在识别"——停止那一刻文本已经落进输入框了。
        ChatBottomBar(
            text = uiState.inputText,
            onTextChange = onTextChange,
            onSend = onSend,
            onMore = onToggleMore,
            onInputFocused = {
                // 输入框 pointer down 已经先处理“更多 -> 键盘”的切换；
                // 这里仅保留接口，不再用 focus 事件抢 showMorePanel 状态。
            },
            onVoiceInput = onVoiceInput,
            isRecording = uiState.isRecording,
            hasPendingAttachment = uiState.lastUploadedImageUrl != null ||
                uiState.pendingAttachments.isNotEmpty() || uiState.pendingVideoUrl != null,
            showMorePanel = showMorePanel,
            voicePartialText = uiState.voicePartialText,
            voiceAmplitude = uiState.voiceAmplitude,
            onVoiceCancel = onVoiceCancel,
            onVoiceFinish = onVoiceFinish
        )

        // 用 expandVertically / shrinkVertically（从底部生长）而不是 slideInVertically：
        // slide 只改绘制位移、不改占位高度，面板一出现布局就瞬间跳满一整个面板的高度，
        // 输入栏被瞬间顶上去、面板却还在下面滑动，看起来就是一卡一卡地上下跳。
        // 让占位高度跟着动画一起长，输入栏才是被平滑推上去的。
        AnimatedVisibility(
            visible = showMorePanel,
            enter = fadeIn(tween(durationMillis = 160)) +
                expandVertically(
                    animationSpec = tween(durationMillis = 220),
                    expandFrom = Alignment.Bottom
                ),
            exit = fadeOut(tween(durationMillis = 120)) +
                shrinkVertically(
                    animationSpec = tween(durationMillis = 180),
                    shrinkTowards = Alignment.Bottom
                )
        ) {
            ChatMorePanel(
                panelHeight = morePanelHeight,
                onPickImages = onPickImages,
                onPickDocuments = onPickDocuments
            )
        }
    }
}
