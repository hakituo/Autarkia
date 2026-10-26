package com.aveline.ai.mobile.presentation.theme

/**
 * 呼吸光晕支持的情绪状态。
 * 与后端及 Web 端使用的小写情绪名一一对应。
 */
enum class EmotionState {
    NEUTRAL,
    HAPPY,
    SHY,
    ANGRY,
    JEALOUS,
    WRONGED,
    COQUETRY,
    LOST,
    EXCITED;

    companion object {
        /**
         * 把情绪名解析为枚举；无法识别时回落到 [NEUTRAL]，避免光晕消失。
         */
        fun fromString(emotion: String): EmotionState {
            return when (emotion.lowercase()) {
                "neutral" -> NEUTRAL
                "happy" -> HAPPY
                "shy" -> SHY
                "angry" -> ANGRY
                "jealous" -> JEALOUS
                "wronged" -> WRONGED
                "coquetry" -> COQUETRY
                "lost" -> LOST
                "excited" -> EXCITED
                else -> NEUTRAL
            }
        }
    }
}
