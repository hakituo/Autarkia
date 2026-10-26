package com.aveline.ai.mobile.presentation.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.components.controls.AvelineButton
import com.aveline.ai.mobile.presentation.components.controls.AvelineButtonVariant
import com.aveline.ai.mobile.presentation.components.controls.AvelineIconButton
import com.aveline.ai.mobile.presentation.components.controls.AvelineSegmented
import com.aveline.ai.mobile.presentation.theme.Danger
import com.aveline.ai.mobile.presentation.theme.Surface
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import com.aveline.ai.mobile.presentation.tools.ToolsUiState

/**
 * 开发者工具里唯一保留的页面：系统资源。
 *
 * 图像生成 / 视觉分析已经从设置页移除，这里只读展示后端采样。渲染不依赖固定
 * 字段名：[SystemJsonCard] 会把任意嵌套 JSON 展开成可读的行；原始 JSON 永远可查。
 */
@Composable
internal fun SettingsSystemResourcesScreen(
    state: ToolsUiState,
    onBack: () -> Unit,
    onLoadSystemResources: () -> Unit,
    onLoadSystemStats: () -> Unit,
    onClearError: () -> Unit,
    modifier: Modifier = Modifier
) {
    var tabIndex by rememberSaveable { mutableIntStateOf(0) }
    var showRaw by rememberSaveable { mutableStateOf(false) }

    val isResourcesTab = tabIndex == 0
    val data = if (isResourcesTab) state.systemResources else state.systemStats
    val loadCurrent = if (isResourcesTab) onLoadSystemResources else onLoadSystemStats

    LaunchedEffect(tabIndex) {
        onClearError()
        if (data == null) loadCurrent()
    }

    Column(
        modifier = modifier
            .fillMaxSize()
            .statusBarsPadding()
    ) {
        SettingsSubPageHeader(
            title = "系统资源",
            subtitle = "后端实时采样；字段随版本变化，未知字段按原样展示",
            onBack = onBack
        )

        Column(
            modifier = Modifier
                .weight(1f)
                .verticalScroll(rememberScrollState())
                .navigationBarsPadding()
                .padding(horizontal = 20.dp)
        ) {
            Spacer(modifier = Modifier.height(16.dp))

            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                AvelineSegmented(
                    options = listOf("资源", "统计"),
                    selectedIndex = tabIndex,
                    onSelect = { tabIndex = it },
                    modifier = Modifier.weight(1f)
                )
                Spacer(modifier = Modifier.width(10.dp))
                AvelineIconButton(
                    icon = Icons.Default.Refresh,
                    contentDescription = "刷新",
                    onClick = loadCurrent,
                    enabled = !state.isSystemLoading
                )
            }

            state.error?.let { error ->
                Spacer(modifier = Modifier.height(12.dp))
                Text(
                    text = "$error · 点击关闭",
                    fontSize = 12.5.sp,
                    lineHeight = 18.sp,
                    color = Danger,
                    modifier = Modifier.clickable(onClick = onClearError)
                )
            }

            Spacer(modifier = Modifier.height(16.dp))

            when {
                data != null -> {
                    SystemJsonCard(data)
                    Spacer(modifier = Modifier.height(20.dp))
                    SettingsSectionHeader("原始数据")
                    SettingsNavRow(
                        title = "JSON",
                        subtitle = "字段结构随时可能变化",
                        value = if (showRaw) "收起" else "展开",
                        onClick = { showRaw = !showRaw }
                    )
                    if (showRaw) {
                        Spacer(modifier = Modifier.height(10.dp))
                        SystemJsonRaw(data)
                    }
                }

                state.isSystemLoading -> LoadingRow()

                else -> EmptyState(
                    isResourcesTab = isResourcesTab,
                    onRetry = loadCurrent
                )
            }

            Spacer(modifier = Modifier.height(32.dp))
        }
    }
}

@Composable
private fun LoadingRow() {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(Surface)
            .border(1.dp, Color.White.copy(alpha = 0.08f), RoundedCornerShape(14.dp))
            .padding(horizontal = 16.dp, vertical = 18.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        CircularProgressIndicator(
            modifier = Modifier.size(16.dp),
            strokeWidth = 2.dp,
            color = TextTertiary
        )
        Text(
            text = "读取中…",
            fontSize = 13.5.sp,
            lineHeight = 19.sp,
            color = TextSecondary
        )
    }
}

@Composable
private fun EmptyState(isResourcesTab: Boolean, onRetry: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(Surface)
            .border(1.dp, Color.White.copy(alpha = 0.08f), RoundedCornerShape(14.dp))
            .padding(horizontal = 16.dp, vertical = 18.dp)
    ) {
        Text(
            text = "还没有${if (isResourcesTab) "资源" else "统计"}数据。",
            fontSize = 13.5.sp,
            lineHeight = 19.sp,
            color = TextSecondary
        )
        Spacer(modifier = Modifier.height(4.dp))
        Text(
            text = "需要后端在线；采样接口不可用时只能看到错误提示。",
            fontSize = 12.5.sp,
            lineHeight = 18.sp,
            color = TextTertiary
        )
        Spacer(modifier = Modifier.height(14.dp))
        AvelineButton(
            text = "读取",
            onClick = onRetry,
            variant = AvelineButtonVariant.Secondary
        )
    }
}
