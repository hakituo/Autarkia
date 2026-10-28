package com.aveline.ai.mobile.presentation.companion

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.domain.models.AIModel
import com.aveline.ai.mobile.presentation.components.controls.AvelineSwitch
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.Background
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/**
 * Companion 模型 Tab。
 *
 * 模型选择属于当前 role：不同角色分别记忆自己的选择；同一角色切换不同 persona 版本时
 * 模型偏好保持不变。没有手动选择过模型的角色继续跟随后端 persona 默认模型。
 *
 * 版式是单选列表：名字 + 厂商两行字，右侧一个圆圈。原来每行是一张描边卡片、
 * 选中态还会把底色和文字都染成强调色——同一屏几十行，卡片边框的视觉噪音盖过了
 * 「选了哪个」这个唯一重要的信息。
 *
 * 性能约定：模型行必须走 [LazyColumn] 的 items 懒加载，不能用一个 item 包 forEach。
 * 模型数量可达几十条，一次性组合全部行会在这页被 Pager 拖动时每帧重绘整列。
 */
@Composable
fun CompanionModelTab(
    availableModels: List<AIModel>,
    selectedModel: AIModel?,
    isLoading: Boolean,
    error: String?,
    onModelSelected: (String) -> Unit,
    /** 思考模式：null = 该角色没设置过，跟随后端配置（界面按开显示）。 */
    thinkingEnabled: Boolean? = null,
    onThinkingChange: (Boolean) -> Unit = {}
) {
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = CompanionGutter),
        contentPadding = PaddingValues(top = 16.dp, bottom = 24.dp)
    ) {
        item(key = "model-caption") {
            Text(
                text = "每个角色单独保存",
                style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.5.sp),
                color = TextTertiary,
                modifier = Modifier.padding(start = 4.dp, bottom = 4.dp)
            )
        }

        // 思考模式放在模型列表之前：它是「这个角色用不用先想再答」的开关，
        // 比「具体用哪个模型」更高一层；跟着滚动会跑到几十行模型后面，容易找不到。
        item(key = "thinking-mode") {
            ThinkingModeRow(
                checked = thinkingEnabled ?: true,
                onCheckedChange = onThinkingChange
            )
        }

        when {
            error != null -> item(key = "model-error") {
                Text(
                    text = error,
                    style = MaterialTheme.typography.bodySmall,
                    color = TextTertiary,
                    modifier = Modifier.padding(vertical = 12.dp, horizontal = 4.dp)
                )
            }

            isLoading && availableModels.isEmpty() -> item(key = "model-loading") {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 32.dp),
                    contentAlignment = Alignment.Center
                ) {
                    CircularProgressIndicator(
                        color = Accent,
                        modifier = Modifier.size(20.dp),
                        strokeWidth = 2.dp
                    )
                }
            }

            availableModels.isEmpty() -> item(key = "model-empty") {
                Text(
                    text = "暂无可用模型",
                    style = MaterialTheme.typography.bodyMedium,
                    color = TextTertiary,
                    modifier = Modifier.padding(vertical = 12.dp, horizontal = 4.dp)
                )
            }

            // 每个模型单独一个懒加载 item：只有可视区域内的行才会被组合与绘制。
            else -> items(
                items = availableModels,
                key = { model -> model.id }
            ) { model ->
                ModelSelectRow(
                    model = model,
                    selected = model.id == selectedModel?.id,
                    onClick = { onModelSelected(model.id) }
                )
            }
        }
    }
}

@Composable
private fun ModelSelectRow(
    model: AIModel,
    selected: Boolean,
    onClick: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = 58.dp)
            .companionRowHairline()
            .clickable(onClick = onClick)
            .padding(horizontal = 4.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(2.dp)
        ) {
            Text(
                text = model.displayName,
                style = MaterialTheme.typography.bodyLarge.copy(
                    fontSize = 15.5.sp,
                    fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal
                ),
                color = TextPrimary,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
            Text(
                text = model.provider.ifBlank { model.typeLabel },
                style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.5.sp),
                color = TextTertiary,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
        }
        CompanionSelectRadio(selected = selected)
    }
}

/**
 * 思考模式开关行：标题 + 一行说明 + 右侧开关，整行可点。
 *
 * 版式沿用 companion 这一套行（细线分隔、左对齐到 [CompanionGutter]），
 * 不复用设置页的 `SettingsSwitchRow` —— 那套行高与字号是设置页的视觉体系。
 */
@Composable
private fun ThinkingModeRow(
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = 58.dp)
            .companionRowHairline()
            .clickable { onCheckedChange(!checked) }
            .padding(horizontal = 4.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(2.dp)
        ) {
            Text(
                text = "思考模式",
                style = MaterialTheme.typography.bodyLarge.copy(fontSize = 15.5.sp),
                color = TextPrimary,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
            Text(
                text = "先想再答，回复更稳但更慢；仅部分模型支持",
                style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.5.sp),
                color = TextTertiary,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis
            )
        }
        AvelineSwitch(
            checked = checked,
            onCheckedChange = onCheckedChange
        )
    }
}

/**
 * 单选圆圈：选中是实心白底 + 对勾，未选中是 1.5dp 空心环。
 *
 * 模型 / 人设 / 音色三处复用同一份，保证「单选」在整页只有一种画法。
 */
@Composable
internal fun CompanionSelectRadio(selected: Boolean, contentDescription: String = "已选中") {
    if (selected) {
        Box(
            modifier = Modifier
                .size(22.dp)
                .clip(CircleShape)
                .background(TextPrimary),
            contentAlignment = Alignment.Center
        ) {
            Icon(
                imageVector = Icons.Default.Check,
                contentDescription = contentDescription,
                tint = Background,
                modifier = Modifier.size(16.dp)
            )
        }
    } else {
        Box(
            modifier = Modifier
                .size(22.dp)
                .clip(CircleShape)
                .border(width = 1.5.dp, color = Color.White.copy(alpha = 0.22f), shape = CircleShape)
        )
    }
}
