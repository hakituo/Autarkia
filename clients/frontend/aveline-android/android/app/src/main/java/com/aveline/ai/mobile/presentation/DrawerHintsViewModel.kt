package com.aveline.ai.mobile.presentation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.data.repository.PersonaLocalMetaRepository
import com.aveline.ai.mobile.data.repository.StudyPlanRepository
import com.aveline.ai.mobile.domain.repository.StudyRepository
import com.aveline.ai.mobile.presentation.study.parseTodayStudyMinutes
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import javax.inject.Inject

/**
 * 侧边栏行尾提示状态。
 *
 * @property unreadCount 各 persona 主动消息未读总数，0 表示不显示
 * @property studyRemainingMinutes 今日学习目标还差多少分钟，null 表示不显示
 */
data class DrawerHintsUiState(
    val unreadCount: Int = 0,
    val studyRemainingMinutes: Int? = null
)

/**
 * 侧边栏行尾提示：消息未读数 + 学习剩余时长。
 *
 * 未读数来自本地 Room 流，实时更新；学习剩余时长（日目标 − 今日已学）是后端数据，
 * 没有本地流可观察，由侧边栏展开时调用 [refreshStudyRemaining] 拉取。
 */
@HiltViewModel
class DrawerHintsViewModel @Inject constructor(
    personaLocalMetaRepository: PersonaLocalMetaRepository,
    private val studyRepository: StudyRepository,
    private val studyPlanRepository: StudyPlanRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(DrawerHintsUiState())
    val uiState: StateFlow<DrawerHintsUiState> = _uiState.asStateFlow()

    /** 同一时刻只保留一条刷新链，避免启动预取与展开刷新并发时旧响应覆盖新值。 */
    private var refreshJob: Job? = null

    init {
        viewModelScope.launch {
            personaLocalMetaRepository.observeAll().collect { metas ->
                _uiState.update { it.copy(unreadCount = metas.sumOf { meta -> meta.unreadCount }) }
            }
        }
        refreshStudyRemaining()
    }

    /** 刷新学习剩余时长；请求失败时保留上一次的值，避免提示闪没。 */
    fun refreshStudyRemaining() {
        refreshJob?.cancel()
        refreshJob = viewModelScope.launch {
            val today = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(Date())
            val goalMinutes = studyPlanRepository.getPlan(today)
                .getOrNull()?.dailyGoalMinutes ?: return@launch
            if (goalMinutes <= 0) {
                // 没设日目标就没有"剩余"可言，直接不显示
                _uiState.update { it.copy(studyRemainingMinutes = null) }
                return@launch
            }
            // 后端校验 history_limit 最小为 5；这里只要今日分钟数，取最小值减少负载。
            val actualMinutes = studyRepository.getWorkspaceStudyPanel(historyLimit = 5)
                .getOrNull()?.let(::parseTodayStudyMinutes) ?: return@launch
            _uiState.update {
                it.copy(
                    studyRemainingMinutes = (goalMinutes - actualMinutes)
                        .takeIf { remaining -> remaining > 0 }
                )
            }
        }
    }
}
