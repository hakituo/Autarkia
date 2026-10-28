package com.aveline.ai.mobile.presentation.companion.memory

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.domain.models.Message

/**
 * 聊天树视图。
 *
 * 本地消息树（含重新生成 / 编辑产生的分支）+ 服务端历史（Windows / 其他平台）合并后
 * 按 parentId 还原成树。默认收起所有分支，只看当前世界线。
 *
 * @param companionName AI 发言时的署名（页头里的名字，避免这里写死「Aveline」）
 */
@Composable
internal fun MemoryConversationPane(
    localMessages: List<Message>,
    remoteMessages: List<Message>,
    companionName: String,
    modifier: Modifier = Modifier
) {
    var activeOnly by rememberSaveable { mutableStateOf(false) }
    var expandedBranches by remember { mutableStateOf<Set<String>>(emptySet()) }

    val messages = remember(localMessages, remoteMessages) {
        mergeConversationMessages(local = localMessages, remote = remoteMessages)
    }
    val rows = remember(messages, expandedBranches, activeOnly) {
        buildConversationTreeRows(
            messages = messages,
            expandedBranches = expandedBranches,
            activeOnly = activeOnly
        )
    }
    val branchParents = remember(messages) { conversationBranchParentIds(messages) }

    LazyColumn(
        modifier = modifier.fillMaxSize(),
        contentPadding = PaddingValues(top = 4.dp, bottom = 24.dp)
    ) {
        if (messages.isEmpty()) {
            item(key = "conversation-empty") { EmptyConversationTreeState() }
        } else {
            item(key = "conversation-switch") {
                ConversationWorldLineSwitch(
                    messageCount = messages.size,
                    branchCount = branchParents.size,
                    activeOnly = activeOnly,
                    onToggleActiveOnly = { activeOnly = !activeOnly }
                )
            }

            conversationTreeItems(
                rows = rows,
                companionName = companionName,
                onExpandBranch = { parentId -> expandedBranches = expandedBranches + parentId }
            )
        }
    }
}
