package com.aveline.ai.mobile.presentation.companion.memory

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Sort
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.domain.models.MemorySortOrder
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * 记忆搜索与筛选：关键词、只看重要、排序。
 *
 * 话题筛选在 [MemoryOverviewCard] 的 chips 上，这里不再重复放置类型下拉。
 */
@Composable
internal fun MemoryFilterBar(
    searchQuery: String,
    showImportantOnly: Boolean,
    sortOrder: MemorySortOrder,
    hasFilters: Boolean,
    resultCount: Int,
    onSearch: (String) -> Unit,
    onToggleImportantOnly: () -> Unit,
    onSortOrderChange: (MemorySortOrder) -> Unit,
    onClearFilters: () -> Unit
) {
    var showSortMenu by remember { mutableStateOf(false) }

    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        TextField(
            value = searchQuery,
            onValueChange = onSearch,
            placeholder = {
                Text("搜索记忆…", style = MaterialTheme.typography.bodyMedium, color = TextTertiary)
            },
            leadingIcon = {
                Icon(Icons.Default.Search, contentDescription = null, tint = TextTertiary)
            },
            trailingIcon = {
                if (searchQuery.isNotEmpty()) {
                    IconButton(onClick = { onSearch("") }) {
                        Icon(Icons.Default.Clear, contentDescription = "清除", tint = TextTertiary)
                    }
                }
            },
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(12.dp)),
            colors = TextFieldDefaults.colors(
                focusedContainerColor = Color(0x33000000),
                unfocusedContainerColor = Color(0x1A000000),
                focusedIndicatorColor = Color.Transparent,
                unfocusedIndicatorColor = Color.Transparent,
                cursorColor = Accent,
                focusedTextColor = TextPrimary,
                unfocusedTextColor = TextPrimary
            ),
            singleLine = true
        )

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            FilterChip(
                selected = showImportantOnly,
                onClick = onToggleImportantOnly,
                label = {
                    Text(
                        text = "只看重要",
                        color = if (showImportantOnly) Color.White else TextSecondary
                    )
                },
                leadingIcon = {
                    Icon(
                        imageVector = Icons.Default.Star,
                        contentDescription = null,
                        tint = if (showImportantOnly) Color.White else TextTertiary,
                        modifier = Modifier.size(14.dp)
                    )
                },
                colors = FilterChipDefaults.filterChipColors(
                    selectedContainerColor = MemoryImportantColor,
                    containerColor = Color(0x1A000000)
                )
            )

            Box {
                AssistChip(
                    onClick = { showSortMenu = true },
                    label = {
                        Text(getSortOrderLabel(sortOrder), color = TextSecondary)
                    },
                    leadingIcon = {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.Sort,
                            contentDescription = null,
                            tint = TextTertiary,
                            modifier = Modifier.size(15.dp)
                        )
                    },
                    trailingIcon = {
                        Icon(
                            imageVector = Icons.Default.ArrowDropDown,
                            contentDescription = null,
                            tint = TextTertiary,
                            modifier = Modifier.size(16.dp)
                        )
                    },
                    colors = AssistChipDefaults.assistChipColors(
                        containerColor = Color(0x1A000000)
                    )
                )
                DropdownMenu(
                    expanded = showSortMenu,
                    onDismissRequest = { showSortMenu = false }
                ) {
                    MemorySortOrder.entries.forEach { order ->
                        DropdownMenuItem(
                            text = {
                                Text(
                                    text = getSortOrderLabel(order),
                                    color = if (sortOrder == order) Accent else TextPrimary
                                )
                            },
                            onClick = {
                                onSortOrderChange(order)
                                showSortMenu = false
                            }
                        )
                    }
                }
            }

            Text(
                text = "$resultCount 条结果",
                style = MaterialTheme.typography.labelSmall,
                color = TextTertiary
            )

            Spacer(modifier = Modifier.size(4.dp))

            if (hasFilters) {
                TextButton(
                    onClick = onClearFilters,
                    colors = ButtonDefaults.textButtonColors(contentColor = TextSecondary)
                ) {
                    Text("清除筛选", style = MaterialTheme.typography.labelMedium)
                }
            }
        }
    }
}

/** 排序方式中文标签 */
internal fun getSortOrderLabel(order: MemorySortOrder): String = when (order) {
    MemorySortOrder.NEWEST_FIRST -> "最新优先"
    MemorySortOrder.OLDEST_FIRST -> "最早优先"
    MemorySortOrder.MOST_ACCESSED -> "访问最多"
    MemorySortOrder.MOST_IMPORTANT -> "最重要"
}
