package com.aveline.ai.mobile.presentation.components

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import com.aveline.ai.mobile.services.media.LocalMediaStore
import dagger.hilt.EntryPoint
import dagger.hilt.InstallIn
import dagger.hilt.android.EntryPointAccessors
import dagger.hilt.components.SingletonComponent
import java.io.File

/** 在 Composable 里拿 [LocalMediaStore] 单例（与 AppPreferencesEntryPoint 同一套做法）。 */
@EntryPoint
@InstallIn(SingletonComponent::class)
interface LocalMediaEntryPoint {
    fun localMediaStore(): LocalMediaStore
}

/**
 * 「本地优先」的媒体模型。
 *
 * 行为：
 * 1. 先同步查本地磁盘，命中直接返回 File —— 换后端后历史图片/视频仍能显示；
 * 2. 未命中时在后台把 [resolvedUrl] 下载到本地，同时组件先用远端地址正常加载，
 *    下载完成后自动切到本地文件（下次进入不再依赖网络）；
 * 3. data URI（后端表情包）key 对内容哈希，未命中时解码落盘、完成后自动切本地文件；
 *    content URI / file URI 不参与落盘，直接返回 null 让调用方走原逻辑。
 *
 * @param rawUrl 后端下发的原始地址（相对路径），用于计算与后端无关的稳定 key
 * @param resolvedUrl 已按当前生效后端补全的绝对地址
 */
@Composable
fun rememberLocalMediaFile(rawUrl: String, resolvedUrl: String): File? {
    val context = LocalContext.current
    val store = remember {
        EntryPointAccessors.fromApplication(
            context.applicationContext,
            LocalMediaEntryPoint::class.java
        ).localMediaStore()
    }
    var file by remember(rawUrl, resolvedUrl) { mutableStateOf(store.lookup(rawUrl)) }

    LaunchedEffect(rawUrl, resolvedUrl) {
        if (file == null && resolvedUrl.isNotBlank()) {
            file = store.cache(rawUrl, resolvedUrl)
        }
    }
    return file
}
