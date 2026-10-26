package com.aveline.ai.mobile.presentation.chat

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Snackbar
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.platform.LocalViewConfiguration
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.aveline.ai.mobile.presentation.components.HorizontalContentGestureState
import com.aveline.ai.mobile.presentation.components.rememberPullableDismissPanelState
import com.aveline.ai.mobile.presentation.memory.MemoryViewModel
import com.aveline.ai.mobile.presentation.persona.PersonaViewModel
import com.aveline.ai.mobile.presentation.settings.SettingsViewModel
import com.aveline.ai.mobile.presentation.status.StatusViewModel
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import kotlinx.coroutines.launch

/**
 * 聊天界面（QQ 风格详情页）。
 *
 * 本文件只做**组装**：收集状态、拼装各子组件，具体 UI 与交互都在兄弟模块里：
 * - [ChatTopBar]：顶部栏（返回 + 头像 + 昵称）
 * - [ChatPeerChatArea]：双角色对话折叠区
 * - [ChatMessageList]：消息列表（时间分隔 / 旁白 / 气泡 / 空状态）
 * - [ChatContentArea]：内容区组装（对白折叠区 + 消息列表 + 消息动作）
 * - [ChatBottomArea]：底部区域（上传/待发/识别/转写提示条 + 输入栏 + “+”面板）
 * - [ChatMorePanel]：聊天“+”更多功能面板
 * - [ChatCompanionPanel]：伴侣详情全屏覆盖
 * - [companionPanelSwipeGesture]：左滑打开伴侣面板的手势
 * - [ChatErrorSnackbarEffect] / [ChatUploadStateEffect]：错误与上传结果提示
 *
 * 导航：通过 NavController 进入/退出，转场动画由 NavGraph 的 slideIn/slideOut 提供（QQ 风格 push/pop）。
 *
 * @param viewModel Chat ViewModel
 * @param initialDisplayName 导航传入的展示名（会话列表算好的 昵称/角色名）。
 *        作为顶部标题的立即初始值，避免 persona 接口返回前先闪一下"聊天"。
 * @param onBackClick 返回会话列表
 */

/** 还没记录过任何键盘高度时的“+”面板高度。 */
private val DefaultMorePanelHeight = 260.dp

