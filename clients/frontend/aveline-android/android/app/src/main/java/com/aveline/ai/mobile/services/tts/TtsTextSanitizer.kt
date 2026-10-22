package com.aveline.ai.mobile.services.tts

/**
 * 直连云端 TTS 的文本清洗。
 *
 * 后端 `/api/v1/media/tts` 在合成前会做一套清洗（去媒体标签、去括号动作描写、
 * 去 `[speed=1.2]` 这类标记）。直连链路绕过了后端，本地必须做同样的处理，
 * 否则会把「[MEME]」「（轻笑）」原样读出来。
 *
 * 规则与 `core/modules/voice/utils/text_processor.py` 的
 * `extract_markers` / `remove_bracketed` 保持同源语义。
 */
object TtsTextSanitizer {

    /** 媒体占位标签：[MEME] / [IMG: xxx] / [VIDEO] ...（半角/全角括号与冒号）。 */
    private val MEDIA_TAG = Regex(
        """[\[［](?:MEME|IMG|BM|VOICE|VIDEO)(?:[：:][^\]］]*)?[\]］]""",
        RegexOption.IGNORE_CASE
    )

    /** 参数标记：[speed=1.2] / [style=happy] ... */
    private val MARKER = Regex("""\[\s*[a-zA-Z_]+\s*=\s*[^\]]+\]""")

    /**
     * 括号动作描写：() （） {} []。
     *
     * 注意右括号必须转义（`\}` / `\]`）：JVM 正则允许裸写，但 Android 的 ICU
     * 正则引擎会直接抛 PatternSyntaxException —— 该异常发生在 object 类初始化阶段，
     * 会变成 ExceptionInInitializerError / NoClassDefFoundError 绕过所有
     * catch (Exception)，曾导致点播放语音必闪退。
     */
    private val BRACKETED = listOf(
        Regex("\\([^)]*\\)"),
        Regex("（[^）]*）"),
        Regex("\\{[^}]*\\}"),
        Regex("\\[[^\\]]*\\]")
    )

    /** 话题标签：#话题#。 */
    private val HASH_TOPIC = Regex("#[^#]{1,64}#")

    fun clean(text: String): String {
        if (text.isBlank()) return ""
        var value = MEDIA_TAG.replace(text, " ")
        value = MARKER.replace(value, " ")
        // 后端连续清洗 3 轮，处理嵌套括号（如「（笑（无奈））」）
        repeat(3) {
            BRACKETED.forEach { value = it.replace(value, " ") }
            value = Regex("\\s{2,}").replace(value, " ").trim()
        }
        value = HASH_TOPIC.replace(value, " ")
        // 重复标点收敛，避免云端合成出拖长音
        value = value.replace(Regex("([。！？!?])\\1+"), "\$1")
        value = value.replace(Regex("\\s{2,}"), " ")
        return value.trim()
    }
}
