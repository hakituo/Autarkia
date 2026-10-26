package com.aveline.ai.mobile.services.endpoint.resolver

/**
 * 单个候选地址的探测结果，供设置页「网络」的候选列表逐行展示。
 *
 * [reachable] 为 false 时 [latencyMs] 必为 null：失败探测的耗时等于超时时间，
 * 写出来只会让用户误以为「慢但能连」。
 */
data class EndpointCandidateProbe(
    val channel: EndpointChannel,
    val url: String,
    val reachable: Boolean,
    val latencyMs: Long? = null
)
