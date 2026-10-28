package com.aveline.ai.mobile.presentation.study.vocab

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.components.controls.AvelineSegmented
import com.aveline.ai.mobile.presentation.study.VOCAB_BATCH_SIZE_OPTIONS
import com.aveline.ai.mobile.presentation.theme.Edge
import com.aveline.ai.mobile.presentation.theme.SurfaceHigh
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import kotlinx.coroutines.launch

/**
 * 背词设置底部面板：出词顺序、新词每组、复习每组。
 *
 * 这三项不常改，从词汇主页挪到标题栏右侧的齿轮里，主页只留背词主流程。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun VocabSettingsSheet(
    isShuffle: Boolean,
    newWordsBatchSize: Int,
    reviewBatchSize: Int,
    onToggleOrder: () -> Unit,
    onNewWordsBatchSizeChange: (Int) -> Unit,
    onReviewBatchSizeChange: (Int) -> Unit,
    onDismiss: () -> Unit
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val scope = rememberCoroutineScope()

    ModalBottomSheet(
        // 先让面板滑下去再摘掉组合，否则下拉关闭会瞬间消失
        onDismissRequest = {
            scope.launch { sheetState.hide() }.invokeOnCompletion { onDismiss() }
        },
        sheetState = sheetState,
        containerColor = SurfaceHigh,
        contentColor = TextPrimary,
        dragHandle = {
            Box(
                modifier = Modifier
                    .padding(top = 12.dp, bottom = 6.dp)
                    .size(width = 36.dp, height = 4.dp)
                    .clip(RoundedCornerShape(2.dp))
                    .background(Edge)
            )
        }
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = 20.dp, end = 20.dp, bottom = 28.dp)
        ) {
            Text(text = "词汇", fontSize = 13.sp, color = TextTertiary)
            Spacer(modifier = Modifier.height(6.dp))
            Text(
                text = "背词设置",
                fontSize = 22.sp,
                fontWeight = FontWeight.SemiBold,
                letterSpacing = (-0.2).sp,
                color = TextPrimary
            )
            Spacer(modifier = Modifier.height(14.dp))
            SettingRow(
                label = "出词顺序",
                options = listOf("顺序", "乱序"),
                selectedIndex = if (isShuffle) 1 else 0,
                onSelect = { index ->
                    if ((index == 1) != isShuffle) onToggleOrder()
                }
            )
            SettingRow(
                label = "新词每组",
                options = VOCAB_BATCH_SIZE_OPTIONS.map { it.toString() },
                selectedIndex = VOCAB_BATCH_SIZE_OPTIONS.indexOf(newWordsBatchSize),
                onSelect = { index ->
                    VOCAB_BATCH_SIZE_OPTIONS.getOrNull(index)?.let(onNewWordsBatchSizeChange)
                }
            )
            SettingRow(
                label = "复习每组",
                options = VOCAB_BATCH_SIZE_OPTIONS.map { it.toString() },
                selectedIndex = VOCAB_BATCH_SIZE_OPTIONS.indexOf(reviewBatchSize),
                onSelect = { index ->
                    VOCAB_BATCH_SIZE_OPTIONS.getOrNull(index)?.let(onReviewBatchSizeChange)
                }
            )
        }
    }
}

@Composable
private fun SettingRow(
    label: String,
    options: List<String>,
    selectedIndex: Int,
    onSelect: (Int) -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(56.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(text = label, style = VocabRowLabelStyle)
        Spacer(modifier = Modifier.width(12.dp))
        AvelineSegmented(
            options = options,
            selectedIndex = selectedIndex.coerceAtLeast(0),
            onSelect = onSelect,
            modifier = Modifier.width(if (options.size <= 2) 120.dp else 174.dp)
        )
    }
}
