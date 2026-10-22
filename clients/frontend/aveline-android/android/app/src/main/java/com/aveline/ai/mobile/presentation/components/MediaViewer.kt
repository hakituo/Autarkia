package com.aveline.ai.mobile.presentation.components

import android.content.Context
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import coil.compose.AsyncImagePainter
import coil.compose.SubcomposeAsyncImage
import coil.compose.SubcomposeAsyncImageContent
import com.aveline.ai.mobile.data.local.preferences.AppPreferences
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.utils.CoilImageModel
import com.aveline.ai.mobile.utils.MediaUrlResolver
import com.aveline.ai.mobile.utils.media.MediaZoomMath
import dagger.hilt.android.EntryPointAccessors

/**
 * 点击媒体后要全屏预览的内容。
 *
 * @param url 后端下发的**原始**地址（相对路径 / data URI 都行），由查看器自己补全后端地址；
 *   不要在调用方先解析，否则换后端后缓存键会跟着变。
 * @param isVideo 视频/动图走全屏播放，其余走缩放看图
 */
data class MediaPreview(
    val url: String,
    val isVideo: Boolean = false
)

/**
 * 全屏媒体查看器（点表情包 / 图片 / 视频放大看）。
 *
 * 行为对齐 QQ / 微信：
 * - 黑底铺满、单击（未放大时）/ 关闭按钮 / 返回键退出；
 * - 双指捏合缩放（1x–5x），放大后可拖动，边界按 [MediaZoomMath] 夹紧；
 * - 双击在图内缩放 2.5x（再双击还原），点击位置会被拉到屏幕中心；
 * - 视频/动图全屏播放，带控制条与原声。
 *
 * 用独立 [Dialog] 承载而不是在列表里叠一层：查看器不需要跟着消息列表滚动/重组，
 * 也不会被 LazyColumn 的裁剪影响。
 */
@Composable
fun MediaViewer(
    preview: MediaPreview,
    onDismiss: () -> Unit
) {
    Dialog(
        onDismissRequest = onDismiss,
        // 铺满窗口；默认的 decorFitsSystemWindows 保留，关闭按钮不会被状态栏/挖孔挡住
        properties = DialogProperties(usePlatformDefaultWidth = false)
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(Color.Black)
        ) {
            if (preview.isVideo) {
                FullscreenVideo(url = preview.url)
            } else {
                ZoomableMediaImage(url = preview.url, onTapWhenNotZoomed = onDismiss)
            }

            IconButton(
                onClick = onDismiss,
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .padding(12.dp)
            ) {
                Icon(
                    imageVector = Icons.Filled.Close,
                    contentDescription = "关闭",
                    tint = Color.White
                )
            }
        }
    }
}

/** 视频/动图全屏播放：复用消息气泡里的播放器，静音关掉、控制条打开。 */
@Composable
private fun FullscreenVideo(url: String) {
    BoxWithConstraints(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.Center
    ) {
        VideoMessageBubble(
            videoUrl = url,
            muted = false,
            showController = true,
            maxWidth = maxWidth,
            maxHeight = maxHeight
        )
    }
}

/**
 * 可缩放的全屏图片。
 *
 * @param onTapWhenNotZoomed 未放大时单击的回调（用来退出全屏）；放大状态下单击不退出，
 *   避免用户想看细节时误触关闭
 */
@OptIn(coil.annotation.ExperimentalCoilApi::class)
@Composable
private fun ZoomableMediaImage(
    url: String,
    onTapWhenNotZoomed: () -> Unit
) {
    val context = LocalContext.current
    val appPreferences = remember { context.applicationContext.viewerAppPreferences() }
    // 与气泡一致：生效后端作为重组依赖，切换通道后重新解析地址
    val activeBackend by appPreferences.effectiveBackendUrlFlow.collectAsStateWithLifecycle()
    val resolvedUrl = remember(url, activeBackend) {
        MediaUrlResolver.resolve(activeBackend, url)
    }
    // 本地优先：历史媒体缓存过就直接读磁盘，换后端后仍能打开
    val localFile = rememberLocalMediaFile(url, resolvedUrl)
    val model = remember(resolvedUrl, localFile) {
        localFile?.let { CoilImageModel.buildFile(context, it) }
            ?: CoilImageModel.build(context, resolvedUrl)
    }

    var scale by remember(url) { mutableFloatStateOf(MediaZoomMath.MIN_SCALE) }
    var offset by remember(url) { mutableStateOf(Offset.Zero) }
    var containerSize by remember(url) { mutableStateOf(IntSize.Zero) }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .onSizeChanged { containerSize = it },
        contentAlignment = Alignment.Center
    ) {
        SubcomposeAsyncImage(
            model = model,
            contentDescription = "全屏图片",
            contentScale = ContentScale.Fit,
            modifier = Modifier
                .fillMaxSize()
                .graphicsLayer {
                    scaleX = scale
                    scaleY = scale
                    translationX = offset.x
                    translationY = offset.y
                }
                .pointerInput(containerSize) {
                    detectTransformGestures { _, pan, zoom, _ ->
                        val nextScale = (scale * zoom)
                            .coerceIn(MediaZoomMath.MIN_SCALE, MediaZoomMath.MAX_SCALE)
                        scale = nextScale
                        offset = if (nextScale > MediaZoomMath.MIN_SCALE) {
                            Offset(
                                x = MediaZoomMath.clampTranslation(
                                    value = offset.x + pan.x,
                                    scale = nextScale,
                                    containerPx = containerSize.width
                                ),
                                y = MediaZoomMath.clampTranslation(
                                    value = offset.y + pan.y,
                                    scale = nextScale,
                                    containerPx = containerSize.height
                                )
                            )
                        } else {
                            Offset.Zero
                        }
                    }
                }
                .pointerInput(containerSize) {
                    detectTapGestures(
                        onTap = {
                            if (scale <= MediaZoomMath.MIN_SCALE) onTapWhenNotZoomed()
                        },
                        onDoubleTap = { tap ->
                            if (scale > MediaZoomMath.MIN_SCALE) {
                                scale = MediaZoomMath.MIN_SCALE
                                offset = Offset.Zero
                            } else {
                                val target = MediaZoomMath.DOUBLE_TAP_SCALE
                                scale = target
                                offset = Offset(
                                    x = MediaZoomMath.translationForDoubleTap(
                                        tapX = tap.x,
                                        containerPx = containerSize.width,
                                        scale = target
                                    ),
                                    y = MediaZoomMath.translationForDoubleTap(
                                        tapX = tap.y,
                                        containerPx = containerSize.height,
                                        scale = target
                                    )
                                )
                            }
                        }
                    )
                }
        ) {
            when (painter.state) {
                is AsyncImagePainter.State.Loading -> CircularProgressIndicator(
                    modifier = Modifier.size(28.dp),
                    color = Color.White,
                    strokeWidth = 2.dp
                )
                is AsyncImagePainter.State.Error -> Text(
                    text = "图片加载失败",
                    color = TextSecondary
                )
                is AsyncImagePainter.State.Success -> SubcomposeAsyncImageContent()
                else -> Unit
            }
        }
    }
}

private fun Context.viewerAppPreferences(): AppPreferences =
    EntryPointAccessors.fromApplication(this, AppPreferencesEntryPoint::class.java)
        .appPreferences()
