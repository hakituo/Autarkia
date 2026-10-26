package com.aveline.ai.mobile.presentation.theme

import androidx.compose.ui.graphics.Color
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 情绪光晕色映射：每个情绪只对应一团光晕色，未知值回落中性。
 */
class EmotionPaletteTest {

    private val expected = mapOf(
        "neutral" to Color(0xFFA5A9B4),
        "happy" to Color(0xFFD6BF8F),
        "shy" to Color(0xFFDCB4BF),
        "angry" to Color(0xFFD99D94),
        "jealous" to Color(0xFFB5ABD6),
        "wronged" to Color(0xFFA4B7D6),
        "coquetry" to Color(0xFFD6ACC4),
        "lost" to Color(0xFF9C9CA3),
        "excited" to Color(0xFF95CCBC)
    )

    @Test
    fun `every emotion maps to its glow color`() {
        expected.forEach { (emotion, color) ->
            assertEquals("emotion $emotion", color, EmotionPalette.of(emotion))
        }
    }

    @Test
    fun `emotion parsing is case insensitive`() {
        assertEquals(EmotionState.HAPPY, EmotionState.fromString("HAPPY"))
        assertEquals(EmotionState.EXCITED, EmotionState.fromString("Excited"))
    }

    @Test
    fun `unknown emotion falls back to neutral`() {
        assertEquals(EmotionPalette.of("neutral"), EmotionPalette.of("unknown"))
    }

    @Test
    fun `null emotion falls back to neutral`() {
        assertEquals(EmotionPalette.of("neutral"), EmotionPalette.of(null))
    }
}
