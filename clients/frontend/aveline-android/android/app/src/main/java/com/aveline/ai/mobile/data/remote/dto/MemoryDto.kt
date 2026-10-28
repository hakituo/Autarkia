package com.aveline.ai.mobile.data.remote.dto

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
  * 记忆 DTO。
  *
  * 兼容后端 weighted_memory_manager 返回的字段命名:
  * id / content / category / weight / timestamp / created_at / last_access_time /
  * topics / emotions / emotion / is_important / source / display_tags 等。
  */
 @Serializable
 data class MemoryDto(
     @SerialName("id")
     val id: String,
 
     /** 后端在正文落盘阶段可能清空 content（由 ChatHistoryStore 回填），缺省按空串处理 */
     @SerialName("content")
     val content: String = "",
 
     @SerialName("summary")
     val summary: String? = null,
 
     @SerialName("type")
     val type: String? = null,
 
     @SerialName("memory_type")
     val memoryType: String? = null,
 
     @SerialName("category")
     val category: String? = null,
 
     @SerialName("importance")
     val importance: Double? = null,
 
     @SerialName("weight")
     val weight: Double? = null,
 
     @SerialName("access_count")
     val accessCount: Int? = null,
 
     @SerialName("last_accessed_at")
     val lastAccessedAt: String? = null,
 
     @SerialName("last_access_time")
     val lastAccessTime: Double? = null,
 
     @SerialName("created_at")
     val createdAt: String? = null,
 
     @SerialName("timestamp")
     val timestamp: Double? = null,
 
     @SerialName("updated_at")
     val updatedAt: String? = null,
 
     @SerialName("source")
     val source: String? = null,
 
     @SerialName("tags")
     val tags: List<String>? = null,
 
     @SerialName("topics")
     val topics: List<String>? = null,
 
     @SerialName("display_tags")
     val displayTags: List<String>? = null,
 
     @SerialName("keywords")
     val keywords: List<String>? = null,

     @SerialName("search_keywords")
     val searchKeywords: List<String>? = null,
 
     @SerialName("emotion")
     val emotion: String? = null,

     @SerialName("emotions")
     val emotions: List<String>? = null,
 
     @SerialName("is_important")
     val isImportant: Boolean? = null
 )

/**
 * 记忆列表响应
 */
@Serializable
data class MemoryListResponse(
    @SerialName("status")
    val status: String,
    
    @SerialName("data")
    val data: List<MemoryDto>,

    @SerialName("total")
    val total: Int? = null,

    @SerialName("offset")
    val offset: Int? = null,

    @SerialName("has_more")
    val hasMore: Boolean? = null,
    
    @SerialName("timestamp")
    val timestamp: Double? = null
)

/**
  * 记忆统计数据。
  *
  * 后端 /api/v1/memories/stats 返回:
  * counts / avg_weight / total_memories / distribution
  */
 @Serializable
 data class MemoryStatsData(
     @SerialName("counts")
     val counts: Map<String, Int> = emptyMap(),
 
     @SerialName("avg_weight")
     val avgWeight: Map<String, Double> = emptyMap(),
 
     @SerialName("total_memories")
     val totalMemories: Int = 0,
 
     @SerialName("distribution")
     val distribution: Map<String, Double> = emptyMap()
 )

/**
 * 记忆统计响应
 */
@Serializable
data class MemoryStatsResponse(
    @SerialName("status")
    val status: String,
    
    @SerialName("data")
    val data: MemoryStatsData,
    
    @SerialName("timestamp")
    val timestamp: Double? = null
)

/**
 * 记忆标签项
 */
@Serializable
data class TagItem(
    @SerialName("name")
    val name: String,
    
    @SerialName("weight")
    val weight: Double
)

/**
 * 记忆标签响应
 */
@Serializable
data class TagsResponse(
    @SerialName("status")
    val status: String,
    
    @SerialName("data")
    val data: List<TagItem>,
    
    @SerialName("timestamp")
    val timestamp: Double? = null
)

