package com.aveline.ai.mobile.utils.text

/** 展示段的类型：正文 / 括号内的舞台提示（动作、神态、心里话）。 */
enum class ReplySegmentKind {
    TEXT,
    STAGE_DIRECTION
}

/**
 * 一个展示段：[text] 是**去掉括号后**可以直接上屏的文本。
 *
 * 舞台提示的括号在这里就被剥掉了，渲染层不需要再判断首尾字符。
 */
data class ReplySegment(
    val text: String,
    val kind: ReplySegmentKind
) {
    val isStageDirection: Boolean get() = kind == ReplySegmentKind.STAGE_DIRECTION
}

/**
 * 把一条 AI 回复切成「正文」与「舞台提示」两类展示段。
 *
 * 这里是"哪一段是括号内容"的**唯一判定处**。聊天页的三条写入/渲染路径
 * （HTTP 流式的整条回复、WS 流式的逐字气泡、Room 里的历史消息）历史上有各自的判法：
 * `ChatTextProcessor` 用正则、`ChatFlushManager` 用括号计数、`MessageBubble`
 * 用"首字符是（且尾字符是）"，于是同一条回复在三种路径下长得不一样。统一收敛到这里。
 *
 * 判定口径：
 * 1. 整段被一对括号包住（`（…）` / `(…)`）→ 舞台提示，去掉这对括号；
 * 2. 一段里既有括号又有其它文字 → 括号内是舞台提示，括号外是正文；
 * 3. 只有半边括号（左括号没闭合 / 右括号没开头）→ 仍按舞台提示处理并去掉那半边。
 *    这种碎片来自"流式或断句在括号中间切了一刀"，不修就会在气泡上留一个孤零零的括号。
 * 4. 代码块 / 公式 / 表格等整块保留的结构不参与括号切分（里面的括号是代码，不是动作描写）。
 * 5. 行内公式与行内代码里的括号同样不切：`$f(x)$`、`\(…\)`、`` `foo(bar)` `` 整段留在正文里。
 * 6. 括号本身长得像公式的也不切：`e^(iθ)`（上标后的括号）、`sin(x)`（紧贴 ASCII 标识符、
 *    内部没有中文）。这一条是为了兜住模型用**纯文本**写的公式——它们没有 `$` 标记，
 *    走到这里时和动作描写长得一模一样，只能靠形状区分。
 *
 * 括号内的文本不再递归拆分：`（他把外套（灰色的那件）披上）` 整体是一个舞台提示。
 */
object ReplySegmenter {

    /**
     * 公式 / 代码的特征字符：括号内出现任一，就说明这对括号属于数学或代码，不是动作描写。
     *
     * 不含 `-`：中文行文里连字符与破折号太常见，放进来会误伤正文。
     */
    private const val MATH_CHARS = "^_={}\\$|<>*/+"

    /**
     * 分段入口。
     *
     * @param text 消息原文（可以含时间戳、句末句号，内部会先清洗）
     * @param forceStageDirection 该消息在库里就标成了撤回/旁白（`messageType == "retraction"`）。
     *   此时整条都当成舞台提示 —— 历史数据里这类文本的括号早已被剥掉，按文本判不出来。
     */
    fun segment(text: String, forceStageDirection: Boolean = false): List<ReplySegment> {
        val blocks = TextSegmenter.displayBlocks(text)
        if (blocks.isEmpty()) return emptyList()

        if (forceStageDirection) {
            val joined = blocks.joinToString("\n") { it.text }
            return listOf(ReplySegment(stripOuterParens(joined) ?: joined, ReplySegmentKind.STAGE_DIRECTION))
        }

        val segments = mutableListOf<ReplySegment>()
        for (block in blocks) {
            if (block.atomic) {
                // 代码块 / 公式 / 表格：整块当正文，不把里面的括号当动作描写
                segments += ReplySegment(block.text, ReplySegmentKind.TEXT)
            } else {
                segments += splitBlock(block.text)
            }
        }
        return segments
    }

