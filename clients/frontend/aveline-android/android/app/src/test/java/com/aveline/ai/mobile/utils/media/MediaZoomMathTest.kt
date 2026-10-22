package com.aveline.ai.mobile.utils.media

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 覆盖全屏看图的手势数学：放大后能拖动、但拖不出边界。
 *
 * 这些数字直接决定「图片放大后能不能拖回中间」，所以钉住上下限，
 * 而不是只验证"函数不崩"。
 */
class MediaZoomMathTest {

    @Test
    fun `未放大时不允许拖动`() {
        assertEquals(0f, MediaZoomMath.clampTranslation(value = 500f, scale = 1f, containerPx = 1080), 0.001f)
        assertEquals(0f, MediaZoomMath.clampTranslation(value = -500f, scale = 0.5f, containerPx = 1080), 0.001f)
    }

    @Test
    fun `放大后的可拖动余量是超出部分的一半`() {
        // 3 倍：多出来的 2 个屏宽左右各一半 → 单轴上限 1080
        assertEquals(1080f, MediaZoomMath.maxTranslation(scale = 3f, containerPx = 1080), 0.001f)
        assertEquals(1080f, MediaZoomMath.clampTranslation(5000f, 3f, 1080), 0.001f)
        assertEquals(-1080f, MediaZoomMath.clampTranslation(-5000f, 3f, 1080), 0.001f)
        assertEquals(300f, MediaZoomMath.clampTranslation(300f, 3f, 1080), 0.001f)
    }

    @Test
    fun `容器尺寸还没测量到时不做限制`() {
        assertEquals(0f, MediaZoomMath.clampTranslation(120f, 2f, 0), 0.001f)
        assertEquals(0f, MediaZoomMath.maxTranslation(2f, 0), 0.001f)
    }

    @Test
    fun `双击放大把点击位置拉到屏幕中心`() {
        // 点在正中间：不需要平移
        assertEquals(
            0f,
            MediaZoomMath.translationForDoubleTap(tapX = 540f, containerPx = 1080, scale = 2.5f),
            0.001f
        )
        // 点在左上角：往右下挪 (540 - 0) * 1.5 = 810，正好等于上限
        assertEquals(
            810f,
            MediaZoomMath.translationForDoubleTap(tapX = 0f, containerPx = 1080, scale = 2.5f),
            0.001f
        )
        assertEquals(
            -810f,
            MediaZoomMath.translationForDoubleTap(tapX = 1080f, containerPx = 1080, scale = 2.5f),
            0.001f
        )
    }
}
