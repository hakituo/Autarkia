package com.aveline.ai.mobile.presentation.chat

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember

/**
 * 聊天页的文件/媒体选择入口集合。
 *
 * 图片、通用文件、录音权限三个 launcher 原本散落在 ChatScreen 顶部，
 * 聚合到这里后 ChatScreen 只持有"选完之后干什么"的回调。
 * 底部输入栏只保留麦克风与"+"，因此不再提供选视频入口。
 */
data class ChatMediaPickers(
    /** 打开系统文件选择器，返回本次选中的文档列表。 */
    val pickDocuments: () -> Unit,
    /** 打开相册多选图片，返回本次选中的图片列表。 */
    val pickImages: () -> Unit,
    /** 申请录音权限。 */
    val requestRecordAudioPermission: () -> Unit
)

/**
 * 创建聊天页的媒体选择入口。
 *
 * @param onDocumentsPicked 选中的一个或多个支持的文档
 * @param onImagesPicked 选中的一张或多张图片
 * @param onRecordPermissionResult 录音权限结果：true 已授权，false 被拒绝
 */
@Composable
fun rememberChatMediaPickers(
    onDocumentsPicked: (List<Uri>) -> Unit,
    onImagesPicked: (List<Uri>) -> Unit,
    onRecordPermissionResult: (Boolean) -> Unit
): ChatMediaPickers {
    val documentLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenMultipleDocuments()
    ) { uris: List<Uri> -> if (uris.isNotEmpty()) onDocumentsPicked(uris) }

    val imageLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.GetMultipleContents()
    ) { uris: List<Uri> -> if (uris.isNotEmpty()) onImagesPicked(uris) }

    val recordAudioLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission()
    ) { granted: Boolean -> onRecordPermissionResult(granted) }

    return remember(
        documentLauncher,
        imageLauncher,
        recordAudioLauncher
    ) {
        ChatMediaPickers(
            pickDocuments = {
                documentLauncher.launch(
                    arrayOf(
                        "application/pdf",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        "text/plain",
                        "text/csv",
                        "text/markdown",
                        "application/json"
                    )
                )
            },
            pickImages = { imageLauncher.launch("image/*") },
            requestRecordAudioPermission = {
                recordAudioLauncher.launch(android.Manifest.permission.RECORD_AUDIO)
            }
        )
    }
}
