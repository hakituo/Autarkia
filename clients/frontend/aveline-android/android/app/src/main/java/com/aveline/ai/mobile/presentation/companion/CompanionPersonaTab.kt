package com.aveline.ai.mobile.presentation.companion

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.persona.PersonaUiState
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.Line
import com.aveline.ai.mobile.presentation.theme.TextBody
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * 人设列表项：只取展示与归组需要的五个字段。
 *
 * @param role 归组键：后端 role 优先，缺失时用名字去掉括号后缀，与旧逻辑一致
 */
private data class PersonaEntry(
    val filename: String,
    val name: String,
    val version: String,
    val description: String,
    val role: String
)

/**
 * Companion 人设 Tab。
 *
 * 顺序按设计稿：先一段人设摘要（读得懂「她是谁」），再是版本与音色的单选列表。
 * 原来是人设卡片列表 + 音色 chips：卡片边框、选中底色、版本号三套强调同时出现，
 * 一屏里没有任何一处是视觉重点。
 *
 * @param uiState 人设页 UI 状态
 * @param viewingFilename 正在查看的角色（纯展示，不切后端人设）
 * @param onSwitchPersona 切换人设回调(filename)
 * @param onSelectVoice 手选音色：(persona filename, 音色名)
 * @param onResetVoice 恢复跟随角色默认音色：(persona filename)
 */
@Composable
fun CompanionPersonaTab(
    uiState: PersonaUiState,
    viewingFilename: String? = null,
    onSwitchPersona: (String) -> Unit,
    onSelectVoice: (String, String) -> Unit = { _, _ -> },
    onResetVoice: (String) -> Unit = {}
) {
    val targetFilename = viewingFilename ?: uiState.activeFilename

    // 伴侣详情只展示当前聊天角色范围内的人设，点击可切换。
    val personaList = remember(uiState.personas, targetFilename) {
        val all = uiState.personas.mapNotNull { element ->
            runCatching { element.jsonObject.toPersonaEntry() }.getOrNull()
        }
        val activeRole = all.firstOrNull { it.filename == targetFilename }?.role
        if (activeRole.isNullOrBlank()) all else all.filter { it.role == activeRole }
    }

    val activeEntry = personaList.firstOrNull { it.filename == targetFilename }
        ?: personaList.firstOrNull()
    // 后端没写 description 时整段摘要不显示：留一句「还没有写简介」等于在页面上留了个空位置，
    // 用户既读不到内容也做不了什么。
    val personaDescription = activeEntry?.description.orEmpty().trim()
    val defaultVoice = uiState.personaDefaultVoices[targetFilename].orEmpty()
    val selectedVoice = uiState.personaVoiceOverrides[targetFilename] ?: defaultVoice
    val voiceOverridden = uiState.personaVoiceOverrides.containsKey(targetFilename)

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = CompanionGutter),
        contentPadding = PaddingValues(top = 20.dp, bottom = 24.dp)
    ) {
        if (uiState.isSwitching) {
            item(key = "persona-switching") {
                Row(
                    modifier = Modifier.padding(bottom = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    CircularProgressIndicator(
                        color = Accent,
                        modifier = Modifier.size(14.dp),
                        strokeWidth = 2.dp
                    )
                    Text(
                        text = "正在切换人设…",
                        style = MaterialTheme.typography.labelMedium,
                        color = TextTertiary
                    )
                }
            }
        }

        if (personaDescription.isNotBlank()) {
            item(key = "persona-summary") {
                Column {
                    SectionLabel(text = "人设")
                    Spacer(modifier = Modifier.height(10.dp))
                    Text(
                        text = personaDescription,
                        style = MaterialTheme.typography.bodyLarge.copy(fontSize = 15.sp, lineHeight = 26.sp),
                        color = TextBody
                    )
                }
            }
        }

        if (personaList.isEmpty()) {
            item(key = "persona-empty") {
                Text(
                    text = "暂无可选人设",
                    style = MaterialTheme.typography.bodyMedium,
                    color = TextTertiary,
                    modifier = Modifier.padding(top = 20.dp)
                )
            }
        } else {
            item(key = "persona-versions-label") {
                Column {
                    Spacer(modifier = Modifier.height(22.dp))
                    HorizontalDivider(color = Line, thickness = 1.dp)
                    Spacer(modifier = Modifier.height(16.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        SectionLabel(text = "切换人设")
                        Text(
                            text = "共 ${personaList.size} 个版本",
                            style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp),
                            color = TextTertiary
                        )
                    }
                }
            }
            itemsIndexed(
                items = personaList,
                key = { _, entry -> entry.filename.ifBlank { entry.name } }
            ) { _, entry ->
                PersonaSelectRow(
                    entry = entry,
                    selected = entry.filename == targetFilename,
                    enabled = !uiState.isSwitching,
                    onClick = { onSwitchPersona(entry.filename) }
                )
            }
        }

        item(key = "voice-divider") {
            Column {
                Spacer(modifier = Modifier.height(22.dp))
                HorizontalDivider(color = Line, thickness = 1.dp)
                Spacer(modifier = Modifier.height(16.dp))
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    SectionLabel(text = "音色")
                    if (voiceOverridden) {
                        Text(
                            text = "恢复默认",
                            style = MaterialTheme.typography.bodySmall.copy(fontSize = 13.sp),
                            color = TextSecondary,
                            modifier = Modifier
                                .clickable { onResetVoice(targetFilename) }
                                .padding(vertical = 2.dp)
                        )
                    }
                }
            }
        }

        if (uiState.voiceNames.isEmpty()) {
            item(key = "voice-empty") {
                Text(
                    text = "未读取到可用音色（后端未配置或未连接）",
                    style = MaterialTheme.typography.bodySmall,
                    color = TextTertiary,
                    modifier = Modifier.padding(top = 8.dp)
                )
            }
        } else {
            items(
                items = uiState.voiceNames,
                key = { voice -> "voice-$voice" }
            ) { voice ->
                VoiceSelectRow(
                    name = voice,
                    selected = voice == selectedVoice,
                    isPersonaDefault = voice == defaultVoice,
                    onClick = { onSelectVoice(targetFilename, voice) }
                )
            }
        }

        if (!voiceOverridden && defaultVoice.isNotBlank()) {
            item(key = "voice-following") {
                Text(
                    text = "当前跟随角色默认音色",
                    style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp),
                    color = TextTertiary,
                    modifier = Modifier.padding(top = 10.dp)
                )
            }
        }
    }
}

