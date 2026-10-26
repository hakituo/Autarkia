package com.aveline.ai.mobile.presentation.tools

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.domain.models.*
import com.aveline.ai.mobile.domain.repository.ToolsRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import javax.inject.Inject

data class ToolsUiState(
    val foodMenu: List<FoodItem> = emptyList(),
    val foodInventory: List<FoodInventoryItem> = emptyList(),
    val notifications: List<NotificationItem> = emptyList(),
    val intentText: String = "",
    val intentResult: IntentResult? = null,
    val systemResources: JsonElement? = null,
    val systemStats: JsonElement? = null,
    val preferences: SystemPreferences = SystemPreferences(),
    val sensitiveEnabled: Boolean? = null,
    val isFoodLoading: Boolean = false,
    val isNotificationsLoading: Boolean = false,
    val isIntentLoading: Boolean = false,
    val isSystemLoading: Boolean = false,
    val isPreferencesLoading: Boolean = false,
    val isSensitiveLoading: Boolean = false,
    val message: String? = null,
    val error: String? = null
)

@HiltViewModel
class ToolsViewModel @Inject constructor(
    private val toolsRepository: ToolsRepository
) : ViewModel() {
    private val _uiState = MutableStateFlow(ToolsUiState())
    val uiState: StateFlow<ToolsUiState> = _uiState.asStateFlow()

    fun setIntentText(value: String) {
        _uiState.update { it.copy(intentText = value) }
    }

    fun updateMode(value: String) {
        _uiState.update { it.copy(preferences = it.preferences.copy(mode = value)) }
    }

    fun updateResponseLength(value: String) {
        _uiState.update { it.copy(preferences = it.preferences.copy(responseLength = value)) }
    }

    fun updateConversationStyle(value: String) {
        _uiState.update { it.copy(preferences = it.preferences.copy(conversationStyle = value)) }
    }

    fun updateSensitivity(value: String) {
        _uiState.update { it.copy(preferences = it.preferences.copy(sensitivity = value)) }
    }

    fun toggleActiveCare(enabled: Boolean) {
        _uiState.update { it.copy(preferences = it.preferences.copy(activeCareEnabled = enabled)) }
    }

    fun toggleDebugVisible(enabled: Boolean) {
        _uiState.update { it.copy(preferences = it.preferences.copy(debugVisible = enabled)) }
    }

    fun loadFoodMenu() {
        viewModelScope.launch {
            _uiState.update { it.copy(isFoodLoading = true, error = null, message = null) }
            val result = toolsRepository.getFoodMenu(null)
            _uiState.update {
                result.fold(
                    onSuccess = { items ->
                        it.copy(isFoodLoading = false, foodMenu = items)
                    },
                    onFailure = { e ->
                        it.copy(isFoodLoading = false, error = "获取菜单失败: ${e.message}")
                    }
                )
            }
        }
    }

    fun loadFoodInventory() {
        viewModelScope.launch {
            _uiState.update { it.copy(isFoodLoading = true, error = null, message = null) }
            val result = toolsRepository.getFoodInventory()
            _uiState.update {
                result.fold(
                    onSuccess = { items ->
                        it.copy(isFoodLoading = false, foodInventory = items)
                    },
                    onFailure = { e ->
                        it.copy(isFoodLoading = false, error = "获取库存失败: ${e.message}")
                    }
                )
            }
        }
    }

    fun buyFood(foodId: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(isFoodLoading = true, error = null, message = null) }
            val result = toolsRepository.buyFood(foodId, 1)
            _uiState.update {
                result.fold(
                    onSuccess = { res ->
                        it.copy(isFoodLoading = false, message = res.message)
                    },
                    onFailure = { e ->
                        it.copy(isFoodLoading = false, error = "购买失败: ${e.message}")
                    }
                )
            }
            loadFoodInventory()
        }
    }

    fun eatFood(foodId: String, recipient: String = "self") {
        viewModelScope.launch {
            _uiState.update { it.copy(isFoodLoading = true, error = null, message = null) }
            val result = toolsRepository.eatFood(foodId, true, recipient)
            _uiState.update {
                result.fold(
                    onSuccess = { res ->
                        it.copy(isFoodLoading = false, message = res.message)
                    },
                    onFailure = { e ->
                        it.copy(isFoodLoading = false, error = "食用失败: ${e.message}")
                    }
                )
            }
            loadFoodInventory()
        }
    }

    fun loadNotifications() {
        viewModelScope.launch {
            _uiState.update { it.copy(isNotificationsLoading = true, error = null, message = null) }
            val result = toolsRepository.getNotifications("default")
            _uiState.update {
                result.fold(
                    onSuccess = { items ->
                        it.copy(isNotificationsLoading = false, notifications = items)
                    },
                    onFailure = { e ->
                        it.copy(isNotificationsLoading = false, error = "获取通知失败: ${e.message}")
                    }
                )
            }
        }
    }

    fun runIntent() {
        val text = _uiState.value.intentText.trim()
        if (text.isEmpty()) {
            _uiState.update { it.copy(error = "请输入意图文本") }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isIntentLoading = true, error = null, message = null) }
            val result = toolsRepository.classifyIntent(text)
            _uiState.update {
                result.fold(
                    onSuccess = { intent ->
                        it.copy(isIntentLoading = false, intentResult = intent)
                    },
                    onFailure = { e ->
                        it.copy(isIntentLoading = false, error = "识别失败: ${e.message}")
                    }
                )
            }
        }
    }

    fun loadSystemResources() {
        viewModelScope.launch {
            _uiState.update { it.copy(isSystemLoading = true, error = null, message = null) }
            val result = toolsRepository.getSystemResources()
            _uiState.update {
                result.fold(
                    onSuccess = { data ->
                        it.copy(
                            isSystemLoading = false,
                            systemResources = data?.takeUnless { d -> d is JsonNull }
                        )
                    },
                    onFailure = { e ->
                        it.copy(isSystemLoading = false, error = "获取资源失败: ${e.message}")
                    }
                )
            }
        }
    }

    fun loadSystemStats() {
        viewModelScope.launch {
            _uiState.update { it.copy(isSystemLoading = true, error = null, message = null) }
            val result = toolsRepository.getSystemStats()
            _uiState.update {
                result.fold(
                    onSuccess = { data ->
                        it.copy(
                            isSystemLoading = false,
                            systemStats = data?.takeUnless { d -> d is JsonNull }
                        )
                    },
                    onFailure = { e ->
                        it.copy(isSystemLoading = false, error = "获取统计失败: ${e.message}")
                    }
                )
            }
        }
    }

    fun loadPreferences() {
        viewModelScope.launch {
            _uiState.update { it.copy(isPreferencesLoading = true, error = null, message = null) }
            val result = toolsRepository.getSystemPreferences()
            _uiState.update {
                result.fold(
                    onSuccess = { prefs ->
                        it.copy(isPreferencesLoading = false, preferences = prefs)
                    },
                    onFailure = { e ->
                        it.copy(isPreferencesLoading = false, error = "获取偏好失败: ${e.message}")
                    }
                )
            }
        }
    }

    fun savePreferences() {
        viewModelScope.launch {
            _uiState.update { it.copy(isPreferencesLoading = true, error = null, message = null) }
            val prefs = _uiState.value.preferences
            val update = SystemPreferencesUpdate(
                mode = prefs.mode,
                activeCareEnabled = prefs.activeCareEnabled,
                responseLength = prefs.responseLength,
                conversationStyle = prefs.conversationStyle,
                sensitivity = prefs.sensitivity,
                debugVisible = prefs.debugVisible
            )
            val result = toolsRepository.updateSystemPreferences(update)
            _uiState.update {
                result.fold(
                    onSuccess = { updated ->
                        it.copy(isPreferencesLoading = false, preferences = updated, message = "偏好已更新")
                    },
                    onFailure = { e ->
                        it.copy(isPreferencesLoading = false, error = "更新失败: ${e.message}")
                    }
                )
            }
        }
    }

    fun refreshSensitive() {
        viewModelScope.launch {
            _uiState.update { it.copy(isSensitiveLoading = true, error = null, message = null) }
            val result = toolsRepository.getSensitiveStatus("default")
            _uiState.update {
                result.fold(
                    onSuccess = { enabled ->
                        it.copy(isSensitiveLoading = false, sensitiveEnabled = enabled)
                    },
                    onFailure = { e ->
                        it.copy(isSensitiveLoading = false, error = "获取失败: ${e.message}")
                    }
                )
            }
        }
    }

    fun toggleSensitive(enabled: Boolean) {
        viewModelScope.launch {
            _uiState.update { it.copy(isSensitiveLoading = true, error = null, message = null) }
            val result = toolsRepository.toggleSensitive("default", enabled)
            _uiState.update {
                result.fold(
                    onSuccess = { value ->
                        it.copy(isSensitiveLoading = false, sensitiveEnabled = value, message = "分级模式已更新")
                    },
                    onFailure = { e ->
                        it.copy(isSensitiveLoading = false, error = "更新失败: ${e.message}")
                    }
                )
            }
        }
    }

    fun clearMessage() {
        _uiState.update { it.copy(message = null) }
    }

    fun clearError() {
        _uiState.update { it.copy(error = null) }
    }
}
