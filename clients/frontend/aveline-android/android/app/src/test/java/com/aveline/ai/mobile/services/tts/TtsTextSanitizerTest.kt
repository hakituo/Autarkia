package com.aveline.ai.mobile.services.tts

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 直连 TTS 文本清洗回归测试。
 *
 * 另有一条 JVM 单测覆盖不到的坑：Android ICU 正则不接受裸 `}`，
 * BRACKETED 里的右括号必须写成 `\}` —— 曾因裸 `}` 在类初始化时抛
 * PatternSyntaxException -> ExceptionInInitializerError，点播放语音必闪退。
 * 该约束由 tests/scripts/voice/verify_tts_direct_and_local_media.py 静态断言。
 */
class TtsTextSanitizerTest {

    @Test
    fun `媒体标签被剥离`() {
        assertEquals("你好 呀", TtsTextSanitizer.clean("你好[MEME]呀"))
        assertEquals("看图", TtsTextSanitizer.clean("[IMG: abc]看图"))
        assertEquals("来了", TtsTextSanitizer.clean("[VIDEO]来了"))
    }

    @Test
    fun `括号动作描写被剥离`() {
        assertEquals("今天天气不错", TtsTextSanitizer.clean("（笑）今天天气不错"))
        assertEquals("今天天气不错", TtsTextSanitizer.clean("今天天气不错(开心)"))
        assertEquals("好", TtsTextSanitizer.clean("好{摸鱼中}"))
        assertEquals("好", TtsTextSanitizer.clean("好[斜眼]"))
    }

    @Test
    fun `参数标记被剥离`() {
        assertEquals("你好", TtsTextSanitizer.clean("[speed=1.2]你好"))
        assertEquals("别急", TtsTextSanitizer.clean("别急[style=happy]"))
    }

    @Test
    fun `话题标签被剥离`() {
        assertEquals("来 了吗", TtsTextSanitizer.clean("来#运动#了吗"))
    }

    @Test
    fun `重复标点收敛`() {
        assertEquals("好！", TtsTextSanitizer.clean("好！！！"))
        assertEquals("走吗？", TtsTextSanitizer.clean("走吗？？？"))
    }

    @Test
    fun `空白被压缩`() {
        assertEquals("你好 呀", TtsTextSanitizer.clean("你好   呀"))
    }

    @Test
    fun `多轮清洗处理混合括号`() {
        assertEquals("走", TtsTextSanitizer.clean("（笑）[跳]走"))
        // 与后端 remove_bracketed 同口径：嵌套括号第一轮剥到内层，
        // 残留的孤立右括号不属于任何配对，不做臆测性删除
        assertEquals("）笑", TtsTextSanitizer.clean("（笑（无奈））笑"))
    }

    @Test
    fun `纯空白与空串返回空`() {
        assertEquals("", TtsTextSanitizer.clean(""))
        assertEquals("", TtsTextSanitizer.clean("   "))
        assertEquals("", TtsTextSanitizer.clean("（只括号）"))
    }

    @Test
    fun `普通文本不被误伤`() {
        val text = "今天 3+2=5，对吧？"
        assertEquals(text, TtsTextSanitizer.clean(text))
    }
}
