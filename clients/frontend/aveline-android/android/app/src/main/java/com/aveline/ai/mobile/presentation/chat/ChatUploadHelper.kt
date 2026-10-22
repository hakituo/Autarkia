package com.aveline.ai.mobile.presentation.chat

import android.net.Uri
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.domain.models.ChatAttachment
import com.aveline.ai.mobile.domain.models.ChatAttachmentKind
import com.aveline.ai.mobile.domain.repository.ToolsRepository
import com.aveline.ai.mobile.services.FileUploadManager
import com.aveline.ai.mobile.services.UploadKind
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

private const val MAX_CHAT_ATTACHMENTS = 10

/**
 * 文件上传助手
 *
 * 负责文件/图片/视频的上传、状态观察和媒体消息发送，
 * 将上传相关逻辑从 ViewModel 中分离。
 *
 * 图片/文档发送流程：
 * 1. 多选 → 逐个上传 → 附件暂存在 ChatUiState.pendingAttachments（可逐项移除、有数量上限）；
 * 2. 点发送 → 组装 `[图片: url]` / `[附件: url]` 标记，不在 Android 端提前调用视觉模型；
 * 3. 后端把图片标记还原成标准 OpenAI `image_url` 多模态内容（统一视觉路由决定直看原图
 *    还是走 VL 中转），文档标记则只读取白名单目录内文档的可读文本作为不可信资料注入。
 *
 * 视频发送流程：
 * 1. 选视频 → 上传 → 地址暂存在 ChatUiState.pendingVideoUrl（待发送）；
 * 2. 点发送 → 直接以 `[视频: url]` 作为用户消息文本发出（后端暂无视频理解能力，
 *    不做视觉识别），本地气泡渲染播放器 + 用户文案。
 *
 * @param scope             ViewModel 的协程作用域
 * @param uiState           UI 状态流
 * @param fileUploadManager 文件上传管理器
 * @param appPreferences    应用偏好设置（提供后端地址和 token）
 * @param toolsRepository   保留现有构造注入兼容；图片发送不再通过它预先调用视觉接口
 * @param sendMediaMessage  把组装好的文本交给发送流程（HTTP SSE 流式回复）
 */
