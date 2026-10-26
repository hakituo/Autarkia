package com.aveline.ai.mobile.presentation.chat

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.domain.models.Message
import com.aveline.ai.mobile.presentation.components.HorizontalContentGestureState
import com.aveline.ai.mobile.presentation.components.LocalHorizontalContentGestureState
import com.aveline.ai.mobile.presentation.components.MediaPreview
import com.aveline.ai.mobile.presentation.components.MessageBubble
import com.aveline.ai.mobile.presentation.components.MessageData
import com.aveline.ai.mobile.presentation.components.MessageType
import com.aveline.ai.mobile.presentation.components.StageDirectionRow
import com.aveline.ai.mobile.presentation.components.TimeSeparator
import com.aveline.ai.mobile.presentation.components.shouldShowTimeSeparator
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import kotlinx.coroutines.flow.distinctUntilChanged

private const val INITIAL_HISTORY_WINDOW = 50
private const val HISTORY_PAGE_SIZE = 50
private const val HISTORY_LOAD_THRESHOLD = 3

data class ChatMessageActions(
    val onPlayTTS: (String) -> Unit,
    val onCopy: (String) -> Unit,
    val onDelete: (String) -> Unit,
    val onRegenerate: (String) -> Unit,
    val onEdit: (String, String) -> Unit,
    val onSwitchVariant: (String, Int) -> Unit
)

@Composable
fun ChatMessageList(
    messages: List<Message>,
    sessionId: String?,
    isLoading: Boolean,
    loadingState: LoadingState,
    playingMessageId: String?,
    displayName: String? = null,
    ttsLoadingMessageId: String? = null,
    horizontalContentGestureState: HorizontalContentGestureState,
    actions: ChatMessageActions,
    forceFollowLatestRequest: Int = 0,
    /**
     * 软键盘是否可见。由聊天页根层（整页 imePadding 之外）传入。
     * 列表自己读 insets 拿不到"键盘正在弹出"这件事与页面布局的先后关系，
     * 只有根层那一份才是与本次键盘动画同步的。
     */
    imeVisible: Boolean = false,
    hasOlderMessages: Boolean = false,
    onLoadOlderMessages: () -> Unit = {},
    /** 点图片/表情包/视频时回调，由外层打开全屏查看器；为 null 时媒体不可点 */
    onMediaClick: ((MediaPreview) -> Unit)? = null,
    /** 设置页「动作描写」开关；false 时历史上标成 retraction 的消息也按普通气泡显示。 */
    stageDirectionEnabled: Boolean = true,
    modifier: Modifier = Modifier
) {
    // 等待回复时插入的那条空白 AI 占位不参与列表布局。
    //
    // 它是"给对方留的位置"：占位一上屏，列表底部就多出一行（外加 Arrangement 的间距），
    // 回复为空 / 静默回复（角色在做事，replyMode=silent）时占位又被删掉，底部再缩回去 ——
    // 用户看到的就是「发完消息抖一下，过一会儿又抖回来」。
    // IM 里发消息不该有这种预留位：自己的气泡发出去就结束，她的回复有内容了才出现。
    val displayMessages = remember(messages) {
        messages.filterNot { it.isBlankAssistantPlaceholder() }
    }

    if (displayMessages.isEmpty()) {
        EmptyMessageList(
            isLoading = isLoading,
            loadingState = loadingState,
            displayName = displayName,
            modifier = modifier
        )
        return
    }

    var historyWindowSize by remember(sessionId) {
        mutableIntStateOf(INITIAL_HISTORY_WINDOW)
    }
    val visibleMessages = remember(displayMessages, historyWindowSize) {
        displayMessages.takeLast(historyWindowSize)
    }
    val hasOlderHistory = displayMessages.size > visibleMessages.size || hasOlderMessages

    LoadedMessageList(
        messages = visibleMessages,
        sessionId = sessionId,
        hasOlderHistory = hasOlderHistory,
        onLoadOlderHistory = {
            historyWindowSize += HISTORY_PAGE_SIZE
            if (historyWindowSize > displayMessages.size && hasOlderMessages) onLoadOlderMessages()
        },
        playingMessageId = playingMessageId,
        ttsLoadingMessageId = ttsLoadingMessageId,
        horizontalContentGestureState = horizontalContentGestureState,
        actions = actions,
        forceFollowLatestRequest = forceFollowLatestRequest,
        imeVisible = imeVisible,
        onMediaClick = onMediaClick,
        stageDirectionEnabled = stageDirectionEnabled,
        modifier = modifier
    )
}