@Composable
private fun SectionLabel(text: String) {
    Text(
        text = text,
        style = MaterialTheme.typography.labelMedium.copy(fontSize = 13.sp),
        color = TextTertiary
    )
}

@Composable
private fun PersonaSelectRow(
    entry: PersonaEntry,
    selected: Boolean,
    enabled: Boolean,
    onClick: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = 58.dp)
            .companionRowHairline()
            .clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = 4.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(2.dp)
        ) {
            Text(
                text = entry.name,
                style = MaterialTheme.typography.bodyLarge.copy(
                    fontSize = 15.5.sp,
                    fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal
                ),
                color = TextPrimary,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
            Text(
                text = "版本 ${entry.version}",
                style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.5.sp),
                color = TextTertiary,
                maxLines = 1
            )
        }
        CompanionSelectRadio(selected = selected, contentDescription = "当前人设")
    }
}

@Composable
private fun VoiceSelectRow(
    name: String,
    selected: Boolean,
    isPersonaDefault: Boolean,
    onClick: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = 52.dp)
            .companionRowHairline()
            .clickable(onClick = onClick)
            .padding(horizontal = 4.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Row(
            modifier = Modifier.weight(1f),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Text(
                text = name,
                style = MaterialTheme.typography.bodyLarge.copy(
                    fontSize = 15.5.sp,
                    fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal
                ),
                color = TextPrimary,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
            if (isPersonaDefault) {
                Text(
                    text = "角色默认",
                    style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp),
                    color = TextTertiary
                )
            }
        }
        CompanionSelectRadio(selected = selected, contentDescription = "当前音色")
    }
}

private fun JsonObject.toPersonaEntry(): PersonaEntry {
    val name = stringOf("name").ifBlank { "未命名" }
    return PersonaEntry(
        filename = stringOf("filename"),
        name = name,
        version = stringOf("version").ifBlank { "?.?.?" },
        description = stringOf("description"),
        role = stringOf("role").ifBlank { name.substringBefore('(').substringBefore('（').trim() }
    )
}

private fun JsonObject.stringOf(key: String): String =
    runCatching { get(key)?.jsonPrimitive?.contentOrNull.orEmpty() }.getOrDefault("")
