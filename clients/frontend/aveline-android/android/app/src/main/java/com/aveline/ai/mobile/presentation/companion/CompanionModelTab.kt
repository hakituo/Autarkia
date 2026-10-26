package com.aveline.ai.mobile.presentation.companion

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.outlined.SmartToy
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.domain.models.AIModel
import com.aveline.ai.mobile.presentation.components.SectionCard
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * Companion 模型 Tab。
 *
 * 模型选择属于当前 role：不同角色分别记忆自己的选择；同一角色切换不同 persona 版本时
 * 模型偏好保持不变。没有手动选择过模型的角色继续跟随后端 persona 默认模型。
 *
 * 性能约定：模型行必须走 [LazyColumn] 的 items 懒加载，不能用一个 item 包 forEach。
 * 模型数量可达几十条，一次性组合全部行会在这页被 Pager 拖动时每帧重绘整列，表现为
 * 左右滑动明显掉帧；同时也避免了大列表尺寸动画叠加在滑动动画上。
 */
@Composable
fun CompanionModelTab(
    availableModels: List<AIModel>,
    selectedModel: AIModel?,
    isLoading: Boolean,
    error: String?,
    onModelSelected: (String) -> Unit
) {
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 16.dp),
        contentPadding = PaddingValues(top = 8.dp, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        item(key = "model-section-header") {
            SectionCard(
                title = "模型设置",
                icon = Icons.Outlined.SmartToy,
                subtitle = "当前角色独立保存；切换角色会恢复各自的模型"
            ) {
                when {
                    error != null -> Text(
                        text = error,
                        style = MaterialTheme.typography.bodySmall,
                        color = TextSecondary
                    )
                    isLoading && availableModels.isEmpty() -> Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 16.dp),
                        contentAlignment = Alignment.Center
                    ) {
                        CircularProgressIndicator(
                            color = Accent,
                            modifier = Modifier.size(20.dp),
                            strokeWidth = 2.dp
                        )
                    }
                    availableModels.isEmpty() -> Text(
                        text = "暂无可用模型",
                        style = MaterialTheme.typography.bodyMedium,
                        color = TextTertiary
                    )
                    else -> Text(
                        text = "共 ${availableModels.size} 个可用模型，点击切换",
                        style = MaterialTheme.typography.bodySmall,
                        color = TextTertiary
                    )
                }
            }
        }

        // 每个模型单独一个懒加载 item：只有可视区域内的行才会被组合与绘制。
        items(
            items = availableModels,
            key = { model -> model.id }
        ) { model ->
            ModelListItem(
                model = model,
                isSelected = model.id == selectedModel?.id,
                onClick = { onModelSelected(model.id) }
            )
        }
    }
}

@Composable
private fun ModelListItem(
    model: AIModel,
    isSelected: Boolean,
    onClick: () -> Unit
) {
    val cardBg = if (isSelected) Accent.copy(alpha = 0.08f) else Color.Transparent
    val cardBorder = if (isSelected) {
        BorderStroke(1.5.dp, Accent)
    } else {
        BorderStroke(1.dp, TextSecondary.copy(alpha = 0.15f))
    }
    val textColor = if (isSelected) Accent else TextPrimary

    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(10.dp)),
        shape = RoundedCornerShape(10.dp),
        color = cardBg,
        border = cardBorder,
        onClick = onClick
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = model.name,
                    style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Bold),
                    color = textColor,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Spacer(modifier = Modifier.height(2.dp))
                Text(
                    text = model.provider,
                    style = MaterialTheme.typography.labelSmall,
                    color = TextSecondary
                )
            }
            if (isSelected) {
                Icon(
                    imageVector = Icons.Default.Check,
                    contentDescription = "当前模型",
                    tint = Accent,
                    modifier = Modifier.size(18.dp)
                )
            }
        }
    }
}
