package com.aveline.ai.mobile.presentation.companion.memory

import com.aveline.ai.mobile.domain.models.Memory
import com.aveline.ai.mobile.domain.models.MemorySortOrder
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

/**
 * 记忆树的一级节点：时间桶。
 *
 * 顺序固定为「今天 → 昨天 → 本周 → 本月 → 更早」，保证每次进页面结构稳定。
 */
enum class MemoryTimeBucket(val label: String) {
    TODAY("今天"),
    YESTERDAY("昨天"),
    THIS_WEEK("本周"),
    THIS_MONTH("本月"),
    EARLIER("更早")
}

/**
 * 记忆树的二级节点：同一时间桶内的一个话题簇。
 *
 * @property key 话题键（与 [com.aveline.ai.mobile.domain.models.Memory.topicKey] 一致）
 * @property label 话题中文名
 * @property memories 已按当前排序方式排好的条目
 */
data class MemoryTopicNode(
    val key: String,
    val label: String,
    val memories: List<Memory>
) {
    val count: Int get() = memories.size
    val importantCount: Int get() = memories.count { it.isImportant }
}

/**
 * 记忆树的一级节点实例：时间桶 + 其下话题。
 */
data class MemoryBucketNode(
    val bucket: MemoryTimeBucket,
    val topics: List<MemoryTopicNode>
) {
    val count: Int get() = topics.sumOf { it.count }
    val importantCount: Int get() = topics.sumOf { it.importantCount }
}

/** 蒸馏链路偶尔会把空值写成字符串，这些不是有效记忆内容 */
private val PLACEHOLDER_TEXTS = setOf("none", "null", "undefined", "nan")

/**
 * 记忆条目是否值得展示。
 *
 * 后端落盘会清空 content（正文由 ChatHistoryStore 回填），回填失败的记录
 * 只剩空壳或占位字符串；这类记录不参与树构建，直接过滤，
 * 避免列表里出现大片空白卡片和「None」摘要。
 */
internal fun Memory.hasVisibleContent(): Boolean {
    val text = displayContent.trim()
    return text.isNotEmpty() && text.lowercase() !in PLACEHOLDER_TEXTS
}

/**
 * 把扁平记忆列表构建成「时间 → 话题 → 条目」三层树。
 *
 * 分组只做展示层聚合，不改动任何记忆数据；过滤条件已由 ViewModel 处理，
 * 这里只负责排序、剔除空壳和归组。
 */
internal fun buildMemoryTree(
    memories: List<Memory>,
    sortOrder: MemorySortOrder,
    now: Instant = Instant.now(),
    zoneId: ZoneId = ZoneId.systemDefault()
): List<MemoryBucketNode> {
    val visible = memories.filter { it.hasVisibleContent() }
    if (visible.isEmpty()) return emptyList()

    val sorted = when (sortOrder) {
        MemorySortOrder.NEWEST_FIRST -> visible.sortedByDescending { it.createdAt }
        MemorySortOrder.OLDEST_FIRST -> visible.sortedBy { it.createdAt }
        MemorySortOrder.MOST_ACCESSED -> visible.sortedByDescending { it.accessCount }
        MemorySortOrder.MOST_IMPORTANT -> visible.sortedByDescending { it.importance }
    }

    val today = now.atZone(zoneId).toLocalDate()
    val grouped = LinkedHashMap<MemoryTimeBucket, LinkedHashMap<String, MutableList<Memory>>>()
    sorted.forEach { memory ->
        val bucket = bucketOf(memory.createdAt.atZone(zoneId).toLocalDate(), today)
        val topicMap = grouped.getOrPut(bucket) { LinkedHashMap() }
        topicMap.getOrPut(memory.topicKey) { mutableListOf() }.add(memory)
    }

    return MemoryTimeBucket.entries.mapNotNull { bucket ->
        val topicMap = grouped[bucket] ?: return@mapNotNull null
        MemoryBucketNode(
            bucket = bucket,
            topics = topicMap.map { (key, items) ->
                MemoryTopicNode(key = key, label = items.first().topicLabel, memories = items)
            }
        )
    }
}

/** 计算日期所属时间桶；未来时间（设备时钟偏差）归入「今天」 */
internal fun bucketOf(date: LocalDate, today: LocalDate): MemoryTimeBucket = when {
    !date.isBefore(today) -> MemoryTimeBucket.TODAY
    date == today.minusDays(1) -> MemoryTimeBucket.YESTERDAY
    date.isAfter(today.minusDays(7)) -> MemoryTimeBucket.THIS_WEEK
    date.isAfter(today.minusDays(30)) -> MemoryTimeBucket.THIS_MONTH
    else -> MemoryTimeBucket.EARLIER
}

/**
 * 话题汇总（概览卡的筛选 chips 用）。
 *
 * @return 按条目数降序排列的「话题键 → 条目数」
 */
internal fun topicCounts(memories: List<Memory>): List<Pair<String, Int>> = memories
    .asSequence()
    .filter { it.hasVisibleContent() }
    .groupingBy { it.topicKey }
    .eachCount()
    .entries
    .sortedWith(compareByDescending<Map.Entry<String, Int>> { it.value }.thenBy { it.key })
    .map { it.key to it.value }
