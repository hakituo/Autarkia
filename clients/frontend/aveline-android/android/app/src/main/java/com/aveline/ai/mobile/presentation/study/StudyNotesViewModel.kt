package com.aveline.ai.mobile.presentation.study

import android.content.Context
import androidx.collection.LruCache
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.domain.models.DailyNoteContent
import com.aveline.ai.mobile.domain.models.LibraryNote
import com.aveline.ai.mobile.domain.repository.StudyRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import javax.inject.Inject

/**
 * 知识笔记（学习库）域 ViewModel。
 *
 * 从 [StudyDailyViewModel] 中拆分出来,独立管理学习库笔记的列表加载、内容读取与缓存。
 *
 * 缓存策略（三层）：
 * - 磁盘列表快照 [NotesCache.readLibrary]：进入「笔记」时先秒开上次的目录树；
 * - 后端版本指纹 /study-daily/version：与快照记录一致时完全不发列表请求；
 * - 正文内存 [LruCache] + 磁盘镜像：打开单篇时按需读取，旧正文不会被当成新内容。
 *
 * @property context ApplicationContext（用于磁盘缓存）
 * @property studyRepository 学习仓库（读取笔记列表与内容）
 */
@HiltViewModel
class StudyNotesViewModel @Inject constructor(
    @ApplicationContext private val context: Context,
    private val studyRepository: StudyRepository
) : ViewModel() {

    /** 内存缓存：rel_path -> 笔记正文 */
    private val memoryCache = LruCache<String, String>(64)

    /** 磁盘缓存：列表快照 + 正文镜像 */
    private val diskCache = NotesCache(context)

    private val _uiState = MutableStateFlow(StudyNotesUiState())
    val uiState: StateFlow<StudyNotesUiState> = _uiState.asStateFlow()

    /** 当前列表快照对应的后端 library_version */
    @Volatile
    private var cachedVersion: String? = null

    /** 防抖：init 与 ON_RESUME 可能在同一帧内各触发一次 */
    @Volatile
    private var lastCheckAt: Long = 0L

    private var loadJob: Job? = null

    /** 是否已经走过一次列表加载/版本比对（用于 ON_RESUME 时决定要不要检查） */
    @Volatile
    private var hasLoadedOnce = false

    /** 首屏本地快照读取任务；loadLibraryNotes 会先等它完成再判断是否有缓存 */
    private val cacheLoadJob: Job = viewModelScope.launch {
        // 秒开：先读磁盘列表快照，有就直接渲染，不等后端全盘扫描
        val cached = withContext(Dispatchers.IO) { diskCache.readLibrary() } ?: return@launch
        cachedVersion = cached.version
        if (_uiState.value.libraryNotes.isNotEmpty()) return@launch
        // 空库快照也算"检查过"：版本没变时不必再拉一次空列表
        hasLoadedOnce = true
        if (cached.notes.isEmpty()) return@launch
        _uiState.update {
            it.copy(
                libraryNotes = cached.notes,
                noteTree = buildNoteTree(cached.notes),
                isLoading = false
            )
        }
    }

    /**
     * 加载学习库笔记列表(Study 根目录下各科目文件夹的 .md 文件)。
     *
     * 顺序：本地快照（init 已渲染）→ 版本比对 → 仅在版本变化/首次进入时拉列表。
     * 列表没变化时不更新 StateFlow，Compose 不会重组，不会出现刷新闪动。
     *
     * @param force true 表示手动刷新，跳过版本比对直接拉取
     */
    fun loadLibraryNotes(force: Boolean = false) {
        if (!force && loadJob?.isActive == true) return
        if (!force) {
            val now = System.currentTimeMillis()
            if (now - lastCheckAt < MIN_CHECK_INTERVAL_MS) return
            lastCheckAt = now
        }
        // 手动刷新允许打断上一次静默检查，否则按钮点了没反应
        if (force) loadJob?.cancel()

        loadJob = viewModelScope.launch {
            // 等本地快照读完：有快照时不要先亮 loading 再被缓存顶掉，避免闪一下
            cacheLoadJob.join()
            val hasLocalData = _uiState.value.libraryNotes.isNotEmpty()
            // 只有"第一次且没有任何可显示内容"才点亮 loading；之后的静默检查不闪
            val showLoading = !hasLoadedOnce && !hasLocalData
            _uiState.update { it.copy(isLoading = showLoading, error = null) }

            // 先比对版本：没变化就不重拉列表。手动刷新直接跳过比对。
            if (!force) {
                val localVersion = cachedVersion
                val remoteVersion = studyRepository.getStudyVersions()
                    .getOrNull()
                    ?.libraryVersion
                    ?.takeIf { version -> version.isNotBlank() }
                val versionChanged = remoteVersion != null && remoteVersion != localVersion
                if (remoteVersion != null) {
                    cachedVersion = remoteVersion
                }
                if ((hasLoadedOnce || hasLocalData) && remoteVersion != null && !versionChanged) {
                    hasLoadedOnce = true
                    _uiState.update { it.copy(isLoading = false) }
                    return@launch
                }
            }

            studyRepository.getLibraryNotes(force = force)
                .onSuccess { payload ->
                    hasLoadedOnce = true
                    val visibleNotes = payload.notes.filter { !it.isHidden() }
                    if (payload.version.isNotBlank()) {
                        cachedVersion = payload.version
                    }
                    val changed = visibleNotes != _uiState.value.libraryNotes
                    withContext(Dispatchers.IO) {
                        // 旧实现会对每篇未缓存笔记调用 write("")：既造 N 个空文件，
                        // 又 N 次重写 index.json（O(N²)）。这里只更新列表快照。
                        diskCache.writeLibrary(visibleNotes, cachedVersion)
                    }
                    _uiState.update {
                        it.copy(
                            libraryNotes = if (changed) visibleNotes else it.libraryNotes,
                            noteTree = if (changed) buildNoteTree(visibleNotes) else it.noteTree,
                            isLoading = false,
                            error = null
                        )
                    }
                }
                .onFailure { e ->
                    _uiState.update {
                        it.copy(
                            // 失败时保留已渲染的本地快照，只把错误挂出来
                            isLoading = false,
                            error = e.message ?: "加载学习库失败"
                        )
                    }
                }
        }
    }

    /**
     * 回到学习页时的静默检查。
     *
     * 只有已经加载过笔记（或本地有快照）才检查，避免用户没进过笔记板块也去拉列表。
     */
    fun refreshIfLoaded() {
        if (!hasLoadedOnce && _uiState.value.libraryNotes.isEmpty()) return
        loadLibraryNotes(force = false)
    }

    /**
     * 加载学习库中指定笔记内容(按相对路径)。
     *
     * 命中顺序：内存 LruCache → 磁盘缓存(与后端 updated_ts 一致) → 后端。
     * 磁盘内容过期时不展示旧正文，直接走后端并回写。
     *
     * @param path 相对于学习根目录的路径,如 "Mathematics/极限.md"
     */
    fun loadLibraryNote(path: String) {
        // 内存命中直接展示,避免任何 IO
        memoryCache.get(path)?.let { cached ->
            _uiState.update {
                it.copy(
                    currentNoteContent = DailyNoteContent(
                        filename = path.substringAfterLast("/"),
                        path = path,
                        content = cached
                    )
                )
            }
            return
        }

        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            val latestTs = _uiState.value.libraryNotes
                .firstOrNull { note -> note.relPath == path }
                ?.updatedTs
                ?: 0L

            // 磁盘命中(内容与后端 ts 一致)则直接读本地；过期内容不能冒充新内容
            val disk = withContext(Dispatchers.IO) {
                if (latestTs > 0 && !diskCache.isContentFresh(path, latestTs)) {
                    null
                } else {
                    diskCache.readContent(path)
                }
            }
            if (!disk.isNullOrBlank()) {
                memoryCache.put(path, disk)
                _uiState.update {
                    it.copy(
                        currentNoteContent = DailyNoteContent(
                            filename = path.substringAfterLast("/"),
                            path = path,
                            content = disk
                        ),
                        isLoading = false
                    )
                }
                return@launch
            }
            // 走后端
            studyRepository.getLibraryNote(path)
                .onSuccess { content ->
                    // 优先用后端返回的 ts；旧后端没返回时退回列表里的 ts
                    val ts = content.updatedTs.takeIf { it > 0 } ?: latestTs
                    withContext(Dispatchers.IO) {
                        memoryCache.put(content.path, content.content)
                        diskCache.write(content.path, content.content, ts)
                    }
                    _uiState.update {
                        it.copy(currentNoteContent = content, isLoading = false)
                    }
                }
                .onFailure { e ->
                    _uiState.update {
                        it.copy(isLoading = false, error = e.message ?: "加载笔记内容失败")
                    }
                }
        }
    }

    /**
     * 打开指定笔记进入阅读页，并触发内容加载（内存/磁盘/后端三级缓存）。
     *
     * 切换文件时先清空旧内容，避免阅读页短暂显示上一篇笔记。
     *
     * @param path 笔记相对路径，如 "Biology/08_专项练习/01_分子与细胞/笔记.md"
     */
    fun openNote(path: String) {
        _uiState.update {
            it.copy(
                selectedNotePath = path,
                isReaderOpen = true,
                currentNoteContent = null
            )
        }
        loadLibraryNote(path)
    }

    /** 关闭阅读页 */
    fun closeReader() {
        _uiState.update { it.copy(isReaderOpen = false) }
    }

    /** 清除错误信息 */
    fun clearError() {
        _uiState.update { it.copy(error = null) }
    }

    private companion object {
        /** 同一秒内重复进入不重复做版本检查 */
        private const val MIN_CHECK_INTERVAL_MS = 1_500L
    }
}

/**
 * 知识笔记域 UI 状态。
 *
 * @property libraryNotes 学习库笔记列表(按后端返回顺序)
 * @property noteTree 文件夹树（顶层为科目文件夹）
 * @property currentNoteContent 当前打开的笔记内容
 * @property selectedNotePath 当前打开的笔记相对路径
 * @property isReaderOpen 是否显示阅读页
 * @property isLoading 是否加载中
 * @property error 错误信息
 */
data class StudyNotesUiState(
    val libraryNotes: List<LibraryNote> = emptyList(),
    val noteTree: List<NoteTreeNode> = emptyList(),
    val currentNoteContent: DailyNoteContent? = null,
    val selectedNotePath: String? = null,
    val isReaderOpen: Boolean = false,
    val isLoading: Boolean = false,
    val error: String? = null
)
