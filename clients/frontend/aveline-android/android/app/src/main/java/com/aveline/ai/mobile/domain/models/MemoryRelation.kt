package com.aveline.ai.mobile.domain.models

/**
 * 一条记忆的关联邻居。
 *
 * 关系由后端 `relation_graph` 稀疏投影推断（同一轮 / 同一件事 / 接着说 / 同一话题），
 * 客户端只负责展示与继续扩散，不重新计算关系。
 *
 * @property memory 邻居记忆本体（content 为后端截断后的预览文本）
 * @property relation 关系类型键（turn / event / continuation / topic …）
 * @property relationLabel 关系中文说明，由后端统一给出
 * @property strength 边强度（0~1），越大越近
 * @property distance 距中心记忆的跳数
 */
data class MemoryRelation(
    val memory: Memory,
    val relation: String,
    val relationLabel: String,
    val strength: Float,
    val distance: Int
) {
    /** 列表里的展示文本：预览已被后端截断，直接复用 */
    val preview: String
        get() = memory.displayContent
}
