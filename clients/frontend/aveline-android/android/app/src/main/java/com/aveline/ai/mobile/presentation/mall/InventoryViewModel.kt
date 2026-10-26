package com.aveline.ai.mobile.presentation.mall

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.domain.models.GiftInventoryItem
import com.aveline.ai.mobile.domain.models.RecipientOption
import com.aveline.ai.mobile.domain.repository.PersonaRepository
import com.aveline.ai.mobile.domain.repository.ShopRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * 库存页 UI 状态。
 *
 * 列表按后端下发的「物品 + 归属人」原样展示；页面自己只补总件数与提示行。
 */
data class InventoryUiState(
    val items: List<GiftInventoryItem> = emptyList(),
    val isLoading: Boolean = true,
    val recipientOptions: List<RecipientOption> = emptyList(),
    val message: String? = null,
    val messageIsError: Boolean = false
) {
    /** 物品种类数，用于页头「5 种 · 共 9 件」；同一物品分属不同角色只算一种。 */
    val kindCount: Int
        get() = items.distinctBy { it.itemId }.size

    /** 所有物品件数之和，用于页头「5 种 · 共 9 件」。 */
    val totalQuantity: Int
        get() = items.sumOf { it.quantity }
}

/**
 * 库存 ViewModel：只负责读库存、送出、刷新。
 *
 * 从商城页的礼物弹窗改成独立页后单独持有，避免进库存时顺带拉一遍商品菜单。
 */
@HiltViewModel
class InventoryViewModel @Inject constructor(
    private val shopRepository: ShopRepository,
    personaRepository: PersonaRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(InventoryUiState())
    val uiState: StateFlow<InventoryUiState> = _uiState.asStateFlow()

    init {
        viewModelScope.launch {
            val options = loadRecipientOptions(personaRepository)
            if (options.isNotEmpty()) {
                _uiState.update { it.copy(recipientOptions = options) }
            }
        }
        refresh()
    }

    private fun refresh() {
        viewModelScope.launch {
            // 只有首次进入显示整页 Loading；送出后刷新沿用旧列表，避免闪白
            _uiState.update { it.copy(isLoading = it.items.isEmpty()) }
            val items = shopRepository.getGiftInventory()
            _uiState.update { it.copy(items = items, isLoading = false) }
        }
    }

    /** 送出：选好收礼对象后调用，成功后刷新库存。 */
    fun useGift(itemId: String, recipient: String) {
        viewModelScope.launch {
            shopRepository.useGiftItem(itemId, recipient).fold(
                onSuccess = { message ->
                    _uiState.update { it.copy(message = message, messageIsError = false) }
                },
                onFailure = { e ->
                    _uiState.update {
                        it.copy(message = "送出失败: ${e.message}", messageIsError = true)
                    }
                }
            )
            refresh()
        }
    }

    fun clearMessage() {
        _uiState.update { it.copy(message = null) }
    }
}
