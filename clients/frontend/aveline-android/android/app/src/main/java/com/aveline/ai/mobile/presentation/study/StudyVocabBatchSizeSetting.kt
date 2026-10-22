package com.aveline.ai.mobile.presentation.study

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.presentation.theme.TextSecondary

/**
 * 分组数量设置（背新词 / 复习共用）。
 *
 * @param selectedSize 当前选中的每组数量
 * @param title 分组标题
 * @param subtitle 说明文案
 * @param options 可选档位
 * @param onSizeSelected 选择回调
 */
@Composable
fun StudyVocabBatchSizeSetting(
    selectedSize: Int,
    onSizeSelected: (Int) -> Unit,
    title: String = "背新词分组",
    subtitle: String = "每次背一组；完成后可继续下一组",
    options: List<Int> = NEW_WORDS_BATCH_SIZE_OPTIONS
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Text(
            text = title,
            style = MaterialTheme.typography.labelLarge
        )
        Text(
            text = subtitle,
            style = MaterialTheme.typography.bodySmall,
            color = TextSecondary
        )
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            options.forEach { size ->
                FilterChip(
                    selected = selectedSize == size,
                    onClick = { onSizeSelected(size) },
                    label = { Text("${size} 个") }
                )
            }
        }
    }
}