/**
 * 记忆关联节点。
 *
 * 对应后端 `GET /api/v1/memories/{id}/relations` 的单个邻居：
 * `relation_label` 是后端统一给出的中文说明（同一轮 / 同一话题 / 接着说 …），
 * 客户端不再维护第二套关系映射；`preview` 是后端截断后的可展示文本。
 */
@Serializable
data class MemoryRelationDto(
    @SerialName("id")
    val id: String,

    @SerialName("relation")
    val relation: String = "",

    @SerialName("relation_label")
    val relationLabel: String? = null,

    @SerialName("strength")
    val strength: Double = 0.0,

    @SerialName("graph_distance")
    val graphDistance: Int = 1,

    @SerialName("preview")
    val preview: String = "",

    @SerialName("created_at")
    val createdAt: String? = null,

    @SerialName("timestamp")
    val timestamp: Double? = null,

    @SerialName("weight")
    val weight: Double? = null,

    @SerialName("category")
    val category: String? = null,

    @SerialName("topics")
    val topics: List<String>? = null,

    @SerialName("emotion")
    val emotion: String? = null,

    @SerialName("is_important")
    val isImportant: Boolean? = null
)

/**
 * 关系邻域数据体。
 *
 * `root_id` 是中心记忆，`nodes` 不含中心节点本身，按「跳数 → 边强度 → 权重」排序。
 */
@Serializable
data class MemoryRelationsData(
    @SerialName("root_id")
    val rootId: String = "",

    @SerialName("nodes")
    val nodes: List<MemoryRelationDto> = emptyList(),

    @SerialName("truncated")
    val truncated: Boolean = false
)

/**
 * 关系邻域响应
 */
@Serializable
data class MemoryRelationsResponse(
    @SerialName("status")
    val status: String,

    @SerialName("data")
    val data: MemoryRelationsData,

    @SerialName("timestamp")
    val timestamp: Double? = null
)

/**
 * 记忆地标：某天围绕某个话题的一簇记忆。
 *
 * `id` 指向片段里最显著的那条真实记忆，点进去再展开它的邻域。
 */
@Serializable
data class MemoryAnchorDto(
    @SerialName("id")
    val id: String,

    @SerialName("title")
    val title: String = "",

    @SerialName("preview")
    val preview: String = "",

    @SerialName("member_count")
    val memberCount: Int = 1,

    @SerialName("weight")
    val weight: Double? = null,

    @SerialName("category")
    val category: String? = null,

    @SerialName("topics")
    val topics: List<String>? = null,

    @SerialName("created_at")
    val createdAt: String? = null,

    @SerialName("timestamp")
    val timestamp: Double? = null,

    @SerialName("is_important")
    val isImportant: Boolean? = null
)

/** 地标列表数据体 */
@Serializable
data class MemoryAnchorsData(
    @SerialName("anchors")
    val anchors: List<MemoryAnchorDto> = emptyList()
)

/** 地标列表响应 */
@Serializable
data class MemoryAnchorsResponse(
    @SerialName("status")
    val status: String,

    @SerialName("data")
    val data: MemoryAnchorsData,

    @SerialName("timestamp")
    val timestamp: Double? = null
)

/** 记忆网络里的一条边 */
@Serializable
data class MemoryGraphEdgeDto(
    @SerialName("source")
    val source: String,

    @SerialName("target")
    val target: String,

    @SerialName("relation")
    val relation: String = "",

    @SerialName("relation_label")
    val relationLabel: String? = null,

    @SerialName("strength")
    val strength: Double = 0.0
)

/** 记忆网络子图数据体：节点复用 [MemoryRelationDto] */
@Serializable
data class MemoryGraphData(
    @SerialName("root_id")
    val rootId: String = "",

    @SerialName("nodes")
    val nodes: List<MemoryRelationDto> = emptyList(),

    @SerialName("edges")
    val edges: List<MemoryGraphEdgeDto> = emptyList(),

    @SerialName("truncated")
    val truncated: Boolean = false
)

/** 记忆网络子图响应 */
@Serializable
data class MemoryGraphResponse(
    @SerialName("status")
    val status: String,

    @SerialName("data")
    val data: MemoryGraphData,

    @SerialName("timestamp")
    val timestamp: Double? = null
)
