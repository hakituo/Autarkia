package com.aveline.ai.mobile.presentation.chat

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.aveline.ai.mobile.data.local.storage.PersonaAvatarStorage
import com.aveline.ai.mobile.data.repository.PersonaLocalMetaRepository
import com.aveline.ai.mobile.presentation.companion.CompanionScreen
import com.aveline.ai.mobile.presentation.components.PullableDismissPanel
import com.aveline.ai.mobile.presentation.components.PullableDismissPanelState
import com.aveline.ai.mobile.presentation.conversations.ConversationItem
import com.aveline.ai.mobile.presentation.conversations.PersonaEditSheet
import com.aveline.ai.mobile.presentation.memory.MemoryViewModel
import com.aveline.ai.mobile.presentation.persona.PersonaUiState
import com.aveline.ai.mobile.presentation.persona.PersonaViewModel
import com.aveline.ai.mobile.presentation.settings.SettingsViewModel
import com.aveline.ai.mobile.presentation.status.StatusViewModel
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import kotlinx.coroutines.launch

/**
 * 伴侣详情全屏覆盖面板（点击聊天页顶栏头像打开，从右侧滑入）。
 *
 * 模型 Tab 使用 ChatViewModel 的 role 级状态，不再复用 SettingsViewModel 的应用级模型状态。
 */