class ChatUploadHelper(
    private val scope: CoroutineScope,
    private val uiState: MutableStateFlow<ChatUiState>,
    private val fileUploadManager: FileUploadManager,
    private val appPreferences: AppPreferences,
    toolsRepository: ToolsRepository,
    private val sendMediaMessage: (
        text: String,
        imageUrl: String?,
        videoUrl: String?,
        displayText: String,
        attachments: List<ChatAttachment>
    ) -> Unit
) {
    /**
     * 初始化上传管理器：设置后端地址和访问令牌
     *
     * 地址取裁决结果（effectiveBackendUrl），上传才会跟着聊天一起在局域网/公网之间切换。
     */
    fun init() {
        fileUploadManager.setBackendUrl(appPreferences.effectiveBackendUrl)
        fileUploadManager.setAccessToken(appPreferences.accessToken)
    }

    /**
     * 观察上传状态流，同步到 UI 状态
     */
    fun observeUploadState() {
        scope.launch {
            // 只同步上传进度/结果；待发送图片由 uploadFile 在"确认是图片"时写入，
            // 避免上传文档等非图片文件也被塞进图片预览条
            fileUploadManager.uploadState.collect { state ->
                uiState.update { it.copy(uploadState = state) }
            }
        }
    }

    /** 上传一个或多个图片/文档，按顺序执行以避免共享进度状态相互覆盖。 */
    fun uploadFile(uri: Uri, kind: UploadKind) = uploadFiles(listOf(uri), kind)

    fun uploadFiles(uris: List<Uri>, kind: UploadKind) {
        if (uris.isEmpty()) return
        scope.launch {
            val current = uiState.value.pendingAttachments
            val remaining = (MAX_CHAT_ATTACHMENTS - current.size).coerceAtLeast(0)
            if (remaining == 0) {
                uiState.update { it.copy(error = "一条消息最多附加 $MAX_CHAT_ATTACHMENTS 个文件") }
                return@launch
            }
            val acceptedUris = uris.take(remaining)
            val uploaded = mutableListOf<ChatAttachment>()
            var lastError: String? = null

            for (uri in acceptedUris) {
                val fileInfo = fileUploadManager.getFileInfo(uri)
                if (fileInfo == null) {
                    lastError = "无法读取文件信息"
                    continue
                }
                if (!fileUploadManager.validateFileSize(fileInfo.size, kind)) {
                    val limitMB = maxSizeBytes(kind) / (1024 * 1024)
                    lastError = "${fileInfo.name} 超过大小限制（最大 ${limitMB}MB）"
                    continue
                }
                val result = fileUploadManager.uploadFile(uri, kind)
                if (!result.success || result.fileUrl.isNullOrBlank()) {
                    lastError = result.error ?: "${fileInfo.name} 上传失败"
                    continue
                }
                if (kind == UploadKind.VIDEO) {
                    // 视频仍走单条待发通道：后端暂无视频理解能力，只按地址原样发。
                    uiState.update { state ->
                        state.copy(pendingVideoUrl = result.fileUrl, error = null)
                    }
                } else {
                    uploaded += ChatAttachment(
                        kind = if (kind == UploadKind.IMAGE) {
                            ChatAttachmentKind.IMAGE
                        } else {
                            ChatAttachmentKind.DOCUMENT
                        },
                        url = result.fileUrl,
                        name = fileInfo.name,
                        mimeType = fileInfo.mimeType
                    )
                }
            }

            uiState.update { state ->
                val available = (MAX_CHAT_ATTACHMENTS - state.pendingAttachments.size).coerceAtLeast(0)
                state.copy(
                    pendingAttachments = state.pendingAttachments + uploaded.take(available),
                    error = lastError ?: if (acceptedUris.size < uris.size) {
                        "一条消息最多附加 $MAX_CHAT_ATTACHMENTS 个文件"
                    } else null
                )
            }
        }
    }

    /** 上传图片（[uploadFiles] 的便捷封装）。 */
    fun uploadImage(uri: Uri) = uploadFile(uri, UploadKind.IMAGE)

    fun uploadImages(uris: List<Uri>) = uploadFiles(uris, UploadKind.IMAGE)

    fun uploadDocuments(uris: List<Uri>) = uploadFiles(uris, UploadKind.DOCUMENT)

    /** 上传视频（[uploadFile] 的便捷封装） */
    fun uploadVideo(uri: Uri) = uploadFile(uri, UploadKind.VIDEO)

    /** 重置上传状态 */
    fun resetUploadState() {
        fileUploadManager.resetState()
    }

    /**
     * 发送待发送的图片消息。
     *
     * 这里只发送附件标记，不再先做一次视觉描述。这样原生多模态主模型能直接看到原图；
     * 后端统一视觉路由只会在主模型为纯文本时调用 VL 中转。
     *
     * @param imageUrl 上传得到的图片地址（相对路径，如 /output/image/uploads/x.jpg）
     * @param caption  附带文字（可选）
     */
    fun sendImageMessage(imageUrl: String, caption: String = "") {
        val url = imageUrl.trim()
        if (url.isEmpty()) return
        val attachment = ChatAttachment(
            kind = ChatAttachmentKind.IMAGE,
            url = url,
            name = url.substringAfterLast('/').ifBlank { "image" },
            mimeType = "image/*"
        )
        sendAttachments(listOf(attachment), caption)
    }

    fun sendAttachments(attachments: List<ChatAttachment>, caption: String = "") {
        val valid = attachments.filter { it.url.isNotBlank() }
        if (valid.isEmpty()) return
        val firstImage = valid.firstOrNull { it.kind == ChatAttachmentKind.IMAGE }?.url
        val sendText = MediaSendText.buildAttachments(valid, caption)
        uiState.update {
            it.copy(
                lastUploadedImageUrl = null,
                pendingAttachments = emptyList(),
                isAnalyzingImage = false,
                isTyping = true,
                showTypingIndicator = true,
                error = null
            )
        }
        sendMediaMessage(sendText, firstImage, null, caption, valid)
    }

    /**
     * 发送待发送的视频消息。
     *
     * 后端 chat 通道只收文本且没有视频理解能力，所以这里不做视觉识别，
     * 直接把地址放进文本（与图片附件标记口径一致），
     * 本地气泡按 videoUrl 渲染播放器。
     *
     * @param videoUrl 上传得到的视频地址（相对路径，如 /output/video/uploads/x.mp4）
     * @param caption  附带文字（可选）
     */
    fun sendVideoMessage(videoUrl: String, caption: String = "") {
        val url = videoUrl.trim()
        if (url.isEmpty()) return
        uiState.update {
            it.copy(
                pendingVideoUrl = null,
                isTyping = true,
                showTypingIndicator = true,
                error = null
            )
        }
        sendMediaMessage(VideoMessageText.build(url, caption), null, url, caption, emptyList())
    }

    /** 从待发送队列移除一项附件。 */
    fun removePendingAttachment(index: Int) {
        uiState.update { state ->
            if (index < 0) {
                state.copy(lastUploadedImageUrl = null)
            } else {
                state.copy(
                    pendingAttachments = state.pendingAttachments.filterIndexed { i, _ -> i != index }
                )
            }
        }
    }

    /** 取消所有待发送图片/文档。 */
    fun clearPendingAttachments() {
        uiState.update { it.copy(pendingAttachments = emptyList(), lastUploadedImageUrl = null) }
    }

    /** 兼容旧单图调用：取消当前所有待发送图片。 */
    fun clearPendingImage() = clearPendingAttachments()

    /** 取消待发送的视频（选完视频又不想发了）。 */
    fun clearPendingVideo() {
        uiState.update { it.copy(pendingVideoUrl = null) }
    }

    /** 判断 MIME 类型是否为支持的图片类型 */
    fun isSupportedImageType(mimeType: String): Boolean =
        fileUploadManager.isSupportedImageType(mimeType)

    /** 判断 MIME 类型是否为支持的视频类型 */
    fun isSupportedVideoType(mimeType: String): Boolean =
        fileUploadManager.isSupportedVideoType(mimeType)

    /** 获取文件信息(现为 suspend 内部 IO,保持对外接口一致) */
    suspend fun getFileInfo(uri: Uri) = fileUploadManager.getFileInfo(uri)

    private fun maxSizeBytes(kind: UploadKind): Long = when (kind) {
        UploadKind.IMAGE -> FileUploadManager.MAX_IMAGE_SIZE
        UploadKind.VIDEO -> FileUploadManager.MAX_VIDEO_SIZE
        UploadKind.DOCUMENT -> FileUploadManager.MAX_FILE_SIZE
    }
}