    /**
     * 只有半边括号时剥掉它，返回剥完的文本；括号本来就配平或压根没有括号时返回 null。
     *
     * 供"已经把括号吃掉的旧数据"兜底：`（低头…` 与 `…拉好）` 都会被还原成干净的舞台提示文本。
     */
    fun stripLoneParen(text: String): String? {
        val trimmed = text.trim()
        if (trimmed.length < 2) return null
        if (isOpen(trimmed.first()) && trimmed.drop(1).none { isClose(it) }) {
            return trimmed.drop(1).trim().takeIf { it.isNotEmpty() }
        }
        if (isClose(trimmed.last()) && trimmed.dropLast(1).none { isOpen(it) }) {
            return trimmed.dropLast(1).trim().takeIf { it.isNotEmpty() }
        }
        return null
    }

    /** 整段被一对括号包住时返回括号内文本；否则返回 null。 */
    private fun stripOuterParens(text: String): String? {
        val trimmed = text.trim()
        if (trimmed.length < 2 || !isOpen(trimmed.first())) return stripLoneParen(trimmed)
        return if (findClosing(trimmed, 0) == trimmed.lastIndex) {
            trimmed.substring(1, trimmed.lastIndex).trim().takeIf { it.isNotEmpty() }
        } else {
            stripLoneParen(trimmed)
        }
    }

    /** 切一个非结构块：括号内→舞台提示，括号外→正文。 */
    private fun splitBlock(block: String): List<ReplySegment> {
        val trimmed = block.trim()
        if (trimmed.isEmpty()) return emptyList()

        // 行内公式 / 行内代码占用的区间：这些字符不参与括号配对
        val protected = protectedMask(trimmed)

        val segments = mutableListOf<ReplySegment>()
        val buffer = StringBuilder()
        var sawPair = false
        var index = 0

        while (index < trimmed.length) {
            val ch = trimmed[index]
            if (protected[index] || !isOpen(ch)) {
                buffer.append(ch)
                index++
                continue
            }
            val closeIndex = findClosing(trimmed, index)
            if (closeIndex < 0) {
                // 半截左括号：先当普通字符攒着，整块处理完再判断是不是被切开的舞台提示
                buffer.append(ch)
                index++
                continue
            }
            if (looksLikeFormula(trimmed.substring(index + 1, closeIndex), trimmed.getOrNull(index - 1))) {
                // 公式/代码的括号：连同括号一起留在正文里，不拆段
                buffer.append(ch)
                index++
                continue
            }
            sawPair = true
            val before = buffer.toString().trim()
            if (before.isNotEmpty()) segments += ReplySegment(before, ReplySegmentKind.TEXT)
            buffer.clear()
            val inner = trimmed.substring(index + 1, closeIndex).trim()
            if (inner.isNotEmpty()) segments += ReplySegment(inner, ReplySegmentKind.STAGE_DIRECTION)
            index = closeIndex + 1
        }

        val tail = buffer.toString().trim()
        if (tail.isNotEmpty()) segments += ReplySegment(tail, ReplySegmentKind.TEXT)

        if (!sawPair) {
            val lone = stripLoneParen(trimmed)
            if (lone != null) {
                return listOf(ReplySegment(lone, ReplySegmentKind.STAGE_DIRECTION))
            }
        }
        return segments
    }

    /** 从 [start]（一个左括号）找到与之配对的右括号下标；找不到返回 -1。 */
    private fun findClosing(text: String, start: Int): Int {
        var depth = 0
        var index = start
        while (index < text.length) {
            val ch = text[index]
            if (isOpen(ch)) {
                depth++
            } else if (isClose(ch)) {
                depth--
                if (depth == 0) return index
            }
            index++
        }
        return -1
    }

