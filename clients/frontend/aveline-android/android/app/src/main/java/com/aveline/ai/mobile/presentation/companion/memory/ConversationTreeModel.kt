package com.aveline.ai.mobile.presentation.companion.memory

import com.aveline.ai.mobile.domain.models.Message
import kotlin.math.min

/** 分支最多缩进的层级；超过后不再加深，避免窄屏被挤没 */
private const val MAX_BRANCH_DEPTH = 4

/**
 * 聊天记录树的一行（已扁平化，供 LazyColumn 使用）。
 *
 * 主世界线不缩进、不画树线；只有重新生成 / 编辑产生的变体才作为分支缩进展示，
 * 因此长对话不会因为消息链越来越深而缩进到屏幕外。
 */
sealed interface ConversationTreeRow {
    /** LazyColumn 的稳定 key */
    val key: String

    /** 世界线嵌套层级：主世界线为 0，分支 = 父层级 + 1 */
    val depth: Int

    /** 显示顺序（新 → 旧）下位于同级组最上方的行；倒序渲染时用它收口分支线 */
    val isLastChild: Boolean

    /** 是否画树线（主世界线的消息不画） */
    val showRail: Boolean

    /** 一条真实消息 */
    data class MessageRow(
        val message: Message,
        val onActivePath: Boolean,
        /** 来自服务端历史（Windows / 其他平台），不是本机 Room 产生的 */
        val fromServer: Boolean,
        override val depth: Int,
        override val isLastChild: Boolean,
        override val showRail: Boolean
    ) : ConversationTreeRow {
        override val key: String get() = "chat-msg-${message.id}"
    }

    /** 「其他 N 个版本」折叠行：点击后铺开重新生成 / 编辑产生的平行分支 */
    data class BranchRow(
        val parentId: String,
        val hiddenCount: Int,
        override val depth: Int
    ) : ConversationTreeRow {
        override val key: String get() = "chat-branch-$parentId"
        override val isLastChild: Boolean get() = true
        override val showRail: Boolean get() = true
    }
}

/** 兄弟节点顺序与后端 `selectActiveConversationPath` 保持一致 */
private val SIBLING_ORDER: Comparator<Message> =
    compareBy<Message> { it.variantIndex }.thenBy { it.timestamp }.thenBy { it.id }

/**
 * 把会话的全部消息还原成「聊天记录 + 分支树」。
 *
 * 规则：
 * - 每个父节点只把当前激活的版本续在主世界线上（不缩进）；
 * - 其余版本折叠成一行「其他 N 个版本」，展开后按分支缩进展示；
 * - 分支内的后续对话继承该分支的层级；
 * - **返回按时间倒序排列（最新在最上）**：世界线结构照旧自根向下推导，
 *   最后整体反转，分支行因此出现在其活跃版本上方。
 *
 * 用显式栈而不是递归：长会话的 parent 链可能有数千层。工作项按「倒序压栈」
 * 保证弹出顺序，从而让「其他版本」紧跟在活跃版本下面，而不是跑到整条对话末尾。
 *
 * @param messages `ChatRepository.observeAllMessages` 的全量消息（含平行分支）
 * @param expandedBranches 已展开的分支点（父消息 id）
 * @param activeOnly 只看当前世界线（隐藏所有分支）
 */
