package com.aveline.ai.mobile.presentation.chat

import com.aveline.ai.mobile.domain.models.Message
import com.aveline.ai.mobile.utils.text.TextSegmenter

/**
 * 会话列表预览文本构造器（单一真源）。
 *
 * 预览副标题按 QQ / 微信消息列表的口径：只展示"最后一条看得见的内容"，不区分发送方，
 * 也不加"我: "前缀。
 *
 * - 文本消息：直接取 text，超长截断
 * - 图片消息：显示 "[图片]"
 * - 表情包（`/output/image/memes/` 下的图）：显示 "[表情]"
 * - 视频消息：显示 "[视频]"
 * - 只剩媒体标签的气泡（例如 AI 只回了一个 `[MEME]`）：按标签类型给占位，
 *   不能返回空串 —— 否则会话列表会出现一行没有副标题的空白项
 * - 真正空的气泡（AI 回复占位、媒体链连接点）：返回空串，由调用方回退到上一条可见消息
 *
 * 历史聊天里 DB 存的是含 [MEME]/[IMG]/[BM]/[VOICE] 媒体标签的原始文本，
 * 预览前需要剥离这些标签。
 *
 * 同时被多处复用，避免逻辑分叉：
 * - [ChatIncomingMessageHandler]：进入聊天、收到新消息时实时写预览
 * - [com.aveline.ai.mobile.presentation.conversations.ConversationListViewModel]：
 *   冷启动从本地聊天历史重建全部预览（因此 DB 里的旧预览值也会被重建覆盖，
 *   这里加的清洗规则无需数据迁移即可对历史数据生效）
 */
object ChatPreviewBuilder {
    /** 预览文本最大长度（超出截断，加省略号） */
    const val PREVIEW_MAX_LEN = 60

    /**
     * 重建预览时回看的消息条数。
     *
     * 不能只看最后一条：AI 回复的表情包/图片链会插入多条空气泡当连接点，
     * 「正在输入」占位本身也是空文本，最后一条经常是空的，必须往前找到第一条
     * 真正可见的消息。
     */
    const val PREVIEW_LOOKBACK = 20

    private val mediaTagRegex = Regex(
        """[\[［](?:MEME|IMG|BM|VOICE|VIDEO)(?:[：:][^\]］]*)?[\]］]""",
        RegexOption.IGNORE_CASE
    )

    /** 逐类标签单独匹配，用于空气泡（只剩标签）判断该显示哪种占位。 */
    private val memeTagRegex = Regex("""[\[［]MEME(?:[：:][^\]］]*)?[\]］]""", RegexOption.IGNORE_CASE)
    private val videoTagRegex = Regex("""[\[［]VIDEO(?:[：:][^\]］]*)?[\]］]""", RegexOption.IGNORE_CASE)
    private val voiceTagRegex = Regex("""[\[［]VOICE(?:[：:][^\]］]*)?[\]］]""", RegexOption.IGNORE_CASE)
    private val imageTagRegex = Regex("""[\[［](?:IMG|BM)(?:[：:][^\]］]*)?[\]］]""", RegexOption.IGNORE_CASE)

    /**
     * 由消息字段构造列表预览文本。
     *
     * @param text 原始消息文本（可能含媒体标签）
     * @param messageType 消息类型（"image" 视为图片，"video" 视为视频，"attachment" 视为多附件）
     * @param imageUrl 图片地址（非空视为图片）
     * @param videoUrl 视频地址（非空视为视频）
     * @return 预览文本；真正空的气泡返回空串
     */
    fun buildPreviewText(
        text: String,
        messageType: String,
        imageUrl: String? = null,
        videoUrl: String? = null
    ): String {
        // 剥离媒体标签（DB 存的是含标签的原始文本），
        // 再按聊天页同一套规则清掉句末多余标点——会话列表预览与聊天气泡观感一致，
        // 不出现「都快十点了。」这类句末句号
        val cleanedText = TextSegmenter.stripTrailingPunctuation(
            mediaTagRegex.replace(text, "").replace("\n", " ")
        ).trim()
        val raw = when {
            messageType == "video" || !videoUrl.isNullOrBlank() -> "[视频]"
            // 多附件消息优先显示用户文案；纯附件（没打字）统一显示 [附件]。
            // 不能落到下面的 imageUrl 分支：多附件消息的 imageUrl 只是第一张图的兼容副本，
            // 「1 张图 + 1 个 PDF」会被误报成纯图片消息。
            messageType == "attachment" ->
                cleanedText.ifEmpty { "[附件]" }
            messageType == "image" || !imageUrl.isNullOrBlank() ->
                if (isMemeUrl(imageUrl)) "[表情]" else "[图片]"
            // 只剩标点的正文（"……[MEME]" 剥掉标签后是 "……"）不算可见内容，
            // 交给媒体标签兜底，避免列表显示一行 "……"
            cleanedText.isNotEmpty() && hasVisibleContent(cleanedText) -> cleanedText
            else -> labelForMediaTags(text).ifEmpty { cleanedText }
        }
        return truncate(raw)
    }

    /**
     * 从一组消息里找出"最后一条能显示的预览"。
     *
     * 会话列表的副标题语义是"最后一条看得见的内容"，而不是"DB 里最后一行"：
     * AI 回复占位（等回复时 text 为空）、媒体链上的空气泡都没有内容可展示，
     * 直接取最后一条会让整行变成空白。这里从后往前找第一条能出预览的消息。
     *
     * @return 预览快照；整组消息都没有可见内容时返回 null
     */
    fun buildLatestPreview(messages: List<Message>): PreviewEntry? {
        for (index in messages.indices.reversed()) {
            val message = messages[index]
            val text = buildPreviewText(
                text = message.text,
                messageType = message.messageType,
                imageUrl = message.imageUrl,
                videoUrl = message.videoUrl
            )
            if (text.isNotBlank()) {
                return PreviewEntry(message = message, text = text)
            }
        }
        return null
    }

    /** 后端表情包静态资源统一落在 /output/image/memes/ 下（与气泡渲染同一判据）。 */
    private fun isMemeUrl(url: String?): Boolean =
        url?.contains("/memes/", ignoreCase = true) == true

    /** 正文里是否还有"看得见"的字符（字母 / 数字 / 汉字），纯标点与省略号不算。 */
    private fun hasVisibleContent(value: String): Boolean =
        value.any { it.isLetterOrDigit() }

    /** 空气泡里只剩媒体标签时，按标签类型给出与聊天页一致的占位文案。 */
    private fun labelForMediaTags(text: String): String = when {
        memeTagRegex.containsMatchIn(text) -> "[表情]"
        videoTagRegex.containsMatchIn(text) -> "[视频]"
        voiceTagRegex.containsMatchIn(text) -> "[语音]"
        imageTagRegex.containsMatchIn(text) -> "[图片]"
        else -> ""
    }

    private fun truncate(value: String): String =
        if (value.length > PREVIEW_MAX_LEN) {
            value.take(PREVIEW_MAX_LEN - 1) + "…"
        } else {
            value
        }
}

/**
 * 会话列表预览快照：真正用于展示的那条消息 + 它的预览文本。
 *
 * 保留 [message] 是为了让调用方用"这条消息自己的 sessionId / timestamp"落库，
 * 而不是用当前会话的——等回复时展示的是用户刚发的那条，时间也应该是它的时间。
 */
data class PreviewEntry(
    val message: Message,
    val text: String
)
