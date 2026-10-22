package com.aveline.ai.mobile.presentation.study

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.domain.models.CalendarDay
import com.aveline.ai.mobile.domain.models.DailyContent
import com.aveline.ai.mobile.domain.models.DailyNote
import com.aveline.ai.mobile.domain.models.DiaryEntry
import com.aveline.ai.mobile.domain.models.LatestProgress
import com.aveline.ai.mobile.domain.repository.StudyRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale
import javax.inject.Inject

/**
 * Study/Daily 文件夹 UI 状态。
 *
 * 持有日历、当日内容、笔记列表、笔记内容、最新进度等数据,
 * 由 [StudyDailyViewModel] 管理,供 Study 模块各 Tab 共享。
 *
 * @property calendarDays 月度日历数据
 * @property currentDateContent 当前选中日期的 diary/plan/progress 内容
 * @property dailyNotes 专题笔记列表
 * @property latestProgress 最新学习进度
 * @property selectedDate 当前选中的日期(yyyy-MM-dd)
 * @property isLoading 是否加载中
 * @property error 错误信息
 */
data class StudyDailyUiState(
    val calendarDays: List<CalendarDay> = emptyList(),
    val currentDateContent: DailyContent? = null,
    val dailyNotes: List<DailyNote> = emptyList(),
    val latestProgress: LatestProgress? = null,
    val diaryEntries: List<DiaryEntry> = emptyList(),
    val selectedDate: String = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(Date()),
    val isLoading: Boolean = false,
    val error: String? = null
)

/**
 * Study/Daily 文件夹专用 ViewModel。
 *
 * 由于 [StudyViewModel] 已超过 500 行限制,这里独立拆分,
 * 专门处理 Study/Daily 文件夹相关的数据加载:
 * - 月度日历(标记哪些日期有 diary/plan/progress)
 * - 按日期读取 diary/plan/progress 全部内容
 * - 专题笔记列表与内容
 * - 最新学习进度
 *
 * 刷新策略：
 * - 首次进入必须加载（本地没有缓存的数据可展示）；
 * - 之后回到学习页先比对 /study-daily/version，Daily 指纹没变就完全不重拉；
 * - 已有数据时的刷新是静默的：不点亮刷新按钮，内容相同 StateFlow 不发射，
 *   Compose 不会重组，也就没有刷新闪动。
 */
