package com.aveline.ai.mobile.presentation.study

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Article
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.FolderOpen
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 知识笔记树。
 *
 * 以文件夹树形式展示学习库中的 .md 笔记：
 * - 顶层为科目文件夹，下面按实际目录层级展开；
 * - 隐藏目录/文件（如 .trae、.qoder）已在后端和本地双重过滤；
 * - 默认只展开顶层科目，子文件夹默认折叠，避免一次性渲染过多节点；
 * - 点击文件由顶层 [StudyScreenV2] 打开全屏阅读页（阅读页不再被分页器的内边距切窄）。
 *
 * 第三轮设计稿：去掉 SectionCard 与说明文字，标题和计数上移到页头；
 * 树本身只用细线分隔、每层缩进 20dp，展开箭头放到右侧，文件夹显示篇数。
 *
 * @param notesUiState 知识笔记域 UI 状态
 * @param onOpenNote 打开笔记回调（传入相对路径）
 */
@Composable
fun StudyNotesTab(
    notesUiState: StudyNotesUiState,
    onOpenNote: (String) -> Unit
) {
    val noteTree = notesUiState.noteTree

    // 展开集合：每次更新都赋新 Set 实例（保证 MutableState 正确触发重组）。
    // 首次拿到列表时展开顶层科目（只展开一层），让用户一眼看到笔记条目；
    // 子文件夹仍保持折叠，避免整棵树一次性铺开。
    var expandedPaths by remember { mutableStateOf(setOf<String>()) }
    var topLevelExpanded by remember { mutableStateOf(false) }
    if (!topLevelExpanded && noteTree.isNotEmpty()) {
        expandedPaths = noteTree.map { it.path }.toSet()
        topLevelExpanded = true
    }

    // 根据展开集合生成扁平可见节点列表（含缩进层级），LazyColumn 只组合可见项
    val visibleNodes = remember(noteTree, expandedPaths) {
        flattenVisibleNodes(noteTree, expandedPaths)
    }

    LazyColumn(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(top = 20.dp, bottom = 28.dp)
    ) {
        if (noteTree.isEmpty()) {
            item {
                // 加载中不要显示"暂无笔记"：库大时后端全盘扫描要几秒，
                // 旧文案会让用户以为笔记丢了。
                if (notesUiState.isLoading) {
                    Row(
                        modifier = Modifier.padding(bottom = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(10.dp)
                    ) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(18.dp),
                            color = Accent,
                            strokeWidth = 2.dp
                        )
                        Text(
                            text = "正在加载笔记…",
                            fontSize = 14.sp,
                            color = TextSecondary
                        )
                    }
                } else {
                    Text(
                        text = "学习库暂无笔记",
                        fontSize = 14.sp,
                        color = TextTertiary,
                        modifier = Modifier.padding(bottom = 8.dp)
                    )
                }
            }
        } else {
            items(visibleNodes.size) { index ->
                val (node, depth) = visibleNodes[index]
                NoteTreeRow(
                    node = node,
                    depth = depth,
                    isExpanded = expandedPaths.contains(node.path),
                    onFolderClick = {
                        expandedPaths = if (node.path in expandedPaths) {
                            expandedPaths - node.path
                        } else {
                            expandedPaths + node.path
                        }
                    },
                    onFileClick = { onOpenNote(node.path) }
                )
            }
        }
    }
}

/** 可见节点 + 缩进层级 */
private data class VisibleNode(val node: NoteTreeNode, val depth: Int)

/** 根据展开集合把树展开成扁平列表 */
private fun flattenVisibleNodes(
    nodes: List<NoteTreeNode>,
    expanded: Set<String>,
    depth: Int = 0,
): List<VisibleNode> = buildList {
    nodes.forEach { node ->
        add(VisibleNode(node, depth))
        if (node is NoteTreeNode.Folder && node.path in expanded) {
            addAll(flattenVisibleNodes(node.children, expanded, depth + 1))
        }
    }
}

/**
 * 单个树节点：48dp 细线行。
 *
 * 文件夹展开时图标提亮到正文色，折叠和文件都用 Faint；
 * 展开 / 收起箭头在右侧，文件夹在箭头前显示篇数。
 */
@Composable
private fun NoteTreeRow(
    node: NoteTreeNode,
    depth: Int,
    isExpanded: Boolean,
    onFolderClick: () -> Unit,
    onFileClick: () -> Unit
) {
    val isFolder = node is NoteTreeNode.Folder
    val icon = when (node) {
        is NoteTreeNode.Folder -> if (isExpanded) Icons.Default.FolderOpen else Icons.Default.Folder
        is NoteTreeNode.File -> Icons.AutoMirrored.Filled.Article
    }
    val iconColor = if (isFolder && isExpanded) TextPrimary else TextTertiary

    Column(modifier = Modifier.fillMaxWidth()) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(1.dp)
                .background(NoteHairline)
        )
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = 48.dp)
                .clickable {
                    when (node) {
                        is NoteTreeNode.Folder -> onFolderClick()
                        is NoteTreeNode.File -> onFileClick()
                    }
                }
                .padding(start = (depth * 20).dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = iconColor,
                modifier = Modifier.size(20.dp)
            )
            Spacer(modifier = Modifier.width(10.dp))
            Text(
                text = node.name,
                fontSize = 15.sp,
                fontWeight = if (isFolder) FontWeight.Medium else FontWeight.Normal,
                color = TextPrimary,
                modifier = Modifier.weight(1f)
            )
            if (node is NoteTreeNode.Folder) {
                Text(
                    text = node.fileCount().toString(),
                    fontSize = 12.5f.sp,
                    color = TextTertiary,
                    style = TextStyle(fontFeatureSettings = "tnum")
                )
                Spacer(modifier = Modifier.width(10.dp))
                Icon(
                    imageVector = if (isExpanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
                    contentDescription = if (isExpanded) "收起" else "展开",
                    tint = TextTertiary,
                    modifier = Modifier.size(18.dp)
                )
            }
        }
    }
}

/** 列表行顶栏线：6% 白。 */
private val NoteHairline = Color(0x0FFFFFFF)