/** “+”面板高度下限：避免异常偏小的 IME inset 让面板矮到看不见。 */
private val MinMorePanelHeight = 200.dp

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ChatScreen(
    viewModel: ChatViewModel,
    initialDisplayName: String? = null,
    onBackClick: () -> Unit = {}
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val snackbarHostState = remember { SnackbarHostState() }
    val density = LocalDensity.current
    val focusManager = LocalFocusManager.current
    val keyboardController = LocalSoftwareKeyboardController.current

    // “+”更多面板与软键盘互斥；记录最近一次真实 IME 高度，
    // 从键盘切到更多面板时尽量保持底部区域等高，避免聊天 viewport 突然跳动。
    var showMorePanel by remember { mutableStateOf(false) }
    var lastImeHeightPx by remember { mutableIntStateOf(0) }
    // IME inset 是动画变化的：收起过程中会连续给出 800 -> 600 -> ... -> 3 -> 0 这样的值。
    // 只按“最后一个正数”记录，留下的是动画尾巴上那个只有几像素的值，
    // 面板高度就会退化成几个 dp —— 表现是点“+”几乎没反应、页面只抬起一点点。
    // 所以改为记录本次弹出过程中的峰值，收起后再保留这个峰值。
    var imePeakHeightPx by remember { mutableIntStateOf(0) }
    val currentImeHeightPx = WindowInsets.ime.getBottom(density)
    // 手势的 pointerInput 只在 key 变化时重建，闭包会固化首次组合时的局部值。
    // 包成 State 后，{ imeHeightState.value == 0 } 每次读取的都是最新 IME 高度，
    // 否则键盘弹出时"禁用左滑开面板"的判断会一直用初始的 0（恒为可开）。
    val imeHeightState = rememberUpdatedState(currentImeHeightPx)
    var imeWasVisible by remember { mutableStateOf(currentImeHeightPx > 0) }
    LaunchedEffect(currentImeHeightPx) {
        val imeVisible = currentImeHeightPx > 0
        if (imeVisible) {
            imePeakHeightPx = maxOf(imePeakHeightPx, currentImeHeightPx)
            lastImeHeightPx = imePeakHeightPx
        } else {
            // 收起后清零峰值，但保留 lastImeHeightPx 作为下一次的面板高度参考。
            imePeakHeightPx = 0
        }

        // 只在 IME 真正从“隐藏 -> 显示”时关闭更多面板。
        // 不能再用输入框 focus 回调直接关面板：点击“+”时我们会主动 clearFocus，
        // Compose 的焦点状态更新与重组存在时序竞争，之前会出现 showMorePanel 刚设为 true
        // 就又被 focus 回调立刻设回 false，看起来像“+ 点了完全没反应”。
        if (imeVisible && !imeWasVisible && showMorePanel) {
            showMorePanel = false
        }
        imeWasVisible = imeVisible
    }
    // 高度对齐最近一次真实键盘高度，并给一个下限兜底：
    // 只要 inset 异常偏小（动画中间值、某些机型的非零静态值），面板也不会矮到看不见。
    val morePanelHeight = if (lastImeHeightPx > 0) {
        with(density) { lastImeHeightPx.toDp() }.coerceAtLeast(MinMorePanelHeight)
    } else {
        DefaultMorePanelHeight
    }

    // 用户主动发送的事件序号。它只属于 UI 滚动语义，不进入 ViewModel / 数据层。
    // 每次发送递增一次，让 ChatMessageList 无条件跟到本次新消息。
    var forceFollowLatestRequest by remember(uiState.currentSession?.id) {
        mutableIntStateOf(0)
    }

    BackHandler(enabled = showMorePanel) {
        showMorePanel = false
    }

    // 离开聊天页（返回会话列表 / 手势退出）时把输入框里没发出去的话同步落盘。
    // 比 ViewModel.onCleared 更早一步：此时 uiState 还是完整的，
    // 用户在 debounce 窗口里刚打的最后几个字不会被丢掉。
    DisposableEffect(Unit) {
        onDispose { viewModel.flushInputDraft() }
    }

    // 正在编辑的消息（对话框内部自持文本状态，这里只记"编辑哪一条"）
    var editingMessageId by remember { mutableStateOf<String?>(null) }
    var editingMessageText by remember { mutableStateOf("") }

    // 伴侣详情面板：面板常驻组合树并停在右侧隐藏锚点，聊天页手势才能同步驱动首帧位移
    var showCompanionPanel by remember { mutableStateOf(false) }
    var companionDismissGestureEnabled by remember { mutableStateOf(true) }
    val companionScope = rememberCoroutineScope()
    val companionPanelState = rememberPullableDismissPanelState()
    val horizontalContentGestureState = remember { HorizontalContentGestureState() }

    // 顶部栏需要的 persona 数据
    val personaViewModel: PersonaViewModel = hiltViewModel()
    val personaUiState by personaViewModel.uiState.collectAsStateWithLifecycle()

    // Companion 相关的 ViewModel（状态与回调较多，由 ChatCompanionPanel 自行消费）
    val statusViewModel: StatusViewModel = hiltViewModel()
    val memoryViewModel: MemoryViewModel = hiltViewModel()
    val settingsViewModel: SettingsViewModel = hiltViewModel()

    // 伴侣详情的"正在查看角色"跟随当前聊天会话（纯只读，不切对话人设）。
    // 这里同时承担伴侣详情**预加载**：聊天时就把状态 / 记忆拉齐，打开面板直接渲染。
    val viewingPersona by viewModel.viewingProfileFilename.collectAsStateWithLifecycle()
    LaunchedEffect(viewingPersona, uiState.currentSession?.id) {
        // 聊天记录树跟随当前会话；切换会话时 ViewModel 内部会取消旧订阅。
        memoryViewModel.setViewingSession(uiState.currentSession?.id)
        val fn = viewingPersona
        if (fn != null) {
            memoryViewModel.setViewingPersona(fn)
            statusViewModel.setControlContext(fn, uiState.currentSession?.id)
        } else {
            memoryViewModel.ensureLoaded() // 深链无 persona 时兜底首屏
        }
    }

    // 头像本地存储（用于 Chat 顶部头像，如果用户给 persona 设了自定义头像）
    val avatarStorageHolder: ChatAvatarStorageHolder = hiltViewModel()
    val avatarStorage = avatarStorageHolder.avatarStorage
    val localMeta = avatarStorageHolder.localMeta
    val localAvatarMap by avatarStorageHolder.localAvatarMap.collectAsStateWithLifecycle()

    // 当前激活 persona 的显示数据（名字 + 头像）：跟随"正在查看的角色"
    val activePersonaInfo = remember(
        viewingPersona,
        personaUiState.activeFilename,
        personaUiState.personas,
        localAvatarMap,
        initialDisplayName
    ) {
        resolveActivePersonaInfo(personaUiState, localAvatarMap, viewingPersona, initialDisplayName)
    }

    val mediaPickers = rememberChatMediaPickers(
        onDocumentsPicked = { viewModel.uploadDocuments(it) },
        onImagesPicked = { viewModel.uploadImages(it) },
        onRecordPermissionResult = { granted ->
            if (granted) {
                viewModel.startVoiceRecording()
            } else {
                viewModel.setError("缺少录音权限，请在系统设置中授予")
            }
        }
    )

    // 显示错误信息（带"复制"按钮）
    ChatErrorSnackbarEffect(
        error = uiState.error,
        snackbarHostState = snackbarHostState,
        onErrorShown = viewModel::clearError
    )

    // 显示上传成功提示
    ChatUploadStateEffect(
        uploadState = uiState.uploadState,
        snackbarHostState = snackbarHostState,
        onUploadReset = viewModel::resetUploadState
    )

    // 屏幕宽度（px）与手势判定参数：方向锁定后直接驱动面板位移，松手时再按速度吸附。
    // 注意：宽度必须在根容器里按**实际占用宽度**取（见下方 BoxWithConstraints），
    // 平板双栏时聊天页只占右半边，用整屏宽度会把左侧保留区放大到无法起手。
    //
    // 和 anchoredDraggable（全局侧边栏）共用系统 touchSlop。
    // 原来写死 16dp，约为侧边栏的两倍，起手要多滑一大段面板才开始动，
    // 主观上就是"侧边栏一碰就走、伴侣详情卡一下才跟手"。
    val touchSlopPx = LocalViewConfiguration.current.touchSlop
    val openVelocityThresholdPx = with(density) { 125.dp.toPx() }

    val openCompanionPanel: () -> Unit = {
        companionScope.launch {
            // 面板常驻在屏幕右侧隐藏锚点，点击头像时直接动画到可见位置。
            // 状态已由上面的 LaunchedEffect 预加载，这里不再补发请求（面板自身会缓存优先刷新）。
            showCompanionPanel = true
            companionPanelState.show()
        }
    }
    val closeCompanionPanel: () -> Unit = {
        companionScope.launch {
            companionPanelState.dismiss()
            // dismiss() 正常返回即表示面板已停在隐藏锚点。这里再兜底清一次可见标记：
            // 面板本来就已隐藏时 offset 不会再变化，不会再触发 onDismissed，
            // 只靠回调会让可见标记永久停在 true，返回键被 BackHandler 一直吃掉。
            showCompanionPanel = false
        }
    }

    val toggleMorePanel: () -> Unit = {
        if (showMorePanel) {
            showMorePanel = false
        } else {
            // 面板高度直接用上面 LaunchedEffect 维护的“本次弹出峰值”，
            // 这里不再用当前 inset 覆盖它：键盘正在弹出/收起时当前值只是动画中间值，
            // 覆盖会把已经记好的真实高度改小，面板又变回几个 dp。
            // 关闭逻辑由真实 IME 的“隐藏 -> 显示”转换接管，不依赖 focus 回调。
            keyboardController?.hide()
            focusManager.clearFocus(force = true)
            showMorePanel = true
        }
    }

    // 键盘弹出时把整个聊天页压到键盘之上（微信/QQ 行为）：
    // 页面可用高度缩小 → 顶部栏留在原位、消息列表缩短、底部输入栏自然贴在键盘上沿。
    // 消息列表内部会监听真实 viewport 高度并根据 followLatest 状态决定是否保持底部锚定。
    BoxWithConstraints(
        modifier = Modifier
            .fillMaxSize()
            .imePadding()
    ) {
        // 手势阈值用聊天页真实占用的宽度：手机上是整屏宽，平板双栏时是右半栏宽。
        val screenWidthPx = with(density) { maxWidth.toPx() }
        // ========== 聊天界面（底层）==========
        Scaffold(
            containerColor = MaterialTheme.colorScheme.background.copy(alpha = 0f),
            contentWindowInsets = WindowInsets(0, 0, 0, 0),
            snackbarHost = {
                SnackbarHost(hostState = snackbarHostState) { data ->
                    Snackbar(
                        snackbarData = data,
                        containerColor = MaterialTheme.colorScheme.surfaceVariant,
                        contentColor = TextPrimary
                    )
                }
            },
            topBar = {
                ChatTopBar(
                    displayName = activePersonaInfo.displayName,
                    avatarUrl = activePersonaInfo.avatarUrl,
                    avatarPath = activePersonaInfo.localAvatarPath,
                    avatarStorage = avatarStorage,
                    onBackClick = onBackClick,
                    onAvatarClick = openCompanionPanel,
                    unreadFromOthers = uiState.unreadFromOthers
                )
            },
            bottomBar = {
                ChatBottomArea(
                    uiState = uiState,
                    morePanelHeight = morePanelHeight,
                    showMorePanel = showMorePanel,
                    resolveImageUrl = { viewModel.resolveImageUrl(it) },
                    onTextChange = { viewModel.updateInputText(it) },
                    onSend = { text ->
                        forceFollowLatestRequest++
                        showMorePanel = false
                        viewModel.sendPendingOrText(text)
                    },
                    onToggleMore = toggleMorePanel,
                    onVoiceInput = {
                        if (uiState.isRecording) {
                            viewModel.stopVoiceRecording()
                        } else {
                            if (viewModel.hasRecordAudioPermission()) {
                                // 语音态会把输入区整块换掉：先收键盘和更多面板，免得悬空
                                keyboardController?.hide()
                                focusManager.clearFocus(force = true)
                                showMorePanel = false
                                viewModel.startVoiceRecording()
                            } else {
                                mediaPickers.requestRecordAudioPermission()
                            }
                        }
                    },
                    onRemovePendingAttachment = { viewModel.removePendingAttachment(it) },
                    onVoiceFinish = { viewModel.stopVoiceRecording() },
                    onVoiceCancel = { viewModel.cancelVoiceRecording() },
                    onPickImages = { showMorePanel = false; mediaPickers.pickImages() },
                    onPickDocuments = { showMorePanel = false; mediaPickers.pickDocuments() }
                )
            }
        ) { paddingValues ->
            ChatContentArea(
                viewModel = viewModel,
                uiState = uiState,
                displayName = activePersonaInfo.displayName,
                forceFollowLatestRequest = forceFollowLatestRequest,
                // 键盘可见性在 imePadding 之外读取，与本次键盘动画是同一份值。
                imeVisible = currentImeHeightPx > 0,
                horizontalContentGestureState = horizontalContentGestureState,
                onEditMessage = { id, text ->
                    editingMessageId = id
                    editingMessageText = text
                },
                modifier = Modifier
                    .fillMaxSize()
                    .padding(paddingValues)
                    .companionPanelSwipeGesture(
                        screenWidthPx = screenWidthPx,
                        touchSlopPx = touchSlopPx,
                        openVelocityThresholdPx = openVelocityThresholdPx,
                        horizontalContentGestureState = horizontalContentGestureState,
                        panelState = companionPanelState,
                        // 键盘显示时聊天区只负责输入/收键盘，不允许顺手拉出右侧伴侣面板。
                        isGestureEnabled = { imeHeightState.value == 0 },
                        isPanelVisible = { showCompanionPanel },
                        onOpeningStarted = { showCompanionPanel = true },
                        onOpenFailed = { showCompanionPanel = false },
                        settleScope = companionScope
                    )
            )
        }

        ChatCompanionPanel(
            chatViewModel = viewModel,
            personaViewModel = personaViewModel,
            statusViewModel = statusViewModel,
            memoryViewModel = memoryViewModel,
            settingsViewModel = settingsViewModel,
            personaUiState = personaUiState,
            localAvatarMap = localAvatarMap,
            viewingFilename = viewingPersona,
            panelState = companionPanelState,
            visible = showCompanionPanel,
            gesturesEnabled = companionDismissGestureEnabled,
            avatarStorage = avatarStorage,
            localMeta = localMeta,
            onRequestClose = closeCompanionPanel,
            onDismissed = { showCompanionPanel = false },
            // 面板只要离开隐藏位就算可见：保证 showCompanionPanel 跟真实位置一致，
            // 不会出现"面板已经在屏幕上、标记却是 false"导致返回键不生效。
            onRevealed = { showCompanionPanel = true },
            onDismissGestureEnabledChange = { companionDismissGestureEnabled = it }
        )
    }

    editingMessageId?.let { id ->
        ChatEditMessageDialog(
            initialText = editingMessageText,
            onDismiss = { editingMessageId = null },
            onConfirm = { text ->
                viewModel.editUserMessage(id, text)
                editingMessageId = null
            },
            textFieldModifier = Modifier.fillMaxWidth()
        )
    }
}
