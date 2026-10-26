package com.aveline.ai.mobile.presentation.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.theme.Edge
import com.aveline.ai.mobile.presentation.theme.Sand
import com.aveline.ai.mobile.presentation.theme.Surface
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import kotlinx.serialization.json.JsonElement

/**
 * 系统资源的通用 JSON 卡片。
 *
 * 渲染完全由 [buildSystemJsonNodes] 产出的节点驱动，不直接读 JSON 字段名；
 * 后端新增 / 改名 / 嵌套层级变化都只影响显示文案，不会让界面崩掉。
 */
@Composable
internal fun SystemJsonCard(
    element: JsonElement,
    modifier: Modifier = Modifier
) {
    val nodes = remember(element) { buildSystemJsonNodes(element) }
    Column(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .background(Surface)
            .border(1.dp, Color.White.copy(alpha = 0.08f), RoundedCornerShape(16.dp))
            .padding(horizontal = 16.dp, vertical = 6.dp)
    ) {
        SystemNodeList(nodes, indent = 0)
    }
}

@Composable
private fun SystemNodeList(nodes: List<SystemJsonNode>, indent: Int) {
    nodes.forEachIndexed { index, node ->
        when (node) {
            is SystemJsonNode.Row -> SystemValueRow(
                label = node.label,
                value = node.value,
                indent = indent,
                showDivider = index < nodes.lastIndex
            )
            is SystemJsonNode.Group -> SystemGroup(node, indent)
            is SystemJsonNode.Note -> Text(
                text = node.text,
                fontSize = 12.sp,
                lineHeight = 18.sp,
                color = TextTertiary,
                modifier = Modifier.padding(start = indent.dp, top = 8.dp, bottom = 8.dp)
            )
        }
    }
}

@Composable
private fun SystemValueRow(
    label: String,
    value: String,
    indent: Int,
    showDivider: Boolean
) {
    // 长值（路径、域名、UUID）横排会把键名挤没，改为上下两行
    val stacked = label.isNotBlank() && (value.length > 28 || value.contains('\n'))

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(start = indent.dp, top = 8.dp, bottom = 8.dp)
    ) {
        if (stacked) {
            Text(text = label, fontSize = 13.sp, lineHeight = 18.sp, color = TextSecondary)
            Spacer(modifier = Modifier.height(3.dp))
            Text(
                text = value,
                style = settingsMonoStyle(size = 12, color = TextPrimary)
            )
        } else {
            Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.Top) {
                if (label.isNotBlank()) {
                    Text(
                        text = label,
                        fontSize = 13.sp,
                        lineHeight = 18.sp,
                        color = TextSecondary,
                        modifier = Modifier.weight(1f)
                    )
                    Spacer(modifier = Modifier.width(12.dp))
                }
                Text(
                    text = value,
                    style = settingsMonoStyle(size = 12, color = TextPrimary),
                    textAlign = if (label.isBlank()) TextAlign.Start else TextAlign.End,
                    modifier = Modifier.weight(if (label.isBlank()) 1f else 1.2f)
                )
            }
        }
    }
    if (showDivider) SettingsRowDivider()
}

@Composable
private fun SystemGroup(group: SystemJsonNode.Group, indent: Int) {
    if (group.label.isNotBlank()) {
        Spacer(modifier = Modifier.height(10.dp))
        Text(
            text = group.label,
            fontSize = 12.5.sp,
            lineHeight = 18.sp,
            color = Sand,
            modifier = Modifier.padding(start = indent.dp)
        )
        Spacer(modifier = Modifier.height(2.dp))
    }

    if (group.itemized) {
        group.children.forEach { child ->
            if (child is SystemJsonNode.Group) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(start = (indent + 2).dp, top = 6.dp, bottom = 6.dp)
                        .clip(RoundedCornerShape(10.dp))
                        .background(Color.White.copy(alpha = 0.03f))
                        .padding(horizontal = 12.dp, vertical = 8.dp)
                ) {
                    if (child.label.isNotBlank()) {
                        Text(
                            text = child.label,
                            style = settingsMonoStyle(size = 11, color = TextTertiary)
                        )
                    }
                    SystemNodeList(child.children, indent = 0)
                }
            } else {
                Column(modifier = Modifier.padding(start = indent.dp)) {
                    SystemNodeList(listOf(child), indent = 0)
                }
            }
        }
    } else {
        Column(modifier = Modifier.padding(start = indent.dp)) {
            SystemNodeList(group.children, indent = 0)
        }
    }
}

/** 原始 JSON：等宽 + 横向滚动 + 可选中复制。 */
@Composable
internal fun SystemJsonRaw(
    element: JsonElement,
    modifier: Modifier = Modifier
) {
    val pretty = remember(element) { systemJsonPretty(element) }
    val scroll = rememberScrollState()

    Box(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(Surface)
            .border(1.dp, Edge, RoundedCornerShape(14.dp))
            .padding(14.dp)
            .horizontalScroll(scroll)
    ) {
        SelectionContainer {
            Text(
                text = pretty,
                fontFamily = FontFamily.Monospace,
                fontSize = 11.5.sp,
                lineHeight = 16.sp,
                color = TextSecondary,
                softWrap = false
            )
        }
    }
}
