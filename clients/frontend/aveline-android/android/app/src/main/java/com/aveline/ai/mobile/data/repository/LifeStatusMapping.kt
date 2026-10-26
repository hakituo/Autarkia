package com.aveline.ai.mobile.data.repository

import com.aveline.ai.mobile.data.remote.dto.LifeStatusResponse
import com.aveline.ai.mobile.domain.models.CharacterDailyPlan
import com.aveline.ai.mobile.domain.models.CharacterDailySlot
import com.aveline.ai.mobile.domain.models.LifeStatus

/**
 * `/life/status` 响应 → 领域模型。
 *
 * 日程槽位连 `execution_status` 一起搬运：客户端**只渲染后端给的状态**，
 * 不自行按设备时间推算「正在进行」，避免两端时区/时钟不一致时各说各话。
 */
internal fun LifeStatusResponse.toLifeStatus(persona: String?, timestamp: Long): LifeStatus {
    val life = life_status?.life
    return LifeStatus(
        health = (life?.energy ?: 100f) / 100f,
        hunger = (life?.hunger ?: 0f) / 100f,
        happiness = (life?.mood_score ?: 80f) / 100f,
        energy = (life?.energy ?: 100f) / 100f,
        timestamp = timestamp,
        scope = persona,
        activity = activity,
        activityChatEligible = activity_chat_eligible,
        replyMode = reply_policy?.mode ?: "immediate",
        replyDelayMinSeconds = reply_policy?.min_seconds,
        replyDelayMaxSeconds = reply_policy?.max_seconds,
        isSleeping = sleep_summary?.is_sleeping ?: false,
        sleepPhase = sleep_summary?.phase,
        dailyPlan = daily_plan?.let { plan ->
            CharacterDailyPlan(
                roleId = plan.role_id,
                date = plan.date,
                currentActivity = plan.current_activity,
                roleName = plan.role_name,
                activityLabel = plan.activity_label,
                activityDetail = plan.activity_detail,
                slots = plan.slots.map { slot ->
                    CharacterDailySlot(
                        activity = slot.activity,
                        label = slot.label,
                        detail = slot.detail,
                        plannedStart = slot.planned_start,
                        plannedEnd = slot.planned_end,
                        flexible = slot.flexible,
                        executionStatus = slot.execution_status
                    )
                }
            )
        }
    )
}
