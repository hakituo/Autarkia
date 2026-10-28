package com.aveline.ai.mobile.presentation.study

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.components.LatexMath
import com.aveline.ai.mobile.presentation.components.MarkdownInlineText
import com.aveline.ai.mobile.presentation.components.claimHorizontalContentGesture
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.Line
import com.aveline.ai.mobile.presentation.theme.TextBody
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import com.aveline.ai.mobile.utils.text.CodeHighlighter
import com.aveline.ai.mobile.utils.text.MarkdownBlock
import com.aveline.ai.mobile.utils.text.MarkdownBlockParser
import com.aveline.ai.mobile.utils.text.MarkdownInlineNode

/**
 * 聊天与学习文档共用的 Markdown renderer。
 *
 * 全文先通过 [MarkdownBlockParser] 解析成块 AST，并用 `remember(text)` 缓存；标题、列表、引用、表格 cell
 * 都复用 [MarkdownInlineText]，因此粗体、斜体、删除线与行内 LaTeX 的行为一致。代码 fence 优先于数学块，
 * `$$...$$` 同时支持多行和单行形式。
 *
 * @param bodyStyle 正文样式：聊天传 bodyLarge，笔记 / 日记传 15.5–16sp 的阅读样式。
 * @param documentStyle 长文模式：标题、列表符号、公式块改成笔记阅读稿的中性排版，
 *   不把强调色用在标题和项目符号上；聊天流仍保持默认样式。
 */
@Composable
fun NotesMarkdownRenderer(
    text: String,
    bodyStyle: TextStyle = MaterialTheme.typography.bodyMedium,
    documentStyle: Boolean = false
) {
    val blocks = remember(text) { MarkdownBlockParser.parse(text) }

    Column(
        modifier = Modifier.fillMaxWidth(),
        // 长文模式按阅读稿放宽段落 / 列表项间距（设计稿列表项之间 10px），聊天流保持紧凑。
        verticalArrangement = Arrangement.spacedBy(if (documentStyle) 10.dp else 4.dp),
    ) {
        blocks.forEach { block ->
            when (block) {
                MarkdownBlock.Blank -> Spacer(modifier = Modifier.height(2.dp))
                MarkdownBlock.Divider -> Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(1.dp)
                        .background(Line),
                )

                is MarkdownBlock.Paragraph -> MarkdownInlineText(
                    nodes = block.content,
                    style = bodyStyle,
                    color = TextBody,
                    modifier = Modifier.fillMaxWidth(),
                )

                is MarkdownBlock.Heading -> RenderHeading(block, documentStyle)
                is MarkdownBlock.Bullet -> Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text(
                        text = if (documentStyle) "·" else "•",
                        style = bodyStyle,
                        color = if (documentStyle) TextTertiary else Accent,
                        modifier = Modifier.alignByBaseline(),
                    )
                    MarkdownInlineText(
                        nodes = block.content,
                        style = bodyStyle,
                        color = TextBody,
                        modifier = Modifier
                            .weight(1f)
                            .alignByBaseline(),
                    )
                }

                is MarkdownBlock.Quote -> RenderMarkdownQuote(block)
                is MarkdownBlock.Math -> RenderMathBlock(block.formula, documentStyle)
                is MarkdownBlock.Code -> RenderCodeBlock(block.code, block.language)
                is MarkdownBlock.Table -> RenderTable(block.rows)
            }
        }
    }
}

/** 文档模式的小标题：17sp SemiBold，不带强调色，靠字重分层。 */
@Composable
private fun RenderHeading(block: MarkdownBlock.Heading, documentStyle: Boolean) {
    val style = if (documentStyle) {
        when (block.level) {
            1 -> TextStyle(fontSize = 24.sp, lineHeight = 32.sp, fontWeight = FontWeight.SemiBold)
            2 -> TextStyle(fontSize = 17.sp, lineHeight = 24.sp, fontWeight = FontWeight.SemiBold)
            3 -> TextStyle(fontSize = 16.sp, lineHeight = 23.sp, fontWeight = FontWeight.SemiBold)
            else -> TextStyle(fontSize = 15.sp, lineHeight = 22.sp, fontWeight = FontWeight.Medium)
        }
    } else {
        when (block.level) {
            1 -> MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.Bold)
            2 -> MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Bold)
            3 -> MaterialTheme.typography.titleSmall.copy(fontWeight = FontWeight.SemiBold)
            else -> MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.SemiBold)
        }
    }
    val color = if (!documentStyle && block.level == 3) Accent else TextPrimary

    if (block.level <= 2) Spacer(modifier = Modifier.height(4.dp))
    MarkdownInlineText(
        nodes = block.content,
        style = style,
        color = color,
        modifier = Modifier.fillMaxWidth(),
    )
}