internal fun buildConversationTreeRows(
    messages: List<Message>,
    expandedBranches: Set<String> = emptySet(),
    activeOnly: Boolean = false
): List<ConversationTreeRow> {
    if (messages.isEmpty()) return emptyList()

    val byId = messages.associateBy { it.id }
    // 父节点不在库里的消息（历史裁剪 / 脏数据）当作根，保证不会整段消失。
    val childrenByParent = messages
        .groupBy { message -> message.parentId?.takeIf { it in byId } }
        .mapValues { (_, children) -> children.sortedWith(SIBLING_ORDER) }

    val roots = childrenByParent[null].orEmpty()
    if (roots.isEmpty()) return emptyList()

    val activeIds = resolveActivePathIds(roots, childrenByParent)
    val rows = ArrayList<ConversationTreeRow>(messages.size)
    val work = ArrayDeque<Work>()

    /** 把 [parentId] 的子节点按展示顺序倒序压栈 */
    fun dispatchChildren(parentId: String, depth: Int) {
        val children = childrenByParent[parentId].orEmpty()
        if (children.isEmpty()) return

        val primary = children.firstOrNull { it.isActiveVariant } ?: children.first()
        val others = children.filter { it.id != primary.id }

        // 弹出顺序：活跃版本 → 其他版本 → 活跃版本的后续
        work.addLast(Work.Dispatch(primary.id, depth))
        if (!activeOnly && others.isNotEmpty()) {
            val branchDepth = min(depth + 1, MAX_BRANCH_DEPTH)
            if (parentId in expandedBranches) {
                others.asReversed().forEach { other ->
                    work.addLast(
                        Work.Visit(
                            message = other,
                            depth = branchDepth,
                            showRail = true,
                            isLast = other.id == others.last().id
                        )
                    )
                }
            } else {
                work.addLast(
                    Work.Branch(parentId = parentId, hiddenCount = others.size, depth = branchDepth)
                )
            }
        }
        work.addLast(Work.Emit(primary, depth = depth, showRail = false, isLast = true))
    }

    for (index in roots.indices.reversed()) {
        work.addLast(Work.Visit(roots[index], depth = 0, showRail = false, isLast = index == roots.lastIndex))
    }

    while (work.isNotEmpty()) {
        when (val item = work.removeLast()) {
            is Work.Emit -> {
                if (activeOnly && item.message.id !in activeIds) continue
                rows += ConversationTreeRow.MessageRow(
                    message = item.message,
                    onActivePath = item.message.id in activeIds,
                    fromServer = item.message.id.startsWith(REMOTE_MESSAGE_PREFIX),
                    depth = item.depth,
                    isLastChild = item.isLast,
                    showRail = item.showRail
                )
            }

            is Work.Dispatch -> dispatchChildren(item.parentId, item.depth)

            is Work.Visit -> {
                if (activeOnly && item.message.id !in activeIds) continue
                rows += ConversationTreeRow.MessageRow(
                    message = item.message,
                    onActivePath = item.message.id in activeIds,
                    fromServer = item.message.id.startsWith(REMOTE_MESSAGE_PREFIX),
                    depth = item.depth,
                    isLastChild = item.isLast,
                    showRail = item.showRail
                )
                dispatchChildren(item.message.id, item.depth)
            }

            is Work.Branch -> {
                rows += ConversationTreeRow.BranchRow(
                    parentId = item.parentId,
                    hiddenCount = item.hiddenCount,
                    depth = item.depth
                )
            }
        }
    }
    // 世界线自根向下推导得到「旧 → 新」，展示要求最新在最上，这里整体反转；
    // 分支行的 isLastChild 语义随之变成「同级组最上方」，树线由 Section 镜像绘制。
    return rows.reversed()
}

private sealed interface Work {
    /** 只输出一行，不处理子节点 */
    data class Emit(
        val message: Message,
        val depth: Int,
        val showRail: Boolean,
        val isLast: Boolean
    ) : Work

    /** 只处理子节点，不重复输出当前行 */
    data class Dispatch(val parentId: String, val depth: Int) : Work

    /** 输出一行并继续处理其子节点 */
    data class Visit(
        val message: Message,
        val depth: Int,
        val showRail: Boolean,
        val isLast: Boolean
    ) : Work

    data class Branch(val parentId: String, val hiddenCount: Int, val depth: Int) : Work
}

/**
 * 复刻 `selectActiveMessageEntities` 的活跃路径：从根开始每层优先跟 isActiveVariant，
 * 没有激活标记时退回该层第一条。
 */
private fun resolveActivePathIds(
    roots: List<Message>,
    childrenByParent: Map<String?, List<Message>>
): Set<String> {
    val activeIds = HashSet<String>()
    val orderedRoots = roots.sortedWith(compareBy<Message> { it.timestamp }.thenBy { it.id })
    var current: Message? = orderedRoots.firstOrNull { it.isActiveVariant } ?: orderedRoots.firstOrNull()
    while (current != null && activeIds.add(current.id)) {
        val children = childrenByParent[current.id].orEmpty()
        current = children.firstOrNull { it.isActiveVariant } ?: children.firstOrNull()
    }
    return activeIds
}

/** 所有发生过重新生成 / 编辑的消息父节点，用于「全部展开 / 收起」 */
internal fun conversationBranchParentIds(messages: List<Message>): Set<String> =
    messages.asSequence()
        .filter { it.variantCount > 1 }
        .mapNotNull { it.parentId }
        .toSet()

/** 服务端历史消息 id 前缀，与本地 Room 主键区分 */
internal const val REMOTE_MESSAGE_PREFIX = "remote-"

/** 上下文压缩产生的摘要不是对话条目，聊天记录树里不展示 */
private const val SUMMARY_PREFIX = "【历史摘要】"

/** 主动消息把心想嵌在正文开头的形态：`（心想：…）\n\n正文` */
private val INLINE_THOUGHT_REGEX =
    Regex("""^[（(]\s*心想\s*[:：]?\s*(.*?)\s*[）)]\s*""", RegexOption.DOT_MATCHES_ALL)

/**
 * 展示层归一化（本地 Room 与远程记录都要过一遍）：
 * - 摘要类内容返回 null，直接不进树；
 * - 正文开头的内嵌心想抠进 [Message.thought]，正文去掉前缀；
 * - 其余原样返回。
 */