@HiltViewModel
class StudyDailyViewModel @Inject constructor(
    @ApplicationContext private val context: Context,
    private val studyRepository: StudyRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(StudyDailyUiState())
    val uiState: StateFlow<StudyDailyUiState> = _uiState.asStateFlow()

    /** 正在进行的加载任务数：为 0 才算"这一轮加载结束" */
    private var pendingLoads = 0

    /** 上次比对/加载时对应的 Daily 目录指纹 */
    @Volatile
    private var lastKnownDailyVersion: String? = null

    @Volatile
    private var isCheckingChanges = false

    init {
        // 初始化时加载当月日历、当前日期内容(计划/日记，内部会触发 loadDiaries)、笔记列表和最新进度
        val now = Calendar.getInstance()
        val dateFormat = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault())
        loadCalendar(now.get(Calendar.YEAR), now.get(Calendar.MONTH) + 1)
        loadDateContent(dateFormat.format(now.time))
        loadNotes()
        loadLatestProgress()
        // 记录当前数据对应的版本，供下次回到学习页时比对（轻量请求，失败忽略）
        viewModelScope.launch {
            lastKnownDailyVersion = studyRepository.getStudyVersions()
                .getOrNull()
                ?.dailyVersion
                ?.takeIf { it.isNotBlank() }
        }
    }

    private fun beginLoad() {
        pendingLoads += 1
    }

    private fun endLoad() {
        pendingLoads = (pendingLoads - 1).coerceAtLeast(0)
        if (pendingLoads == 0) {
            _uiState.update { it.copy(isLoading = false) }
        }
    }

    /**
     * 加载月度日历数据。
     *
     * @param year 年份,如 2026
     * @param month 月份,1-12
     */
    fun loadCalendar(year: Int, month: Int, forceLoading: Boolean = false) {
        viewModelScope.launch {
            beginLoad()
            try {
                _uiState.update {
                    // 已有日历就静默刷新，点亮刷新按钮只会造成无意义的闪动
                    it.copy(
                        isLoading = forceLoading || it.calendarDays.isEmpty(),
                        error = null
                    )
                }
                studyRepository.getCalendar(year, month)
                    .onSuccess { days ->
                        _uiState.update { it.copy(calendarDays = days) }
                    }
                    .onFailure { e ->
                        _uiState.update { it.copy(error = e.message ?: "加载日历失败") }
                    }
            } finally {
                endLoad()
            }
        }
    }

    /**
     * 按日期加载 diary/plan/progress 全部内容,同时更新 selectedDate。
     * 切换日期时也会触发 [loadDiaries] 刷新当日日记列表。
     *
     * @param date 日期字符串,格式 yyyy-MM-dd
     */
    fun loadDateContent(date: String, forceLoading: Boolean = false) {
        viewModelScope.launch {
            beginLoad()
            try {
                _uiState.update {
                    // 切换日期才需要 loading；同一日期静默刷新不闪
                    it.copy(
                        isLoading = forceLoading ||
                            it.currentDateContent == null ||
                            it.selectedDate != date,
                        error = null,
                        selectedDate = date
                    )
                }
                studyRepository.getDateContent(date)
                    .onSuccess { content ->
                        _uiState.update { it.copy(currentDateContent = content) }
                    }
                    .onFailure { e ->
                        _uiState.update { it.copy(error = e.message ?: "加载日期内容失败") }
                    }
            } finally {
                endLoad()
            }
        }
        // 切换日期时同步刷新日记列表(journal 系统)
        loadDiaries(date)
    }

    /**
     * 加载指定日期的日记列表(journal 系统,按作者 source 分组)。
     *
     * @param date 日期字符串,格式 yyyy-MM-dd
     */
    fun loadDiaries(date: String) {
        viewModelScope.launch {
            beginLoad()
            try {
                studyRepository.getDiaries(date)
                    .onSuccess { entries ->
                        _uiState.update { it.copy(diaryEntries = entries) }
                    }
                    .onFailure { e ->
                        _uiState.update {
                            it.copy(error = e.message ?: "加载日记列表失败")
                        }
                    }
            } finally {
                endLoad()
            }
        }
    }

    /**
     * 加载所有专题笔记列表。
     */
    fun loadNotes(forceLoading: Boolean = false) {
        viewModelScope.launch {
            beginLoad()
            try {
                _uiState.update {
                    it.copy(
                        isLoading = forceLoading || it.dailyNotes.isEmpty(),
                        error = null
                    )
                }
                studyRepository.getNotes()
                    .onSuccess { notes ->
                        _uiState.update { it.copy(dailyNotes = notes) }
                    }
                    .onFailure { e ->
                        _uiState.update { it.copy(error = e.message ?: "加载笔记列表失败") }
                    }
            } finally {
                endLoad()
            }
        }
    }

    /**
     * 加载最新的学习进度文件内容。
     */
    fun loadLatestProgress() {
        viewModelScope.launch {
            beginLoad()
            try {
                studyRepository.getLatestProgress()
                    .onSuccess { progress ->
                        _uiState.update { it.copy(latestProgress = progress) }
                    }
                    .onFailure { e ->
                        // 最新进度加载失败不阻塞主流程,仅记录错误
                        _uiState.update {
                            it.copy(error = e.message ?: "加载最新进度失败")
                        }
                    }
            } finally {
                endLoad()
            }
        }
    }

    /**
     * 选择日期,触发 [loadDateContent]。
     *
     * @param date 日期字符串,格式 yyyy-MM-dd
     */
    fun selectDate(date: String) {
        loadDateContent(date)
    }

    /**
     * 回到学习页时的变更检查。
     *
     * 请求 Daily 目录指纹：与上次一致就什么都不做；变了才静默刷新日历/进度/笔记。
     * 首次进入由 init 负责加载，这里只记录版本，避免重复请求。
     */
    fun checkForChanges() {
        if (isCheckingChanges || pendingLoads > 0) return
        val hasData = _uiState.value.calendarDays.isNotEmpty() ||
            _uiState.value.currentDateContent != null ||
            _uiState.value.dailyNotes.isNotEmpty()
        if (!hasData) return

        isCheckingChanges = true
        viewModelScope.launch {
            try {
                val remoteVersion = studyRepository.getStudyVersions()
                    .getOrNull()
                    ?.dailyVersion
                    ?.takeIf { it.isNotBlank() }
                    ?: return@launch
                if (remoteVersion == lastKnownDailyVersion) return@launch
                lastKnownDailyVersion = remoteVersion
                refreshAll(force = false)
            } finally {
                isCheckingChanges = false
            }
        }
    }

    /**
     * 刷新全部 Daily 数据(日历 + 最新进度 + 笔记列表)。
     *
     * @param force true 表示手动刷新：跳过静默策略并恢复 loading 动画
     */
    fun refreshAll(force: Boolean = false) {
        val now = Calendar.getInstance()
        loadCalendar(
            now.get(Calendar.YEAR),
            now.get(Calendar.MONTH) + 1,
            forceLoading = force
        )
        loadLatestProgress()
        loadNotes(forceLoading = force)
        if (force) {
            loadDateContent(_uiState.value.selectedDate, forceLoading = true)
        }
    }

    /**
     * 清除错误信息。
     */
    fun clearError() {
        _uiState.update { it.copy(error = null) }
    }
}
