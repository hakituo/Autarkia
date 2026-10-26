package com.aveline.ai.mobile.services.endpoint

import com.aveline.ai.mobile.services.endpoint.resolver.EndpointCandidateProbe
import com.aveline.ai.mobile.services.endpoint.resolver.EndpointChannel
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.sync.withLock

/**
 * 并行探测三个自动候选，只报告结果、不改生效地址。
 *
 * [EndpointResolver.resolve] 是「命中第一个就返回」，拿不到后面候选的结果；
 * 设置页的网络列表要逐行写「可达 · 23ms / 不可达」，所以单独走这一条：
 * 不判网络类型、不做优先级短路，三条路同时探。
 *
 * 与 resolve 共用同一把锁，避免自动裁决和手动重探同时把探测连接打满。
 * 手动锁定不参与探测 —— 它的语义是「不再自动切换」。
 *
 * 放在门面外，是为了让 EndpointResolver 本身保持在 400 行以内。
 */
internal suspend fun EndpointResolver.probeCandidates(): List<EndpointCandidateProbe> =
    resolveMutex.withLock {
        coroutineScope {
            listOf(
                Triple(
                    EndpointChannel.LAN,
                    appPreferences.lanUrl.trim(),
                    EndpointResolver.LAN_CONNECT_TIMEOUT_MS to EndpointResolver.LAN_READ_TIMEOUT_MS
                ),
                Triple(
                    EndpointChannel.VPN,
                    appPreferences.vpnUrl.trim(),
                    EndpointResolver.VPN_CONNECT_TIMEOUT_MS to EndpointResolver.VPN_READ_TIMEOUT_MS
                ),
                Triple(
                    EndpointChannel.TUNNEL,
                    appPreferences.tunnelUrl.trim(),
                    EndpointResolver.WAN_CONNECT_TIMEOUT_MS to EndpointResolver.WAN_READ_TIMEOUT_MS
                )
            ).filter { it.second.isNotEmpty() }.map { (channel, url, timeouts) ->
                async {
                    val startedAt = System.nanoTime()
                    val reachable = prober.probe(url, timeouts.first, timeouts.second)
                    EndpointCandidateProbe(
                        channel = channel,
                        url = url,
                        reachable = reachable,
                        latencyMs = if (reachable) {
                            (System.nanoTime() - startedAt) / 1_000_000
                        } else {
                            null
                        }
                    )
                }
            }.awaitAll()
        }
    }