@Composable
private fun LoadedMessageList(
    messages: List<Message>,
    sessionId: String?,
    hasOlderHistory: Boolean,
    onLoadOlderHistory: () -> Unit,
    playingMessageId: String?,
    ttsLoadingMessageId: String?,
    horizontalContentGestureState: HorizontalContentGestureState,
    actions: ChatMessageActions,
    forceFollowLatestRequest: Int,
    imeVisible: Boolean,
    onMediaClick: ((MediaPreview) -> Unit)?,
    /** 设置页「动作描写」开关；false 时历史上标成 retraction 的消息也按普通气泡显示。 */
    stageDirectionEnabled: Boolean,
    modifier: Modifier
) {
    val latestItemIndex = messages.lastIndex
    val listState = rememberLazyListState(
        initialFirstVisibleItemIndex = latestItemIndex
    )

    val focusManager = LocalFocusManager.current
    val keyboardController = LocalSoftwareKeyboardController.current

    var previousTailMessageId by remember(sessionId) {
        mutableStateOf(messages.lastOrNull()?.id)
    }
    var followLatest by remember(sessionId) { mutableStateOf(true) }
    var pendingForceFollow by remember(sessionId) { mutableStateOf(false) }
    var previousForceFollowRequest by remember(sessionId) {
        mutableIntStateOf(forceFollowLatestRequest)
    }
    var programmaticFollowInProgress by remember(sessionId) { mutableStateOf(false) }
    // 操作栏默认全部收起，点击某条消息后才展开它自己的操作栏；
    // 同一时刻最多展开一条，点另一条会替换上一条。
    var revealedActionsMessageId by remember(sessionId) { mutableStateOf<String?>(null) }
    // 展开的操作栏是往下撑高的，既不改变 messages 也不改变 tailTextLength，
    // 所以要单独记录它的实测高度，作为底部锚定的触发 key（见下方 LaunchedEffect）。
    // 用 revealedActionsMessageId 作为 remember key，切换/收起时自动归零。
    var revealedActionsBarHeightPx by remember(sessionId, revealedActionsMessageId) {
        mutableIntStateOf(0)
    }

    suspend fun scrollToLatest() {
        if (latestItemIndex < 0) return
        programmaticFollowInProgress = true
        try {
            listState.scrollToItem(latestItemIndex)
            followLatest = true
        } finally {
            programmaticFollowInProgress = false
        }
    }

    LaunchedEffect(sessionId, messages.size) {
        snapshotFlow {
            val lastVisibleIndex = listState.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: -1
            val atLatest = lastVisibleIndex >= (latestItemIndex - 1).coerceAtLeast(0)
            Triple(listState.isScrollInProgress, atLatest, programmaticFollowInProgress)
        }
            .distinctUntilChanged()
            .collect { (isScrolling, atLatest, isProgrammatic) ->
                if (isScrolling && !isProgrammatic) {
                    followLatest = atLatest
                    // 用户主动滚动时收起已展开的操作栏，避免操作栏跟着消息滑来滑去。
                    revealedActionsMessageId = null
                }
            }
    }

    LaunchedEffect(sessionId, forceFollowLatestRequest) {
        if (forceFollowLatestRequest != previousForceFollowRequest) {
            previousForceFollowRequest = forceFollowLatestRequest
            // 只登记"下一条消息一定要跟到底"，**不在这里立刻滚动**：
            // 发送是异步的（预检要读一次历史），此刻新气泡还没进列表，
            // 先滚一次再等气泡上屏后滚第二次，就是发消息时底部那一下抖动。
            // 真正的滚动由下面"尾条变化"的 effect 在气泡真的出现后做一次。
            pendingForceFollow = true
            followLatest = true
        }
    }

    LaunchedEffect(sessionId, hasOlderHistory, messages.firstOrNull()?.id) {
        if (!hasOlderHistory) return@LaunchedEffect
        snapshotFlow { listState.firstVisibleItemIndex }
            .distinctUntilChanged()
            .collect { firstVisibleIndex ->
                if (firstVisibleIndex <= HISTORY_LOAD_THRESHOLD) {
                    onLoadOlderHistory()
                }
            }
    }

    LaunchedEffect(sessionId, messages.lastOrNull()?.id, messages.size) {
        val currentTailId = messages.lastOrNull()?.id
        val tailChanged = previousTailMessageId != null && currentTailId != previousTailMessageId

        if (tailChanged) {
            when {
                pendingForceFollow -> {
                    scrollToLatest()
                    pendingForceFollow = false
                }
                followLatest -> scrollToLatest()
            }
        }
        previousTailMessageId = currentTailId
    }

    val tailTextLength = messages.lastOrNull()?.text?.length ?: 0
    LaunchedEffect(sessionId, messages.lastOrNull()?.id, tailTextLength) {
        if (followLatest && !pendingForceFollow) {
            scrollToLatest()
        }
    }

    // 展开操作栏时把它重新锚定到输入框上方，否则最后一条的操作栏会撑到可视区外被输入框盖住。
    // 展开的正好是最后一条时无条件锚定（用户点它就是想操作它）；其余情况只在原本就跟随最新时锚定，
    // 不打断用户翻历史。revealedActionsBarHeightPx 每帧变化都会重新触发，跟着展开动画一起贴底。
    LaunchedEffect(sessionId, revealedActionsMessageId, revealedActionsBarHeightPx) {
        val revealedId = revealedActionsMessageId ?: return@LaunchedEffect
        if (revealedId == messages.lastOrNull()?.id || followLatest) {
            scrollToLatest()
        }
    }

    var listViewportHeightPx by remember(sessionId) { mutableIntStateOf(0) }
    var previousListHeightPx by remember(sessionId) { mutableIntStateOf(0) }

    // 键盘真正可见的那一刻无条件贴住最新消息（QQ/微信行为）。
    // 旧实现只在 followLatest 为 true 时跟随：用户翻着历史点输入框时 followLatest 是 false，
    // 键盘就只把页面压矮、末尾几条被裁掉，看起来像"键盘直接盖在聊天上"。
    LaunchedEffect(sessionId, imeVisible) {
        if (!imeVisible) return@LaunchedEffect
        followLatest = true
        scrollToLatest()
    }

    LaunchedEffect(listViewportHeightPx) {
        val previous = previousListHeightPx
        previousListHeightPx = listViewportHeightPx
        // 键盘弹出/收起会把 viewport 高度逐帧报上来（IME 动画约 300ms）。
        // 键盘可见期间不看 followLatest：每一帧都要重新贴底，
        // 否则只会按旧的最大滚动量钳制，动画结束后末尾几条仍然被切掉。
        if (previous > 0 && listViewportHeightPx != previous) {
            if (imeVisible) followLatest = true
            if (followLatest) scrollToLatest()
        }
    }

    LazyColumn(
        state = listState,
        modifier = modifier
            .fillMaxSize()
            .pointerInput(imeVisible) {
                if (!imeVisible) return@pointerInput
                awaitEachGesture {
                    val down = awaitFirstDown(
                        requireUnconsumed = false,
                        pass = PointerEventPass.Initial
                    )
                    val start = down.position
                    var isTap = true
                    while (true) {
                        val event = awaitPointerEvent(pass = PointerEventPass.Initial)
                        val change = event.changes.firstOrNull { it.id == down.id } ?: break
                        if ((change.position - start).getDistance() > viewConfiguration.touchSlop) {
                            isTap = false
                        }
                        if (!change.pressed) {
                            if (isTap) {
                                keyboardController?.hide()
                                focusManager.clearFocus(force = true)
                            }
                            break
                        }
                    }
                }
            }
            .onSizeChanged { listViewportHeightPx = it.height },
        verticalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        items(
            count = messages.size,
            key = { index -> messages[index].id }
        ) { index ->
            val message = messages[index]
            val previousMessage = messages.getOrNull(index - 1)
            // 开关关闭时不认历史 retraction 标记：老消息的括号在写库时已被剥掉，
            // 这里只能让它以普通气泡显示，否则用户会觉得「关了开关还是一片居中的灰字」。
            val isRetraction = stageDirectionEnabled && !message.isUser && message.messageType == "retraction"
            val isSystemNarration = !message.isUser && !isRetraction && (
                message.text == "新话题已开启。" || message.text.contains("系统就绪")
            )
            // 空白 AI 占位在进入列表前已被过滤，这里只会是真实消息。
            val showSeparator = shouldShowTimeSeparator(
                previousTimestamp = previousMessage?.timestamp,
                currentTimestamp = message.timestamp
            )

            Column {
                if (showSeparator && !isSystemNarration && !isRetraction) {
                    TimeSeparator(timestamp = message.timestamp)
                }

                when {
                    // 系统提示与括号动作描写共用同一行样式，避免聊天页出现两套"居中灰字 + 横线"
                    isSystemNarration -> StageDirectionRow(text = message.text)
                    else -> CompositionLocalProvider(
                        LocalHorizontalContentGestureState provides horizontalContentGestureState
                    ) {
                        Column {
                            MessageBubble(
                                message = MessageData(
                                    id = message.id,
                                    text = message.text,
                                    isUser = message.isUser,
                                    timestamp = message.timestamp,
                                    imageUrl = message.imageUrl,
                                    videoUrl = message.videoUrl,
                                    attachments = message.attachments,
                                    emotion = message.emotion,
                                    // 版本导航统一交给下方 ChatMessageActionBar，避免旧组件再画一排。
                                    variantIndex = 0,
                                    variantCount = 1,
                                    messageType = when {
                                        isRetraction -> MessageType.RETRACTION
                                        message.isUser -> MessageType.USER
                                        else -> MessageType.AI
                                    }
                                ),
                                onToggleActions = {
                                    revealedActionsMessageId =
                                        if (revealedActionsMessageId == message.id) null else message.id
                                },
                                onMediaClick = onMediaClick,
                                stageDirectionEnabled = stageDirectionEnabled
                            )

                            // 操作栏点击消息后才展开，默认不占位。
                            AnimatedVisibility(
                                visible = !isRetraction && revealedActionsMessageId == message.id,
                                enter = fadeIn() + expandVertically(),
                                exit = fadeOut() + shrinkVertically(),
                                // 把展开动画每帧的实际高度报给外层，驱动列表底部锚定。
                                // 收起态高度为 0，这里只上报当前展开的那条，避免别的 item 把它清零。
                                modifier = Modifier.onSizeChanged { size ->
                                    if (revealedActionsMessageId == message.id) {
                                        revealedActionsBarHeightPx = size.height
                                    }
                                }
                            ) {
                                ChatMessageActionBar(
                                    message = message,
                                    isPlaying = playingMessageId == message.id,
                                    isTtsLoading = ttsLoadingMessageId == message.id,
                                    actions = actions
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

private fun Message.isBlankAssistantPlaceholder(): Boolean =
    !isUser &&
        messageType != "retraction" &&
        text.isBlank() &&
        imageUrl.isNullOrBlank() &&
        videoUrl.isNullOrBlank()

@Composable
private fun EmptyMessageList(
    isLoading: Boolean,
    loadingState: LoadingState,
    displayName: String? = null,
    modifier: Modifier
) {
    LazyColumn(
        modifier = modifier.fillMaxSize(),
        verticalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        if (!isLoading) {
            item {
                when (loadingState) {
                    is LoadingState.NotLoaded -> {
                        EmptyChatState(
                            displayName = displayName,
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = 48.dp)
                        )
                    }
                    is LoadingState.Loading -> Unit
                    is LoadingState.Loaded -> Unit
                }
            }
        }
    }
}

@Composable
private fun EmptyChatState(
    displayName: String? = null,
    modifier: Modifier = Modifier
) {
    val name = displayName?.trim().takeUnless { it.isNullOrBlank() }
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text(
            text = if (name != null) "开始和 $name 聊天吧" else "开始聊天吧",
            style = MaterialTheme.typography.titleMedium,
            color = TextSecondary
        )

        Spacer(modifier = Modifier.height(8.dp))

        Text(
            text = "发送消息开始对话",
            style = MaterialTheme.typography.bodyMedium,
            color = TextSecondary.copy(alpha = 0.7f)
        )
    }
}
