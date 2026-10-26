package com.aveline.ai.mobile.presentation.mall

import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 商城类目 Tab：纯文字，选中加粗变白、未选灰色，和学习 / 生活的 Tab 同一套语言。
 *
 * 8 个类目在窄屏放不下，整行横向滚动；选中项变化时把它滚进可视区。
 */
@Composable
internal fun MallCategoryTabs(
    labels: List<String>,
    selectedIndex: Int,
    onSelect: (Int) -> Unit,
    modifier: Modifier = Modifier
) {
    val scrollState = rememberScrollState()
    val tabStridePx = with(LocalDensity.current) { TAB_STRIDE.roundToPx() }

    LaunchedEffect(selectedIndex) {
        scrollState.animateScrollTo(selectedIndex * tabStridePx)
    }

    Row(
        modifier = modifier
            .fillMaxWidth()
            .horizontalScroll(scrollState)
            .padding(horizontal = 20.dp),
        horizontalArrangement = Arrangement.spacedBy(20.dp)
    ) {
        labels.forEachIndexed { index, label ->
            val selected = index == selectedIndex
            Box(
                modifier = Modifier
                    .height(36.dp)
                    .clickable { onSelect(index) },
                contentAlignment = Alignment.Center
            ) {
                Text(
                    text = label,
                    fontSize = 15.sp,
                    fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
                    color = if (selected) TextPrimary else TextTertiary,
                    maxLines = 1
                )
            }
        }
    }
}

/** 选中项滚动定位的估算步长（两字标签宽度 + 间距），只用于把 Tab 带进视野。 */
private val TAB_STRIDE = 64.dp
