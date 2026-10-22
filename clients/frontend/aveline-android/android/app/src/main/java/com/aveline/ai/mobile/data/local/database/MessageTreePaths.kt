package com.aveline.ai.mobile.data.local.database

import com.aveline.ai.mobile.data.local.database.entity.MessageEntity

/**
 * 新消息落库前修正父链：父节点必须在库里真实存在。
 *
 * 父节点被删掉（典型：连续发两条消息时，第一条的 AI 空占位被新一轮顶掉并按空占位清理）
 * 而子节点还指着它时，这条消息一落库就是孤儿 —— Room 每次回流重算活跃路径都会把它
 * 从列表里抹掉，界面上的表现就是「第二条消息和它的回复一起消失」。
 *
 * 修正口径：
 * - 消息本身已存在（更新内容）→ 不改父链，分支归属由库里的记录说了算；
 * - 会话还没有任何消息 → 作为新的根；
 * - 父节点仍在 → 原样保留（分叉/版本关系由调用方决定）；
 * - 父节点已不在 → 挂回当前活跃路径的尾部，保持一条线性链。
 */
internal fun resolveParentForInsert(
    existing: List<MessageEntity>,
    messageId: String,
    requestedParentId: String?
): String? {
    if (existing.any { it.id == messageId }) return requestedParentId
    if (existing.isEmpty()) return null
    if (requestedParentId != null && existing.any { it.id == requestedParentId }) {
        return requestedParentId
    }
    return selectActiveMessageEntities(existing).lastOrNull()?.id
        ?: existing.maxByOrNull { it.timestamp }?.id
}

/** 页面、上下文和迁移共用相同的分支选择规则。 */
internal fun selectActiveMessageEntities(
    entities: List<MessageEntity>,
    rootId: String? = null
): List<MessageEntity> {
    val ordered = entities.sortedWith(compareBy<MessageEntity> { it.timestamp }.thenBy { it.id })
    val children = ordered.groupBy { it.parentId }
    var current = rootId?.let { id -> ordered.firstOrNull { it.id == id } }
        ?: children[null]?.firstOrNull { it.isActiveVariant }
        ?: children[null]?.firstOrNull() ?: ordered.firstOrNull()
    val visited = mutableSetOf<String>()
    val result = mutableListOf<MessageEntity>()
    while (current != null && visited.add(current.id)) {
        result += current
        current = children[current.id]?.firstOrNull { it.isActiveVariant }
            ?: children[current.id]?.firstOrNull()
    }
    return result
}