    /**
     * 标出"不能被括号切分"的字符区间：行内代码 `` `…` ``、行内公式 `$…$` / `$$…$$`、
     * LaTeX 定界符 `\(…\)` / `\[…\]`。
     *
     * 只标区间、不改文本：命中区间的 `(` 在 [splitBlock] 里按普通字符处理，于是
     * `$f(x)$` 整段留在同一个正文段里，再交给 Markdown 渲染器当公式解析。
     * 未闭合的标记一直保护到块尾——流式阶段可能只收到一半，先保护起来比事后补救安全。
     */
    private fun protectedMask(text: String): BooleanArray {
        val mask = BooleanArray(text.length)
        var index = 0
        while (index < text.length) {
            val ch = text[index]
            val openLength: Int
            val close: String
            when {
                ch == '`' -> {
                    openLength = 1
                    close = "`"
                }
                ch == '$' && !isEscaped(text, index) -> {
                    if (index + 1 < text.length && text[index + 1] == '$') {
                        openLength = 2
                        close = "$$"
                    } else {
                        openLength = 1
                        close = "$"
                    }
                }
                ch == '\\' && index + 1 < text.length && (text[index + 1] == '(' || text[index + 1] == '[') -> {
                    openLength = 2
                    close = if (text[index + 1] == '(') "\\)" else "\\]"
                }
                else -> {
                    index++
                    continue
                }
            }
            val end = findDelimiterEnd(text, index + openLength, close)
            for (i in index..end) mask[i] = true
            index = end + 1
        }
        return mask
    }

    /** 从 [from] 开始找 [delimiter]，返回其最后一个字符的下标；找不到返回文本末尾（整块保护）。 */
    private fun findDelimiterEnd(text: String, from: Int, delimiter: String): Int {
        val found = text.indexOf(delimiter, from)
        return if (found < 0) text.lastIndex else found + delimiter.length - 1
    }

    /** 判断 [index] 处的字符是否被反斜杠转义（`\$` 是字面美元符号，不是公式边界）。 */
    private fun isEscaped(text: String, index: Int): Boolean {
        var backslashes = 0
        var cursor = index - 1
        while (cursor >= 0 && text[cursor] == '\\') {
            backslashes++
            cursor--
        }
        return backslashes % 2 == 1
    }

    /**
     * 这对括号是不是公式 / 代码，而不是动作描写。
     *
     * 模型经常用**纯文本**写公式（`e^(iθ)`、`sin(x)`），它们没有任何 `$` 标记，
     * 走到这里时和 `（笑）` 长得一模一样，只能按形状判：
     * - 紧跟在 `^` / `_` 后面 → 上标 / 下标，`e^(iθ)`；
     * - 括号内有 `^ _ = { } \ $ | < > * / +` 任一字符 → 公式或代码；
     * - 括号内只有数字 / 空格 / 时间与小数点 → `(2024)`、`(10:23)`、`(3.14)`，不是动作；
     * - 紧贴在 ASCII 标识符后面、且内部没有中文 → 函数调用，`f(x)`、`cos(θ)`。
     */
    private fun looksLikeFormula(inner: String, prev: Char?): Boolean {
        if (inner.isEmpty()) return false
        if (prev == '^' || prev == '_') return true
        if (inner.any { it in MATH_CHARS }) return true
        if (inner.all { isAsciiLetterOrDigit(it) || it in " .:-" } && inner.any { isAsciiDigit(it) }) return true
        return prev != null && isAsciiLetterOrDigit(prev) && inner.none { isCjkLetter(it) }
    }

    private fun isAsciiDigit(ch: Char): Boolean = ch in '0'..'9'

    private fun isAsciiLetterOrDigit(ch: Char): Boolean =
        ch in 'a'..'z' || ch in 'A'..'Z' || isAsciiDigit(ch)

    /** 只认汉字区段：`（笑）` 里的"笑"算中文，`cos(θ)` 里的"θ"不算。 */
    private fun isCjkLetter(ch: Char): Boolean =
        ch.code in 0x3400..0x4DBF || ch.code in 0x4E00..0x9FFF || ch.code in 0xF900..0xFAFF

    private fun isOpen(ch: Char): Boolean = ch == '（' || ch == '('

    private fun isClose(ch: Char): Boolean = ch == '）' || ch == ')'
}
