package com.aveline.ai.mobile.data.repository

import com.aveline.ai.mobile.data.remote.api.AvelineApiService
import com.aveline.ai.mobile.data.remote.api.WebSocketManager
import com.aveline.ai.mobile.data.remote.api.WebSocketMessage
import com.aveline.ai.mobile.data.remote.dto.CharacterDailyPlanDto
import com.aveline.ai.mobile.data.remote.dto.CharacterDailySlotDto
import com.aveline.ai.mobile.data.remote.dto.LifeMetricsDto
import com.aveline.ai.mobile.data.remote.dto.LifeStatusDto
import com.aveline.ai.mobile.data.remote.dto.LifeStatusResponse
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDateTime
import java.time.ZoneId

/**
 * 日程缓存与 WS 推送的关系回归测试。
 *
 * 背景：后端生命模拟每秒广播 `life_status`，它只带生命值与 activity，不带
 * `daily_plan`。旧实现每次 WS 推送都推进 HTTP 缓存时钟，`/life/status` 再也
 * 不回源，日程（含 execution_status）整晚停在最后一次拉取的快照上——
 * 凌晨 1 点会显示「昨天下午 16:46-17:36 的活动正在进行」。
 */
class StatusRepositoryImplPlanCacheTest {

    private val zone: ZoneId = ZoneId.systemDefault()

    private fun millisOf(year: Int, month: Int, day: Int, hour: Int, minute: Int): Long =
        LocalDateTime.of(year, month, day, hour, minute).atZone(zone).toInstant().toEpochMilli()

    private val yesterdayEvening = millisOf(2026, 10, 24, 17, 0)
    private val todayEarlyMorning = millisOf(2026, 10, 25, 1, 23)

    private fun statusResponse(
        planDate: String,
        activity: String,
        slotStatus: String = "in_progress",
        slotStart: String = "${planDate}T16:46:00",
        slotEnd: String = "${planDate}T17:36:00"
    ): LifeStatusResponse = LifeStatusResponse(
        status = "success",
        life_status = LifeStatusDto(
            life = LifeMetricsDto(energy = 80f),
            timestamp = "2026-10-25T01:23:00+08:00"
        ),
        activity = activity,
        activity_chat_eligible = true,
        daily_plan = CharacterDailyPlanDto(
            role_id = "aveline",
            role_name = "Aveline",
            date = planDate,
            current_activity = activity,
            activity_label = "继续之前没看完的内容",
            activity_detail = "在家里，自己一个人",
            slots = listOf(
                CharacterDailySlotDto(
                    activity = "reading",
                    label = "继续之前没看完的内容",
                    detail = "在家里，自己一个人",
                    planned_start = slotStart,
                    planned_end = slotEnd,
                    flexible = true,
                    execution_status = slotStatus
                )
            )
        )
    )

    private fun newRepository(api: AvelineApiService): StatusRepositoryImpl {
        val ws = mockk<WebSocketManager>(relaxed = true)
        every { ws.messages } returns MutableSharedFlow<WebSocketMessage>().asSharedFlow()
        return StatusRepositoryImpl(api, ws)
    }

    @Test
    fun `跨日后昨天日程的缓存不再命中且执行状态回到接口值`() = runTest {
        val api = mockk<AvelineApiService>()
        coEvery { api.getLifeStatus(any(), any()) } returns statusResponse(
            planDate = "2026-10-24",
            activity = "reading"
        )
        val repository = newRepository(api)

        repository.clock = { yesterdayEvening }
        val cached = repository.getLifeStatus("aveline").getOrThrow()
        assertEquals("2026-10-24", cached.dailyPlan?.date)
        assertEquals("in_progress", cached.dailyPlan?.slots?.single()?.executionStatus)

        // 跨到第二天凌晨：即便距离上次拉取不到 60 秒，也必须回源拿今天的计划。
        coEvery { api.getLifeStatus(any(), any()) } returns statusResponse(
            planDate = "2026-10-25",
            activity = "sleeping",
            slotStatus = "pending",
            slotStart = "2026-10-25T00:00:00",
            slotEnd = "2026-10-25T08:30:00"
        )
        repository.clock = { todayEarlyMorning }
        val refreshed = repository.getLifeStatus("aveline").getOrThrow()

        assertEquals("2026-10-25", refreshed.dailyPlan?.date)
        assertEquals("pending", refreshed.dailyPlan?.slots?.single()?.executionStatus)
        coVerify(exactly = 2) { api.getLifeStatus(any(), any()) }
    }

    @Test
    fun `WS 推送不会给接口缓存续命`() = runTest {
        val api = mockk<AvelineApiService>()
        coEvery { api.getLifeStatus(any(), any()) } returns statusResponse(
            planDate = "2026-10-25",
            activity = "sleeping"
        )
        val repository = newRepository(api)

        repository.clock = { todayEarlyMorning }
        repository.getLifeStatus("aveline").getOrThrow()

        // 后端每秒广播一次的推送：只带生命值，同一天、活动没变 → 不该要求回源。
        repository.clock = { todayEarlyMorning + 10_000 }
        val shouldRefetch = repository.applyLifeStatusUpdate(
            WebSocketMessage.LifeStatusUpdate(
                life = mapOf("energy" to 60f, "hunger" to 10f),
                activity = "sleeping",
                timestamp = todayEarlyMorning + 10_000
            )
        )
        assertFalse(shouldRefetch)

        // 缓存窗口已过：必须重新请求。旧实现被上面那次推送把时钟推到 +10s，
        // 这里会命中缓存只请求 1 次，日程永远停在旧快照。
        repository.clock = { todayEarlyMorning + 62_000 }
        repository.getLifeStatus("aveline").getOrThrow()

        coVerify(exactly = 2) { api.getLifeStatus(any(), any()) }
    }

