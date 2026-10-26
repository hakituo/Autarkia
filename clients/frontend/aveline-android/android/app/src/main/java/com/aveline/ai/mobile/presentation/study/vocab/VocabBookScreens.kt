package com.aveline.ai.mobile.presentation.study.vocab

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.components.controls.AvelineButton
import com.aveline.ai.mobile.presentation.components.controls.AvelineButtonVariant
import com.aveline.ai.mobile.presentation.study.VocabBookProgress
import com.aveline.ai.mobile.presentation.study.VocabUiState
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.Background
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 词书列表：纯列表，不做渐变头部和图标块。
 *
 * 当前这本加粗、显示进度并带勾；其余只有书名和箭头。
 */
@Composable
fun VocabBookListScreen(
    uiState: VocabUiState,
    onBack: () -> Unit,
    onSelectBook: (String) -> Unit
) {
    val books = uiState.vocabBooks
    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
    ) {
        VocabScreenHeader(
            title = "选择词书",
            subtitle = if (books.isEmpty()) "暂无可用词书" else "共 ${books.size} 本",
            onBack = onBack
        )
        Spacer(modifier = Modifier.height(24.dp))
        if (books.isEmpty()) {
            Box(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .padding(24.dp),
                contentAlignment = Alignment.Center
            ) {
                Text(text = "暂无可用词书", fontSize = 15.sp, color = TextTertiary)
            }
        } else {
            LazyColumn(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth(),
                contentPadding = PaddingValues(start = 20.dp, end = 20.dp, bottom = 24.dp)
            ) {
                items(books, key = { it }) { book ->
                    VocabDivider(color = Color.White.copy(alpha = 0.06f))
                    BookRow(
                        name = bookBaseName(book).ifBlank { bookDisplayName(book) },
                        isCurrent = book == uiState.currentBook,
                        // 刚切换词书时进度还是上一本的，宁可不显示也不报错数字。
                        progress = uiState.bookProgress?.takeIf {
                            bookBaseName(it.currentBook) == bookBaseName(book)
                        },
                        onClick = { onSelectBook(book) }
                    )
                }
            }
        }
    }
}

@Composable
private fun BookRow(
    name: String,
    isCurrent: Boolean,
    progress: VocabBookProgress?,
    onClick: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .defaultMinSize(minHeight = 60.dp)
            .clickable(onClick = onClick)
            .padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        if (isCurrent) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = name,
                    fontSize = 16.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = TextPrimary,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Spacer(modifier = Modifier.height(3.dp))
                Text(
                    text = currentSubtitle(progress),
                    fontSize = 12.5.sp,
                    color = Accent,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
            Spacer(modifier = Modifier.width(12.dp))
            Box(
                modifier = Modifier
                    .size(22.dp)
                    .clip(CircleShape)
                    .background(Accent),
                contentAlignment = Alignment.Center
            ) {
                Icon(
                    imageVector = Icons.Default.Check,
                    contentDescription = "使用中",
                    tint = Background,
                    modifier = Modifier.size(14.dp)
                )
            }
        } else {
            Text(
                text = name,
                fontSize = 16.sp,
                color = TextPrimary,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f)
            )
            Spacer(modifier = Modifier.width(12.dp))
            Icon(
                imageVector = Icons.Default.ChevronRight,
                contentDescription = null,
                tint = TextTertiary,
                modifier = Modifier.size(20.dp)
            )
        }
    }
}

private fun currentSubtitle(progress: VocabBookProgress?): String {
    if (progress == null || progress.totalWords <= 0) return "使用中"
    return "使用中 · 已学 ${formatCount(progress.learnedWords)} / ${formatCount(progress.totalWords)}"
}

/**
 * 词书详情：两列细线列表 + 底部固定按钮。
 *
 * 后端只能查看「当前词书」的单词，因此进入本页前词书已经切换；
 * 底部按钮相应改为直接开背，而不是再切一次。
 */
@Composable
fun VocabBookDetailScreen(
    uiState: VocabUiState,
    onBack: () -> Unit,
    onStartNewWords: () -> Unit,
    onLoadBookWords: () -> Unit = {}
) {
    LaunchedEffect(Unit) { onLoadBookWords() }
    val total = if (uiState.bookTotal > 0) uiState.bookTotal else uiState.bookWords.size
    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
    ) {
        VocabScreenHeader(
            title = bookBaseName(uiState.currentBook).ifBlank { "词书" },
            subtitle = "共 ${formatCount(total)} 个单词",
            onBack = onBack
        )
        Spacer(modifier = Modifier.height(20.dp))
        if (uiState.bookWords.isEmpty()) {
            Box(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .padding(24.dp),
                contentAlignment = Alignment.Center
            ) {
                Text(text = "该词书暂无单词数据", fontSize = 15.sp, color = TextTertiary)
            }
        } else {
            LazyColumn(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth(),
                contentPadding = PaddingValues(start = 20.dp, end = 20.dp, bottom = 16.dp)
            ) {
                itemsIndexed(uiState.bookWords) { _, item ->
                    VocabDivider(color = Color.White.copy(alpha = 0.06f))
                    Row(modifier = Modifier.fillMaxWidth().padding(vertical = 12.dp)) {
                        Text(
                            text = item.word,
                            fontSize = 15.5.sp,
                            fontWeight = FontWeight.Medium,
                            color = TextPrimary,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier
                                .width(120.dp)
                                .alignByBaseline()
                        )
                        Spacer(modifier = Modifier.width(12.dp))
                        Text(
                            text = item.translation.ifBlank { "—" },
                            fontSize = 14.sp,
                            color = TextSecondary,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier
                                .weight(1f)
                                .alignByBaseline()
                        )
                    }
                }
            }
        }
        Box(
            modifier = Modifier
                .navigationBarsPadding()
                .fillMaxWidth()
                .padding(start = 20.dp, end = 20.dp, top = 14.dp, bottom = 24.dp)
        ) {
            AvelineButton(
                text = "开始背新词",
                onClick = onStartNewWords,
                modifier = Modifier.fillMaxWidth(),
                variant = AvelineButtonVariant.Primary,
                enabled = uiState.bookWords.isNotEmpty()
            )
        }
    }
}
