package com.aveline.ai.mobile.utils.text

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * 覆盖 [ReplySegmenter]：聊天页"哪里算括号内容"的唯一判定。
 *
 * 这些用例钉住的是**用户可见口径**——括号里的动作描写走撤回样式，其余走正文。
 * 任何一条挂了，说明聊天页又会出现"一半居中一半靠左"或者气泡上留半个括号。
 */
class ReplySegmenterTest {

    private fun assertSegments(
        expected: List<Pair<String, ReplySegmentKind>>,
        actual: List<ReplySegment>
    ) {
        assertEquals(expected.map { it.first }, actual.map { it.text })
        assertEquals(expected.map { it.second }, actual.map { it.kind })
    }

    @Test
    fun `整条被中文括号包住时整段是舞台提示并去掉括号`() {
        assertSegments(
            listOf("把百褶裙套上，站起来系好，披上大衣" to ReplySegmentKind.STAGE_DIRECTION),
            ReplySegmenter.segment("（把百褶裙套上，站起来系好，披上大衣）")
        )
    }

    @Test
    fun `半角括号与中文括号同口径`() {
        assertSegments(
            listOf("摸了摸头" to ReplySegmentKind.STAGE_DIRECTION),
            ReplySegmenter.segment("(摸了摸头)")
        )
    }

    @Test
    fun `括号后面还有台词时拆成舞台提示加正文`() {
        assertSegments(
            listOf(
                "低头看了眼光着的腿" to ReplySegmentKind.STAGE_DIRECTION,
                "哦" to ReplySegmentKind.TEXT
            ),
            ReplySegmenter.segment("（低头看了眼光着的腿）哦")
        )
    }

    @Test
    fun `台词后面的括号动作也单独成段`() {
        assertSegments(
            listOf(
                "好呀" to ReplySegmentKind.TEXT,
                "笑" to ReplySegmentKind.STAGE_DIRECTION
            ),
            ReplySegmenter.segment("好呀（笑）")
        )
    }

    @Test
    fun `被切掉右括号的碎片仍按舞台提示渲染`() {
        // 流式/断句在括号中间切了一刀，气泡上只剩左括号
        assertSegments(
            listOf("低头，裙子底下露出一截黑" to ReplySegmentKind.STAGE_DIRECTION),
            ReplySegmenter.segment("（低头，裙子底下露出一截黑")
        )
    }

    @Test
    fun `被切掉左括号的碎片仍按舞台提示渲染`() {
        // 这是截图里 "把黑打底裤提上，拉好）" 那一条的形态
        assertSegments(
            listOf("把黑打底裤提上，拉好" to ReplySegmentKind.STAGE_DIRECTION),
            ReplySegmenter.segment("把黑打底裤提上，拉好）")
        )
    }

    @Test
    fun `历史消息标了撤回但括号已被吃掉时整条仍是舞台提示`() {
        assertSegments(
            listOf("穿上了" to ReplySegmentKind.STAGE_DIRECTION),
            ReplySegmenter.segment("穿上了", forceStageDirection = true)
        )
    }

    @Test
    fun `多行回复按行拆出正文与舞台提示`() {
        assertSegments(
            listOf(
                "把百褶裙套上" to ReplySegmentKind.STAGE_DIRECTION,
                "穿好了" to ReplySegmentKind.TEXT,
                "镜头往下移" to ReplySegmentKind.STAGE_DIRECTION
            ),
            ReplySegmenter.segment("（把百褶裙套上）\n穿好了\n（镜头往下移）")
        )
    }

    @Test
    fun `嵌套括号整体算一段舞台提示`() {
        assertSegments(
            listOf("他把外套（灰色的那件）披上" to ReplySegmentKind.STAGE_DIRECTION),
            ReplySegmenter.segment("（他把外套（灰色的那件）披上）")
        )
    }

    @Test
    fun `代码块里的括号是代码不是动作描写`() {
        val code = "```kotlin\nfun f(a: Int) { }\n```"
        val segments = ReplySegmenter.segment(code)
        assertEquals(1, segments.size)
        assertEquals(ReplySegmentKind.TEXT, segments[0].kind)
        assertEquals(code, segments[0].text)
    }

    @Test
    fun `括号出现在句子中间且没闭合时保持正文原样`() {
        val text = "价格（元"
        val segments = ReplySegmenter.segment(text)
        assertEquals(1, segments.size)
        assertEquals(ReplySegmentKind.TEXT, segments[0].kind)
        assertEquals(text, segments[0].text)
    }

    @Test
    fun `纯文本公式里的括号不切成撤回行`() {
        // 模型用裸 ^ 写公式、没有 $ 标记时，走到这里和动作描写长得一模一样
        assertSegments(
            listOf("e^(iθ)" to ReplySegmentKind.TEXT),
            ReplySegmenter.segment("e^(iθ)")
        )
    }

    @Test
    fun `函数调用形态的括号留在正文里`() {
        assertSegments(
            listOf("sin(x) 的导数是 cos(x)" to ReplySegmentKind.TEXT),
            ReplySegmenter.segment("sin(x) 的导数是 cos(x)")
        )
    }

    @Test
    fun `行内公式与行内代码里的括号不参与切分`() {
        listOf(
            "\$f(x)=x^2\$",
            "\\sin(\\theta)",
            "\\(\\frac{a}{b}\\)",
            "`foo(bar)`",
        ).forEach { text ->
            val segment = ReplySegmenter.segment(text).single()
            assertEquals(text, segment.text)
            assertEquals(ReplySegmentKind.TEXT, segment.kind)
        }
    }

    @Test
    fun `公式后面紧跟动作描写时仍然分开`() {
        assertSegments(
            listOf(
                "e^(iθ)" to ReplySegmentKind.TEXT,
                "笑" to ReplySegmentKind.STAGE_DIRECTION
            ),
            ReplySegmenter.segment("e^(iθ)（笑）")
        )
    }

    @Test
    fun `括号里是年份或时间时不按动作描写渲染`() {
        assertSegments(
            listOf("成立于(2024)年" to ReplySegmentKind.TEXT),
            ReplySegmenter.segment("成立于(2024)年")
        )
    }

    @Test
    fun `只有半边括号时 stripLoneParen 返回去括号文本`() {
        assertEquals("低头", ReplySegmenter.stripLoneParen("（低头"))
        assertEquals("拉好", ReplySegmenter.stripLoneParen("拉好）"))
        assertNull(ReplySegmenter.stripLoneParen("（低头）"))
        assertNull(ReplySegmenter.stripLoneParen("普通一句话"))
    }

    @Test
    fun `关闭动作描写开关后括号原样留在正文里`() {
        // 设置页「动作描写」关掉后，正文里正常出现的括号不该再被改写成旁白。
        assertSegments(
            listOf("（笑）好呀" to ReplySegmentKind.TEXT),
            ReplySegmenter.segment("（笑）好呀", stageDirectionEnabled = false)
        )
    }

    @Test
    fun `关闭动作描写开关后历史撤回标记也按正文渲染`() {
        // 老消息在写库时括号已被剥掉，只能靠 messageType 兜底；
        // 开关关闭后必须连这个兜底一起失效，否则用户会看到一片居中的灰字。
        assertSegments(
            listOf("穿上了" to ReplySegmentKind.TEXT),
            ReplySegmenter.segment(
                "穿上了",
                forceStageDirection = true,
                stageDirectionEnabled = false
            )
        )
    }
}
