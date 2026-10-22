package com.aveline.ai.mobile.utils.media

/**
 * 全屏看图的手势数学（纯函数，便于单测）。
 *
 * 只做一件事：把缩放后的平移量限制在「放大后的图片正好铺满容器」的范围内，
 * 放大后拖动不会把图片拖出屏幕、在四周留出一片按不回来的黑边。
 *
 * 这里刻意不依赖 Compose：同一套数值口径可以在 JVM 单测里直接验证，
 * 手势层只负责把算出来的值交给 graphicsLayer。
 */
object MediaZoomMath {

    /** 原始大小：不允许缩小到比"适配屏幕"更小。 */
    const val MIN_SCALE = 1f

    /** 最大放大倍数。 */
    const val MAX_SCALE = 5f

    /** 双击放大到的倍数。 */
    const val DOUBLE_TAP_SCALE = 2.5f

    /**
     * 单轴平移上限：容器尺寸 ×（缩放倍数 − 1）/ 2。
     *
     * 放大后的图片比容器多出来的部分，左右（上下）各一半，所以可拖动的余量也是各一半。
     */
    fun maxTranslation(scale: Float, containerPx: Int): Float {
        if (scale <= MIN_SCALE || containerPx <= 0) return 0f
        return containerPx * (scale - MIN_SCALE) / 2f
    }

    /** 把单轴平移量夹到 ±[maxTranslation]；未放大时恒为 0（不允许拖动）。 */
    fun clampTranslation(value: Float, scale: Float, containerPx: Int): Float {
        val max = maxTranslation(scale, containerPx)
        if (max <= 0f) return 0f
        return value.coerceIn(-max, max)
    }

    /**
     * 双击放大时，把被点的位置拉到屏幕中心所需的平移量（已夹紧）。
     *
     * @param tapX 双击点在容器内的坐标
     * @param containerPx 容器在该轴上的像素长度
     */
    fun translationForDoubleTap(tapX: Float, containerPx: Int, scale: Float): Float {
        val center = containerPx / 2f
        return clampTranslation((center - tapX) * (scale - MIN_SCALE), scale, containerPx)
    }
}