    @Test
    fun `WS 推送的 activity 会覆盖缓存里的旧活动`() = runTest {
        val api = mockk<AvelineApiService>()
        coEvery { api.getLifeStatus(any(), any()) } returns statusResponse(
            planDate = "2026-10-25",
            activity = "reading"
        )
        val repository = newRepository(api)

        repository.clock = { todayEarlyMorning }
        repository.getLifeStatus("aveline").getOrThrow()

        repository.clock = { todayEarlyMorning + 10_000 }
        val shouldRefetch = repository.applyLifeStatusUpdate(
            WebSocketMessage.LifeStatusUpdate(
                life = mapOf("energy" to 60f),
                activity = "sleeping",
                timestamp = todayEarlyMorning + 10_000
            )
        )

        assertEquals("sleeping", repository.cachedLifeStatus.value?.activity)
        // 活动变了但 WS 不带新日程，需要回源补拉槽位与执行状态。
        assertTrue(shouldRefetch)
    }

    @Test
    fun `设备跨日后 WS 推送要求回源`() = runTest {
        val api = mockk<AvelineApiService>()
        coEvery { api.getLifeStatus(any(), any()) } returns statusResponse(
            planDate = "2026-10-24",
            activity = "sleeping"
        )
        val repository = newRepository(api)

        repository.clock = { yesterdayEvening }
        repository.getLifeStatus("aveline").getOrThrow()

        repository.clock = { todayEarlyMorning }
        val shouldRefetch = repository.applyLifeStatusUpdate(
            WebSocketMessage.LifeStatusUpdate(
                life = mapOf("energy" to 60f),
                activity = "sleeping",
                timestamp = todayEarlyMorning
            )
        )

        assertTrue(shouldRefetch)
    }

    @Test
    fun `服务器时区比设备快一天时不会误判为跨日`() = runTest {
        // 设备还在 10-24 22:00（本地时区），后端按 Asia/Shanghai 生成的是 10-25 的计划，
        // 两边日期天然差一天；此时设备没有翻页，缓存必须照常命中。
        val deviceNight = millisOf(2026, 10, 24, 22, 0)
        val api = mockk<AvelineApiService>()
        coEvery { api.getLifeStatus(any(), any()) } returns statusResponse(
            planDate = "2026-10-25",
            activity = "sleeping"
        )
        val repository = newRepository(api)

        repository.clock = { deviceNight }
        val first = repository.getLifeStatus("aveline").getOrThrow()
        assertEquals("2026-10-25", first.dailyPlan?.date)

        // 同一设备日 30 秒后再读：计划日期与设备日期仍差一天，但设备没翻页 → 命中缓存。
        repository.clock = { deviceNight + 30_000 }
        repository.getLifeStatus("aveline").getOrThrow()
        coVerify(exactly = 1) { api.getLifeStatus(any(), any()) }

        // WS 推送同样不能把「计划日期比设备日期晚一天」当成过期。
        assertFalse(
            repository.applyLifeStatusUpdate(
                WebSocketMessage.LifeStatusUpdate(
                    life = mapOf("energy" to 70f),
                    activity = "sleeping",
                    timestamp = deviceNight + 31_000
                )
            )
        )
    }

    @Test
    fun `设备日期锚点未推进时不算过期`() {
        assertFalse(isDeviceDateAdvanced(null, "2026-10-25"))
        assertFalse(isDeviceDateAdvanced("", "2026-10-25"))
        assertFalse(isDeviceDateAdvanced("2026-10-25", "2026-10-25"))
        // 设备时区往回拨：不判过期，避免陷入反复回源
        assertFalse(isDeviceDateAdvanced("2026-10-25", "2026-10-24"))
        assertTrue(isDeviceDateAdvanced("2026-10-24", "2026-10-25"))
    }

    @Test
    fun `clearCache 会重置设备日期锚点`() = runTest {
        val api = mockk<AvelineApiService>()
        coEvery { api.getLifeStatus(any(), any()) } returns statusResponse(
            planDate = "2026-10-24",
            activity = "sleeping"
        )
        val repository = newRepository(api)

        repository.clock = { yesterdayEvening }
        repository.getLifeStatus("aveline").getOrThrow()
        assertFalse(repository.isCachedPlanStaleForDeviceDay())

        repository.clearCache()
        // 锚点清空后即使设备日期还没推进也不判过期（由 60 秒窗口与空缓存兜底）
        assertFalse(repository.isCachedPlanStaleForDeviceDay())

        repository.clock = { todayEarlyMorning }
        repository.getLifeStatus("aveline").getOrThrow()
        coVerify(exactly = 2) { api.getLifeStatus(any(), any()) }
    }
}