/** 使用类似 ChatGPT 的竖线层级呈现引用与子回复。 */
@Composable
private fun RenderMarkdownQuote(quote: MarkdownBlock.Quote) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(IntrinsicSize.Min)
            .padding(start = ((quote.depth - 1) * 12).dp, top = 4.dp, bottom = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        repeat(quote.depth.coerceAtMost(3)) {
            Box(
                modifier = Modifier
                    .width(3.dp)
                    .fillMaxHeight()
                    .clip(RoundedCornerShape(2.dp))
                    .background(Color(0x4DFFFFFF)),
            )
        }
        MarkdownInlineText(
            nodes = quote.content,
            style = MaterialTheme.typography.bodyMedium,
            color = TextSecondary,
            modifier = Modifier.weight(1f),
        )
    }
}

/** 渲染块级 LaTeX 公式；超宽公式可独立横向滚动。文档模式去掉灰底，改成上下两条细线。 */
@Composable
private fun RenderMathBlock(formula: String, documentStyle: Boolean) {
    if (formula.isBlank()) return

    if (documentStyle) {
        Column(modifier = Modifier.fillMaxWidth()) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(1.dp)
                    .background(Line),
            )
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .claimHorizontalContentGesture()
                    .padding(vertical = 14.dp),
                // 短公式居中；超宽公式仍从左边开始，可以独立横滑。
                contentAlignment = Alignment.Center
            ) {
                Row(modifier = Modifier.horizontalScroll(rememberScrollState())) {
                    LatexMath(formula = formula, displayMode = true)
                }
            }
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(1.dp)
                    .background(Line),
            )
        }
        return
    }

    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(Color(0x1A38BDF8))
            .claimHorizontalContentGesture()
            .padding(12.dp),
    ) {
        Row(modifier = Modifier.horizontalScroll(rememberScrollState())) {
            LatexMath(
                formula = formula,
                displayMode = true,
            )
        }
    }
}

/** 渲染代码块：头部显示语言标签，正文按语言做语法高亮。 */
@Composable
private fun RenderCodeBlock(code: String, languageTag: String) {
    val language = remember(code, languageTag) { CodeHighlighter.resolveLanguage(languageTag, code) }
    val highlighted = remember(code, language) { CodeHighlighter.highlightCode(code, language) }
    val languageLabel = CodeHighlighter.displayName(language)

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(Color(0x33000000))
            .claimHorizontalContentGesture(),
    ) {
        if (languageLabel.isNotEmpty()) {
            Text(
                text = languageLabel,
                style = MaterialTheme.typography.labelSmall,
                color = Accent.copy(alpha = 0.8f),
                fontFamily = FontFamily.Monospace,
                modifier = Modifier.padding(top = 8.dp, start = 12.dp),
            )
        }
        Text(
            text = highlighted,
            style = MaterialTheme.typography.bodySmall,
            color = Accent,
            fontFamily = FontFamily.Monospace,
            modifier = Modifier
                .horizontalScroll(rememberScrollState())
                .padding(12.dp),
        )
    }
}

/** 渲染已解析的 GFM 表格；对齐分隔行已在 parser 阶段剔除。 */
@Composable
private fun RenderTable(rows: List<List<List<MarkdownInlineNode>>>) {
    if (rows.isEmpty()) return
    val maxColumnCount = rows.maxOfOrNull { it.size } ?: return
    val tableWidth = maxOf(280, maxColumnCount * 136).dp

    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(Color(0x14000000))
            .claimHorizontalContentGesture(),
    ) {
        Column(
            modifier = Modifier
                .horizontalScroll(rememberScrollState())
                .width(tableWidth),
        ) {
            rows.forEachIndexed { index, cells ->
                Row(
                    modifier = Modifier
                        .width(tableWidth)
                        .padding(horizontal = 10.dp, vertical = 6.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    repeat(maxColumnCount) { columnIndex ->
                        MarkdownInlineText(
                            nodes = cells.getOrNull(columnIndex).orEmpty(),
                            style = MaterialTheme.typography.labelSmall.copy(
                                fontWeight = if (index == 0) FontWeight.Bold else FontWeight.Normal,
                            ),
                            color = if (index == 0) Accent else TextSecondary,
                            modifier = Modifier.width(128.dp),
                        )
                    }
                }
                if (index < rows.size - 1) {
                    Box(
                        modifier = Modifier
                            .width(tableWidth)
                            .height(1.dp)
                            .background(Color(0x1AFFFFFF)),
                    )
                }
            }
        }
    }
}
