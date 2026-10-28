package com.aveline.ai.mobile.presentation.study.vocab

import androidx.compose.animation.Crossfade
import androidx.compose.animation.core.tween
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.components.controls.AvelineButton
import com.aveline.ai.mobile.presentation.components.controls.AvelineButtonVariant
import com.aveline.ai.mobile.presentation.study.BookWord
import com.aveline.ai.mobile.presentation.study.VocabBookProgress
import com.aveline.ai.mobile.presentation.study.VocabLaunch
import com.aveline.ai.mobile.presentation.study.VocabUiState
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.Background
import com.aveline.ai.mobile.presentation.theme.Line
import com.aveline.ai.mobile.presentation.theme.MotionDuration
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
    // 只在确实没有数据时补拉：切书时管理器已经在加载新书，这里不再用旧书再拉一次
    LaunchedEffect(uiState.currentBook) {
        if (uiState.bookWords.isEmpty() && !uiState.bookWordsLoading) onLoadBookWords()
    }
    val total = if (uiState.bookTotal > 0) uiState.bookTotal else uiState.bookWords.size
    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
    ) {
        VocabScreenHeader(
            title = bookBaseName(uiState.currentBook).ifBlank { "词书" },
            subtitle = if (uiState.bookWordsLoading && total == 0) {
                "正在加载单词…"
            } else {
                "共 ${formatCount(total)} 个单词"
            },
            onBack = onBack
        )
        Spacer(modifier = Modifier.height(20.dp))
        // 三态：加载中 → 与真实行同高的骨架（列表不跳）；加载完为空 → 提示；有数据 → 列表淡入
        val listState = when {
            uiState.bookWords.isNotEmpty() -> BookWordsState.Ready
            uiState.bookWordsLoading -> BookWordsState.Loading
            else -> BookWordsState.Empty
        }
        Crossfade(
            targetState = listState,
            animationSpec = tween(MotionDuration.Short),
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth(),
            label = "book_words"
        ) { state ->
            when (state) {
                BookWordsState.Loading -> BookWordsSkeleton()
                BookWordsState.Empty -> Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(24.dp),
                    contentAlignment = Alignment.Center
                ) {
                    Text(text = "该词书暂无单词数据", fontSize = 15.sp, color = TextTertiary)
                }
                BookWordsState.Ready -> BookWordsList(words = uiState.bookWords)
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
                enabled = uiState.bookWords.isNotEmpty(),
                loading = uiState.launching == VocabLaunch.NEW_WORDS
            )
        }
    }
}

private enum class BookWordsState { Loading, Empty, Ready }

@Composable
private fun BookWordsList(words: List<BookWord>) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = 20.dp, end = 20.dp, bottom = 16.dp)
    ) {
        items(words) { item ->
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

/** 骨架行：行高与真实单词行一致（12dp 上下内边距 + 一行字），数据回来时列表不跳。 */
@Composable
private fun BookWordsSkeleton() {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 20.dp)
    ) {
        repeat(10) { index ->
            VocabDivider(color = Color.White.copy(alpha = 0.06f))
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(46.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                SkeletonBar(width = (64 + (index * 23) % 48).dp)
                Spacer(modifier = Modifier.width(132.dp - (64 + (index * 23) % 48).dp))
                SkeletonBar(width = (90 + (index * 37) % 80).dp)
            }
        }
    }
}

@Composable
private fun SkeletonBar(width: Dp) {
    Box(
        modifier = Modifier
            .width(width)
            .height(12.dp)
            .clip(RoundedCornerShape(4.dp))
            .background(Line)
    )
}
