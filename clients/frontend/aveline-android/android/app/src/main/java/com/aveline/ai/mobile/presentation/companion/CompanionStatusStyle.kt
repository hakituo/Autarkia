package com.aveline.ai.mobile.presentation.companion

import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.domain.models.LifeStatus
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.Mist
import com.aveline.ai.mobile.presentation.theme.Sand

// ── 伴侣详情共用度量 ──

/** 详情页统一左右留白：页头、Tab 栏、各 Tab 内容都用这一个值，保证竖线对齐 */
internal val CompanionGutter = 20.dp

/** 列表行之间的细线：6% 白，比 [com.aveline.ai.mobile.presentation.theme.Line] 更淡 */
internal val CompanionHairline = Color(0x0FFFFFFF)

/** 低于这个百分比的生命项才变成沙金色提醒 */
internal const val CompanionLowStatusPercent = 30

/**
 * 单选列表行的顶部细线。
 *
 * 比 [com.aveline.ai.mobile.presentation.theme.Line]（8% 白）更淡：
 * 模型 / 人设 / 音色 / 记忆条目都是几十行连续排列，8% 的线叠起来会变成一张表格。
 */
internal fun Modifier.companionRowHairline(): Modifier = drawBehind {
    val stroke = 1.dp.toPx()
    drawLine(
        color = CompanionHairline,
        start = Offset(0f, stroke / 2f),
        end = Offset(size.width, stroke / 2f),
        strokeWidth = stroke
    )
}

/**
 * 与后端 `DO_NOT_DISTURB_ACTIVITIES` 对齐的不可打扰活动集合。
 *
 * 这些活动期间后端只接受「唤醒」，行内不能给出无效的「打断」（会被后端退回
 * `sleeping_use_wake`）；此前漏了 overslept_recovery，会误给「打断/跳过」。
 */
internal val DO_NOT_DISTURB_ACTIVITIES = setOf(
    "sleeping",
    "napping",
    "waking_up",
    "overslept_recovery"
)

/** 当前是否处于「消息暂不回复」的状态（睡觉 / 午休 / 起床过渡 / 睡过头缓神） */
internal fun companionIsSleeping(lifeStatus: LifeStatus?): Boolean {
    val activity = lifeStatus?.activity.orEmpty().ifBlank { "idle" }
    return lifeStatus?.isSleeping == true || activity in DO_NOT_DISTURB_ACTIVITIES
}

/**
 * 页头状态点颜色。
 *
 * 只分三档：正常（鼠尾草绿）/ 专注（沙金）/ 睡觉（雾蓝）。此前用的是四档生活色，
 * 同一个页面上会同时出现四种含义不同的颜色，用户读不出「哪个才代表现在能不能聊」。
 */
internal fun companionStatusColor(lifeStatus: LifeStatus?): Color = when {
    companionIsSleeping(lifeStatus) -> Mist
    lifeStatus?.replyMode == "silent" -> Sand
    lifeStatus?.replyMode == "delayed" -> Sand
    else -> Accent
}

/** 页头第一行：此刻在做什么（优先用后端下发的活动名） */
internal fun companionActivityHeadline(lifeStatus: LifeStatus?): String {
    val activity = lifeStatus?.activity.orEmpty().ifBlank { "idle" }
    return lifeStatus?.dailyPlan?.activityLabel.orEmpty().ifBlank { companionActivityLabel(activity) }
}

/** 页头第二行：会不会回、什么时候回 */
internal fun companionStatusHint(lifeStatus: LifeStatus?): String {
    val activity = lifeStatus?.activity.orEmpty().ifBlank { "idle" }
    return when {
        activity == "napping" -> "午休中，消息暂不回复"
        activity == "waking_up" -> "刚起床洗漱，消息暂不回复"
        activity == "overslept_recovery" -> "刚睡醒正在缓神，消息暂不回复"
        companionIsSleeping(lifeStatus) -> "睡眠中，消息暂不回复"
        lifeStatus?.replyMode == "silent" -> "专注中，消息会留到活动结束后处理"
        lifeStatus?.replyMode == "delayed" -> companionReplyDelayText(lifeStatus)
        else -> "会正常回复"
    }
}

/** 是否需要唤醒 / 打断 / 跳过这类控制入口 */
internal fun companionNeedsActions(lifeStatus: LifeStatus?): Boolean =
    companionIsSleeping(lifeStatus) || lifeStatus?.replyMode == "silent"

/** 延迟回复的说明文案 */
internal fun companionReplyDelayText(lifeStatus: LifeStatus?): String {
    val minSeconds = lifeStatus?.replyDelayMinSeconds
    val maxSeconds = lifeStatus?.replyDelayMaxSeconds
    return if (minSeconds != null && maxSeconds != null) {
        "会延迟约 ${minSeconds}–${maxSeconds} 秒回复"
    } else {
        "会稍后回复"
    }
}

/** 活动 key 的兜底中文名（后端没下发 activity_label 时用） */
internal fun companionActivityLabel(activity: String): String = when (activity) {
    "sleeping" -> "正在睡觉"
    "waking_up" -> "正在起床洗漱"
    "breakfast" -> "正在吃早餐"
    "lunch" -> "正在吃午餐"
    "dinner" -> "正在吃晚餐"
    "cooking" -> "正在做饭"
    "studying" -> "正在学习"
    "reading" -> "正在阅读"
    "housework" -> "正在做家务"
    "napping" -> "正在午休"
    "walking" -> "正在散步"
    "phone_scrolling" -> "正在刷手机"
    "gardening" -> "正在打理植物"
    "exercising" -> "正在运动"
    "gaming" -> "正在玩游戏"
    "self_care" -> "正在护肤整理"
    "makeup" -> "正在化妆"
    "creative_hobby" -> "正在做自己的兴趣"
    "shopping" -> "正在外出购物"
    "staying_up_late" -> "正在熬夜"
    "late_snack" -> "正在吃夜宵"
    "overslept_recovery" -> "刚睡醒，正在缓神"
    "sleep_recovery" -> "正在恢复精神"
    "peer_chat" -> "正在聊天"
    "idle" -> "正在放松"
    else -> "当前状态"
}

/**
 * 情绪 key 的中文名。
 *
 * 与后端 `core/emotion/models.py::EmotionType` 一一对应；后端新增取值时
 * 原样显示 key，不做二次猜测，避免出现「未知」这种把信息抹掉的文案。
 */
internal fun companionEmotionLabel(key: String): String = when (key.trim().lowercase()) {
    "neutral" -> "平静"
    "happy" -> "开心"
    "sad" -> "难过"
    "angry" -> "生气"
    "anxious" -> "焦虑"
    "tired" -> "疲惫"
    "shy" -> "害羞"
    "excited" -> "兴奋"
    "jealous" -> "吃醋"
    "wronged" -> "委屈"
    "coquetry" -> "撒娇"
    "lost" -> "迷茫"
    "lonely" -> "孤独"
    "fear" -> "害怕"
    else -> key
}
