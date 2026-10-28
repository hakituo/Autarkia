package com.aveline.ai.mobile.presentation.study

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.Background
import com.aveline.ai.mobile.presentation.theme.TextBody
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 笔记阅读页（全屏覆盖）。
 *
 * 第三轮设计稿：面包屑放在返回键旁边，标题 26sp，正文 16sp / 1.8 行高；
 * 公式块去掉灰底，改成上下各一条细线。
 *
 * 阅读页挂在 [StudyScreenV2] 的根层而不是笔记列表里：列表在分页器内、左右各有 16dp 内边距，
 * 阅读页留在里面会被切窄，正文贴不到屏幕边。
 */
@Composable
internal fun NoteReaderScreen(
    uiState: StudyNotesUiState,
    onClose: () -> Unit
) {
    BackHandler(onBack = onClose)

    val content = uiState.currentNoteContent
    val path = content?.path ?: uiState.selectedNotePath
    // 打开笔记到内容返回之间会有一帧「null 且未 loading」，同样按加载态处理，避免白屏闪一下。
    val isLoading = content == null && (uiState.isLoading || uiState.error == null)
    val updatedTs = content?.updatedTs?.takeIf { it > 0L }
        ?: uiState.libraryNotes.firstOrNull { it.relPath == path }?.updatedTs
        ?: 0L
    val title = (content?.filename ?: path?.substringAfterLast('/'))
        .orEmpty()
        .removeSuffix(".md")
        .ifBlank { "笔记" }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Background)
            .statusBarsPadding()
            .navigationBarsPadding()
    ) {
        Column(modifier = Modifier.fillMaxSize()) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(56.dp)
                    .padding(start = 4.dp, end = 16.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                IconButton(onClick = onClose) {
                    Icon(
                        imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                        contentDescription = "返回笔记",
                        tint = TextPrimary,
                        modifier = Modifier.size(22.dp)
                    )
                }
                Text(
                    text = noteBreadcrumb(path),
                    fontSize = 13.5f.sp,
                    color = TextTertiary,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f)
                )
            }

            when {
                isLoading -> {
                    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        CircularProgressIndicator(color = Accent)
                    }
                }

                content == null && uiState.error != null -> {
                    val message = uiState.error.orEmpty()
                    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        Text(
                            text = message,
                            fontSize = 14.sp,
                            color = MaterialTheme.colorScheme.error,
                            modifier = Modifier.padding(24.dp)
                        )
                    }
                }

                content != null -> {
                    LazyColumn(
                        modifier = Modifier.fillMaxSize(),
                        contentPadding = PaddingValues(
                            start = 24.dp,
                            end = 24.dp,
                            top = 12.dp,
                            bottom = 32.dp
                        )
                    ) {
                        item {
                            Column(verticalArrangement = Arrangement.spacedBy(18.dp)) {
                                Text(
                                    text = title,
                                    fontSize = 26.sp,
                                    lineHeight = 34.sp,
                                    fontWeight = FontWeight.SemiBold,
                                    letterSpacing = (-0.3f).sp,
                                    color = TextPrimary
                                )
                                if (updatedTs > 0L) {
                                    Text(
                                        text = "${formatNoteDate(updatedTs)}更新",
                                        fontSize = 12.5f.sp,
                                        color = TextTertiary
                                    )
                                }
                                NotesMarkdownRenderer(
                                    text = content.content,
                                    bodyStyle = NoteBodyStyle,
                                    documentStyle = true
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

/** `物理/电磁学/电磁感应.md` → `物理 / 电磁学`；顶层散文件显示「学习库」。 */
private fun noteBreadcrumb(path: String?): String {
    val dir = path?.substringBeforeLast('/', "")?.trim('/').orEmpty()
    return if (dir.isBlank()) {
        "学习库"
    } else {
        dir.split('/').filter { it.isNotBlank() }.joinToString(" / ")
    }
}

/** 笔记更新时间：`10月24日`。 */
private fun formatNoteDate(epochMillis: Long): String = runCatching {
    SimpleDateFormat("M月d日", Locale.CHINA).format(Date(epochMillis))
}.getOrDefault("")

/** 阅读正文：16sp / 1.8 行高。 */
private val NoteBodyStyle = TextStyle(
    fontSize = 16.sp,
    lineHeight = 28.8f.sp,
    color = TextBody
)