internal fun normalizeForTree(message: Message): Message? {
    val text = message.text.trim()
    if (text.startsWith(SUMMARY_PREFIX)) return null

    val match = INLINE_THOUGHT_REGEX.find(text) ?: return message
    val thought = match.groupValues[1].trim()
    return message.copy(
        text = text.removeRange(match.range).trim(),
        thought = message.thought?.takeIf { it.isNotBlank() } ?: thought.ifBlank { null }
    )
}

/**
 * 把服务端聊天记录合并进本地消息树（只读展示用，不写本地库）。
 *
 * 规则：
 * - 本地消息树原样保留，分支与父子关系不动；
 * - 服务端消息按「角色 + 正文 + 5 秒内」去重，本地已经有的**不丢弃而是补齐心想**
 *   （本地库不存 thought，重复项的心想要回填，否则 Room 里已有的消息看不到心想）；
 * - 早于本地最新消息的服务端历史串成一条前置链，接到本地最早根的 parent 上；
 * - 晚于本地最新消息的串成独立根链，排在本地树之后。
 */
internal fun mergeConversationMessages(local: List<Message>, remote: List<Message>): List<Message> {
    val cleanLocal = local.mapNotNull { normalizeForTree(it) }
    if (remote.isEmpty()) return cleanLocal

    val cleanRemote = remote.mapNotNull { normalizeForTree(it) }

    val localIds = cleanLocal.mapTo(HashSet()) { it.id }
    val backfilledThoughts = HashMap<String, String>()
    val extra = cleanRemote.filter { candidate ->
        if (candidate.id in localIds) return@filter false
        val matched = cleanLocal.firstOrNull { it.isSameTurnAs(candidate) }
        if (matched != null) {
            val thought = candidate.thought?.takeIf { it.isNotBlank() }
            if (thought != null && matched.thought.isNullOrBlank()) {
                backfilledThoughts[matched.id] = thought
            }
            return@filter false
        }
        true
    }

    val mergedLocal = if (backfilledThoughts.isEmpty()) {
        cleanLocal
    } else {
        cleanLocal.map { message ->
            backfilledThoughts[message.id]?.let { message.copy(thought = it) } ?: message
        }
    }
    if (extra.isEmpty()) return mergedLocal

    val localLatest = mergedLocal.maxOfOrNull { it.timestamp }
    val (lead, trail) = extra.partition { localLatest == null || it.timestamp <= localLatest }
    val leadChain = chainMessages(lead)
    val trailChain = chainMessages(trail)

    // 比本地更新的服务端消息：接到本地最新Ye之后，形成主线的延续
    val localParentIds = mergedLocal.mapNotNull { it.parentId }.toSet()
    val latestLeaf = mergedLocal.filter { it.id !in localParentIds }.maxByOrNull { it.timestamp }
    val appendedTrail = if (trailChain.isEmpty() || latestLeaf == null) {
        trailChain
    } else {
        trailChain.mapIndexed { index, message ->
            if (index == 0) message.copy(parentId = latestLeaf.id) else message
        }
    }

    if (leadChain.isEmpty()) return mergedLocal + appendedTrail

    val roots = mergedLocal.filter { it.parentId == null || it.parentId !in localIds }
    val earliestRoot = roots.minByOrNull { it.timestamp } ?: mergedLocal.minByOrNull { it.timestamp }
    val adjustedLocal = if (earliestRoot == null) {
        mergedLocal
    } else {
        mergedLocal.map { message ->
            if (message.id == earliestRoot.id) {
                message.copy(parentId = leadChain.last().id)
            } else {
                message
            }
        }
    }
    return leadChain + adjustedLocal + appendedTrail
}

/** 按时间串成一条线性链，第一条作为根 */
private fun chainMessages(messages: List<Message>): List<Message> {
    var previousId: String? = null
    return messages.sortedBy { it.timestamp }.map { message ->
        val chained = message.copy(parentId = previousId)
        previousId = chained.id
        chained
    }
}

/** 角色相同、正文相同且时间相差 5 秒内，视为同一轮消息 */
private fun Message.isSameTurnAs(other: Message): Boolean =
    isUser == other.isUser &&
        text.trim() == other.text.trim() &&
        kotlin.math.abs(timestamp - other.timestamp) <= 5000

/** 消息在树里显示的一行文本；空正文按消息类型给出占位 */
internal fun conversationMessageText(message: Message): String {
    val text = message.text.trim()
    if (text.isNotEmpty()) return text
    return when (message.messageType.lowercase()) {
        "image" -> "[图片]"
        "video" -> "[视频]"
        "audio", "voice" -> "[语音]"
        "file", "attachment" -> "[附件]"
        "media" -> "[媒体]"
        else -> "(空消息)"
    }
}