@Composable
fun ChatCompanionPanel(
    chatViewModel: ChatViewModel,
    personaViewModel: PersonaViewModel,
    statusViewModel: StatusViewModel,
    memoryViewModel: MemoryViewModel,
    @Suppress("UNUSED_PARAMETER") settingsViewModel: SettingsViewModel,
    personaUiState: PersonaUiState,
    localAvatarMap: Map<String, String>,
    viewingFilename: String?,
    panelState: PullableDismissPanelState,
    visible: Boolean,
    gesturesEnabled: Boolean,
    avatarStorage: PersonaAvatarStorage,
    localMeta: PersonaLocalMetaRepository,
    onRequestClose: () -> Unit,
    onDismissed: () -> Unit,
    onRevealed: () -> Unit,
    onDismissGestureEnabledChange: (Boolean) -> Unit,
    modifier: Modifier = Modifier
) {
    val statusUiState by statusViewModel.uiState.collectAsStateWithLifecycle()
    val memoryUiState by memoryViewModel.uiState.collectAsStateWithLifecycle()
    val graphUiState by memoryViewModel.graphState.collectAsStateWithLifecycle()
    val roleModels by chatViewModel.availableRoleModels.collectAsStateWithLifecycle()
    val selectedRoleModel by chatViewModel.selectedRoleModel.collectAsStateWithLifecycle()
    val roleModelLoading by chatViewModel.roleModelLoading.collectAsStateWithLifecycle()
    val roleModelError by chatViewModel.roleModelError.collectAsStateWithLifecycle()
    val roleThinking by chatViewModel.roleThinking.collectAsStateWithLifecycle()
    val editScope = rememberCoroutineScope()
    var editingItem by remember { mutableStateOf<ConversationItem?>(null) }

    // 页头标题用当前查看 persona 的展示名：与聊天顶栏同源，
    // 避免顶栏写「Ling」、详情页写「Ling (QQ)」这种两处不一致。
    val companionName = remember(personaUiState.personas, viewingFilename, localAvatarMap) {
        resolveActivePersonaInfo(
            personaUiState = personaUiState,
            localAvatarMap = localAvatarMap,
            viewingFilename = viewingFilename
        ).displayName
    }

    // 刷新必须绑定“详情真正可见”，不能只绑头像点击回调：
    // 左滑打开同样会把面板设为 visible。显式传入当前 persona，避免面板可见与
    // ChatScreen 控制上下文 LaunchedEffect 同帧更新时误刷上一个角色。
    //
    // 走缓存优先（仓库有 60s 缓存）：面板先用已有数据渲染，后台再悄悄刷新，
    // 用户不需要对着转圈等一次网络。
    LaunchedEffect(visible, viewingFilename) {
        if (visible) {
            statusViewModel.refreshStatusForPersona(viewingFilename)
            // 深链场景下聊天页没拿到 persona，记忆首屏还没拉过，这里兜底（幂等）。
            memoryViewModel.ensureLoaded()
        }
    }

    BackHandler(enabled = visible) {
        onRequestClose()
    }

    PullableDismissPanel(
        state = panelState,
        onDismissed = onDismissed,
        onRevealed = onRevealed,
        gesturesEnabled = gesturesEnabled
    ) {
        Surface(
            modifier = modifier.fillMaxSize(),
            color = MaterialTheme.colorScheme.surface
        ) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .statusBarsPadding()
            ) {
                // 只留返回与编辑：标题位置让给下方页头里的伴侣名字，
                // 一页里出现「伴侣详情」和「Aveline」两个标题会互相抢注意力。
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 8.dp, vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    IconButton(onClick = onRequestClose) {
                        Icon(
                            Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "返回",
                            tint = TextPrimary
                        )
                    }
                    Spacer(modifier = Modifier.weight(1f))
                    IconButton(
                        onClick = {
                            val info = resolveActivePersonaInfo(personaUiState, localAvatarMap)
                            editingItem = ConversationItem(
                                filename = personaUiState.activeFilename,
                                displayName = info.displayName,
                                role = resolvePersonaRole(personaUiState, personaUiState.activeFilename),
                                description = "",
                                avatarUrl = info.avatarUrl,
                                localAvatarPath = info.localAvatarPath,
                                lastMessagePreview = null,
                                lastMessageAt = null,
                                unreadCount = 0,
                                isActive = true
                            )
                        }
                    ) {
                        Icon(
                            Icons.Filled.Edit,
                            contentDescription = "编辑资料",
                            tint = TextPrimary
                        )
                    }
                }

                CompanionScreen(
                    companionName = companionName,
                    statusUiState = statusUiState,
                    clockFlow = statusViewModel.clock,
                    personaUiState = personaUiState,
                    memoryUiState = memoryUiState,
                    graphUiState = graphUiState,
                    availableModels = roleModels,
                    selectedModel = selectedRoleModel,
                    modelLoading = roleModelLoading,
                    modelError = roleModelError,
                    onModelSelected = chatViewModel::selectModelForCurrentRole,
                    thinkingEnabled = roleThinking,
                    onThinkingChange = chatViewModel::setThinkingForCurrentRole,
                    viewingFilename = viewingFilename,
                    // 错误横幅里的“重试”是用户主动点的，强制走网络拿权威数据。
                    onRefreshStatus = statusViewModel::forceRefreshStatus,
                    // 滑到日程页时的静默刷新：缓存优先，不打断用户滑动。
                    onSilentRefreshStatus = {
                        statusViewModel.refreshStatusForPersona(viewingFilename)
                    },
                    onWakeCompanion = statusViewModel::wakeCompanion,
                    onInterruptCompanion = statusViewModel::interruptCompanion,
                    onSkipCompanionActivity = statusViewModel::skipCompanionActivity,
                    onDismissGestureEnabledChange = onDismissGestureEnabledChange,
                    onSwitchPersona = { fn ->
                        personaViewModel.switchPersona(fn) { selected ->
                            chatViewModel.confirmPersonaSelection(selected)
                        }
                    },
                    onSelectVoice = personaViewModel::selectVoice,
                    onResetVoice = { fn -> personaViewModel.selectVoice(fn, "") },
                    onSearchMemory = memoryViewModel::search,
                    onMemoryTopicFilterChange = memoryViewModel::setTopicFilter,
                    onToggleImportantOnly = memoryViewModel::toggleImportantOnly,
                    onMemorySortOrderChange = memoryViewModel::setSortOrder,
                    onDeleteMemory = memoryViewModel::deleteMemory,
                    onToggleImportant = memoryViewModel::toggleImportant,
                    onConfirmDeleteMemory = memoryViewModel::confirmDelete,
                    onCancelDeleteMemory = memoryViewModel::cancelDelete,
                    onClearMemoryFilters = memoryViewModel::clearFilters,
                    onLoadMoreMemory = memoryViewModel::loadMoreMemories,
                    onOpenMemoryDetail = memoryViewModel::openMemoryDetail,
                    onCloseMemoryDetail = memoryViewModel::closeMemoryDetail,
                    onGraphEnter = memoryViewModel::loadGraphAnchors,
                    onGraphAnchorClick = memoryViewModel::openGraphAnchor,
                    onGraphBack = memoryViewModel::closeGraphAnchor,
                    onGraphRetry = memoryViewModel::retryGraph
                )
            }

            editingItem?.let { item ->
                PersonaEditSheet(
                    item = item,
                    avatarStorage = avatarStorage,
                    onDismiss = { editingItem = null },
                    onSaveName = { newName ->
                        editScope.launch {
                            localMeta.setCustomName(item.filename, newName)
                        }
                        personaViewModel.loadPersonas()
                    },
                    onPickAvatar = { uri ->
                        editScope.launch { localMeta.setAvatar(item.filename, uri) }
                        personaViewModel.loadPersonas()
                    },
                    onClearAvatar = {
                        editScope.launch { localMeta.clearAvatar(item.filename) }
                        personaViewModel.loadPersonas()
                    },
                    voices = personaUiState.voiceNames,
                    selectedVoice = personaUiState.personaVoiceOverrides[item.filename]
                        ?: personaUiState.personaDefaultVoices[item.filename].orEmpty(),
                    isVoiceOverridden = personaUiState.personaVoiceOverrides.containsKey(item.filename),
                    onSelectVoice = { voice -> personaViewModel.selectVoice(item.filename, voice) },
                    onResetVoice = { personaViewModel.selectVoice(item.filename, "") }
                )
            }
        }
    }
}
