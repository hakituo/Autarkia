package com.aveline.ai.mobile.presentation.chat

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.rounded.KeyboardArrowRight
import androidx.compose.material.icons.rounded.ContentCopy
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.Edit
import androidx.compose.material.icons.rounded.MoreHoriz
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Stop
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.domain.models.Message
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * ChatGPT 风格的消息操作栏（设计稿「Chat · 输入栏」那张聊天页里的操作行）。
 *
 * 操作与版本切换放在同一行，不塞进气泡内部：
 * AI：复制 / TTS / 重新生成 / 版本导航 / 更多；用户：编辑 / 版本导航 / 更多。
 *
 * 控件语言对齐设计稿：所有动作都是 40dp 的无底色 ghost 图标（19dp 图标、Tertiary 色），
 * 版本计数用等宽数字。
 */
@Composable
fun ChatMessageActionBar(
    message: Message,
    isPlaying: Boolean,
    isTtsLoading: Boolean,
    actions: ChatMessageActions,
    modifier: Modifier = Modifier
) {
    var showMore by remember(message.id) { mutableStateOf(false) }

    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(start = 12.dp, end = 12.dp, top = 0.dp, bottom = 4.dp),
        horizontalArrangement = if (message.isUser) Arrangement.End else Arrangement.Start,
        verticalAlignment = Alignment.CenterVertically
    ) {
        if (message.isUser) {
            ToolbarButton(
                onClick = { actions.onEdit(message.id, message.text) },
                contentDescription = "编辑消息"
            ) {
                Icon(
                    imageVector = Icons.Rounded.Edit,
                    contentDescription = null,
                    tint = TextTertiary,
                    modifier = Modifier.size(19.dp)
                )
            }
        } else {
            ToolbarButton(
                onClick = { actions.onCopy(message.text) },
                contentDescription = "复制"
            ) {
                Icon(
                    imageVector = Icons.Rounded.ContentCopy,
                    contentDescription = null,
                    tint = TextTertiary,
                    modifier = Modifier.size(19.dp)
                )
            }

            ToolbarButton(
                onClick = { actions.onPlayTTS(message.id) },
                contentDescription = if (isPlaying) "停止播放" else "播放语音"
            ) {
                if (isTtsLoading) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(16.dp),
                        strokeWidth = 2.dp,
                        color = TextTertiary
                    )
                } else {
                    Icon(
                        imageVector = if (isPlaying) Icons.Rounded.Stop else Icons.Rounded.PlayArrow,
                        contentDescription = null,
                        tint = TextTertiary,
                        modifier = Modifier.size(19.dp)
                    )
                }
            }

            ToolbarButton(
                onClick = { actions.onRegenerate(message.id) },
                contentDescription = "重新生成"
            ) {
                Icon(
                    imageVector = Icons.Rounded.Refresh,
                    contentDescription = null,
                    tint = TextTertiary,
                    modifier = Modifier.size(19.dp)
                )
            }
        }

        if (message.variantCount > 1) {
            ToolbarButton(
                onClick = { actions.onSwitchVariant(message.id, -1) },
                contentDescription = "上一个版本",
                enabled = message.variantIndex > 0,
                width = 32.dp
            ) {
                Icon(
                    imageVector = Icons.AutoMirrored.Rounded.KeyboardArrowLeft,
                    contentDescription = null,
                    tint = TextTertiary,
                    modifier = Modifier.size(20.dp)
                )
            }

            Text(
                text = "${message.variantIndex + 1}/${message.variantCount}",
                color = TextSecondary,
                fontSize = 12.sp,
                fontFamily = FontFamily.Monospace,
                modifier = Modifier.padding(horizontal = 2.dp)
            )

            ToolbarButton(
                onClick = { actions.onSwitchVariant(message.id, 1) },
                contentDescription = "下一个版本",
                enabled = message.variantIndex < message.variantCount - 1,
                width = 32.dp
            ) {
                Icon(
                    imageVector = Icons.AutoMirrored.Rounded.KeyboardArrowRight,
                    contentDescription = null,
                    tint = TextTertiary,
                    modifier = Modifier.size(20.dp)
                )
            }
        }

        Box {
            ToolbarButton(
                onClick = { showMore = true },
                contentDescription = "更多"
            ) {
                Icon(
                    imageVector = Icons.Rounded.MoreHoriz,
                    contentDescription = null,
                    tint = TextTertiary,
                    modifier = Modifier.size(19.dp)
                )
            }

            DropdownMenu(
                expanded = showMore,
                onDismissRequest = { showMore = false }
            ) {
                if (message.isUser) {
                    DropdownMenuItem(
                        text = { Text("复制") },
                        leadingIcon = {
                            Icon(Icons.Rounded.ContentCopy, contentDescription = null)
                        },
                        onClick = {
                            showMore = false
                            actions.onCopy(message.text)
                        }
                    )
                }
                DropdownMenuItem(
                    text = { Text("删除") },
                    leadingIcon = {
                        Icon(
                            imageVector = Icons.Rounded.Delete,
                            contentDescription = null,
                            tint = TextTertiary
                        )
                    },
                    onClick = {
                        showMore = false
                        actions.onDelete(message.id)
                    }
                )
            }
        }
    }
}

/**
 * 操作栏里的图标按钮。
 *
 * @param width 版本导航用 32dp 的窄位，其余是 40dp 的方形触控区
 */
@Composable
private fun ToolbarButton(
    onClick: () -> Unit,
    contentDescription: String,
    enabled: Boolean = true,
    width: Dp = 40.dp,
    content: @Composable () -> Unit
) {
    Box(
        modifier = Modifier
            .width(width)
            .height(40.dp)
            .alpha(if (enabled) 1f else 0.38f)
            .clip(CircleShape)
            .clickable(enabled = enabled, onClick = onClick)
            .semantics { this.contentDescription = contentDescription },
        contentAlignment = Alignment.Center
    ) {
        content()
    }
}
