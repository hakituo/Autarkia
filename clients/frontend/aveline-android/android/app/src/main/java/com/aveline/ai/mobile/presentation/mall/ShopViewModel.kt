package com.aveline.ai.mobile.presentation.mall

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.aveline.ai.mobile.domain.models.PurchaseResult
import com.aveline.ai.mobile.domain.models.RecipientOption
import com.aveline.ai.mobile.domain.models.ShopCategory
import com.aveline.ai.mobile.domain.models.ShopItem
import com.aveline.ai.mobile.domain.models.UserBalance
import com.aveline.ai.mobile.domain.repository.PersonaRepository
import com.aveline.ai.mobile.domain.repository.ShopRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

/** 单次购买数量上限：与后端校验口径一致。 */
internal const val MAX_PURCHASE_QUANTITY = 99

/** 单个类目的分页与加载状态：左右滑动时各类目各自保留列表，互不覆盖。 */
data class ShopCategoryFeed(
    val items: List<ShopItem> = emptyList(),
    val currentPage: Int = 1,
    val hasMore: Boolean = false,
    val isLoading: Boolean = false,
    val isLoadingMore: Boolean = false
)

/**
 * 商城 UI 状态
 */
data class ShopUiState(
    val feeds: Map<ShopCategory?, ShopCategoryFeed> = emptyMap(),
    val balance: UserBalance = UserBalance(),
    val selectedCategory: ShopCategory? = null,
    val error: String? = null,
    // "给谁买 / 给谁吃"候选：后端 persona 列表动态下发，只含虚拟角色，前端不硬编码
    val recipientOptions: List<RecipientOption> = emptyList(),
    // 购买面板
    val showPurchaseConfirm: Boolean = false,
    val isPurchasing: Boolean = false,
    val itemToPurchase: ShopItem? = null,
    val purchaseQuantity: Int = 1,
    val purchaseRecipient: RecipientOption = RecipientOption("", ""),
    val purchaseResult: PurchaseResult? = null,
    val showPurchaseResult: Boolean = false
) {
    /** 尚未加载的类目按「加载中」占位，滑到该页时不会先闪一帧空态。 */
    fun feedFor(category: ShopCategory?): ShopCategoryFeed =
        feeds[category] ?: ShopCategoryFeed(isLoading = true)

    val canAffordSelectedItem: Boolean
        get() = itemToPurchase?.let { item ->
            balance.coins >= item.price * purchaseQuantity
        } ?: false

    val totalCost: Int
        get() = itemToPurchase?.let { it.price * purchaseQuantity } ?: 0

    /** 步进器上限：当前余额买得起的最大件数，最多 [MAX_PURCHASE_QUANTITY]。 */
    val maxPurchaseQuantity: Int
        get() = itemToPurchase?.let { item ->
            if (item.price <= 0) {
                MAX_PURCHASE_QUANTITY
            } else {
                (balance.coins / item.price).coerceIn(1, MAX_PURCHASE_QUANTITY)
            }
        } ?: 1
}

/**
 * 商城 ViewModel
 *
 * 功能：
 * - 7 类商品分页加载(懒加载)
 * - 类别切换
 * - 购买(支持 recipient)
 *
 * 礼物库存已独立成页，由 [InventoryViewModel] 负责。
 */
@HiltViewModel
class ShopViewModel @Inject constructor(
    private val shopRepository: ShopRepository,
    private val personaRepository: PersonaRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(ShopUiState())
    val uiState: StateFlow<ShopUiState> = _uiState.asStateFlow()

    companion object {
        private const val PAGE_SIZE = 20
        private const val CACHE_MAX_AGE_MILLIS = 10 * 60 * 1000L
    }

    // 按类目分开保存任务：滑动切换时只重启目标类目的请求，不会把别的页正在加载的列表取消掉。
    private val loadJobs = mutableMapOf<ShopCategory?, Job>()
    private val loadMoreJobs = mutableMapOf<ShopCategory?, Job>()

    init {
        loadCategory(null)
        loadRecipients()
    }

    private fun loadRecipients() {
        viewModelScope.launch {
            val options = loadRecipientOptions(personaRepository)
            if (options.isEmpty()) return@launch
            _uiState.update { state ->
                state.copy(
                    recipientOptions = options,
                    // 已选角色不在新列表里时回退第一个
                    purchaseRecipient = options.firstOrNull { it.id == state.purchaseRecipient.id }
                        ?: options.first()
                )
            }
        }
    }

    /**
     * 加载某个类目的第一页。
     *
     * 有未过期的仓库快照就先同步铺上，再决定要不要补一次网络刷新；
     * 任务按类目分开保存，左右滑动时换页不会互相取消。
     */
    private fun loadCategory(category: ShopCategory?) {
        val cached = shopRepository.getCachedShopSnapshot(category)

        if (cached != null) {
            // ViewModel 即使随 Route 重建，也先同步恢复单例 Repository 中的快照，
            // 页面不会闪回空白或整页 Loading。
            updateFeed(category) { feed ->
                feed.copy(
                    items = cached.items,
                    currentPage = cached.currentPage,
                    hasMore = cached.hasMore,
                    isLoading = false
                )
            }
            _uiState.update { it.copy(balance = cached.balance) }
            if (System.currentTimeMillis() - cached.updatedAtMillis <= CACHE_MAX_AGE_MILLIS) {
                return
            }
        }

        loadJobs[category]?.cancel()
        loadMoreJobs[category]?.cancel()
        loadJobs[category] = viewModelScope.launch {
            updateFeed(category) { feed ->
                feed.copy(
                    isLoading = true,
                    // 第一页刷新会丢弃旧分页，翻页中的转圈也要一起收掉
                    isLoadingMore = false,
                    // 有旧快照时保留在屏列表刷新，没快照的类目清空，避免串类目
                    items = if (cached != null) feed.items else emptyList(),
                    currentPage = if (cached != null) feed.currentPage else 1
                )
            }

            try {
                val (balance, pageResult) = coroutineScope {
                    val balanceRequest = async { shopRepository.getBalance() }
                    val itemsRequest = async {
                        shopRepository.getShopItems(
                            category = category,
                            page = 1,
                            pageSize = PAGE_SIZE
                        )
                    }
                    balanceRequest.await() to itemsRequest.await()
                }
                val (items, hasMore) = pageResult

                updateFeed(category) {
                    it.copy(
                        items = items,
                        isLoading = false,
                        isLoadingMore = false,
                        hasMore = hasMore,
                        currentPage = 1
                    )
                }
                _uiState.update { it.copy(balance = balance) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                updateFeed(category) { it.copy(isLoading = false) }
                if (_uiState.value.selectedCategory == category) {
                    _uiState.update { it.copy(error = "加载失败: ${e.message}") }
                }
            }
        }
    }

    /**
     * 加载更多(翻页)。类目由翻页的那一页自己传入，避免滑到一半时串到别的类目。
     */
    fun loadMore(category: ShopCategory?) {
        val feed = _uiState.value.feedFor(category)
        if (feed.isLoading || feed.isLoadingMore || !feed.hasMore) return

        updateFeed(category) { it.copy(isLoadingMore = true) }
        loadMoreJobs[category] = viewModelScope.launch {
            try {
                val nextPage = feed.currentPage + 1
                val (items, hasMore) = shopRepository.getShopItems(
                    category = category,
                    page = nextPage,
                    pageSize = PAGE_SIZE
                )

                updateFeed(category) {
                    it.copy(
                        items = it.items + items,
                        isLoadingMore = false,
                        hasMore = hasMore,
                        currentPage = nextPage
                    )
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                updateFeed(category) { it.copy(isLoadingMore = false) }
            }
        }
    }

    private fun updateFeed(
        category: ShopCategory?,
        transform: (ShopCategoryFeed) -> ShopCategoryFeed
    ) {
        _uiState.update { state ->
            val feed = transform(state.feeds[category] ?: ShopCategoryFeed())
            state.copy(feeds = state.feeds + (category to feed))
        }
    }

    /**
     * 选择类别：Tab 点击或左右滑动落位后调用。
     */
    fun selectCategory(category: ShopCategory?) {
        val state = _uiState.value
        if (state.selectedCategory != category) {
            _uiState.update { it.copy(selectedCategory = category, error = null) }
        } else if (state.feeds[category]?.isLoading == true) {
            // 首屏 init 的加载与 pager 初始落位回调会重合，已在加载就不再发一次。
            return
        }
        loadCategory(category)
    }

    /**
     * 显示购买面板
     */
    fun showPurchaseConfirm(item: ShopItem) {
        val options = _uiState.value.recipientOptions
        val current = _uiState.value.purchaseRecipient
        _uiState.update {
            it.copy(
                showPurchaseConfirm = true,
                itemToPurchase = item,
                purchaseQuantity = 1,
                purchaseRecipient =
                options.firstOrNull { option -> option.id == current.id }
                    ?: options.firstOrNull()
                    ?: RecipientOption("", "")
            )
        }
    }

    fun hidePurchaseConfirm() {
        _uiState.update {
            it.copy(
                showPurchaseConfirm = false,
                itemToPurchase = null,
                purchaseQuantity = 1
            )
        }
    }

    fun increaseQuantity() {
        _uiState.update {
            it.copy(purchaseQuantity = minOf(it.purchaseQuantity + 1, it.maxPurchaseQuantity))
        }
    }

    fun decreaseQuantity() {
        _uiState.update {
            it.copy(purchaseQuantity = maxOf(it.purchaseQuantity - 1, 1))
        }
    }

    fun selectRecipient(recipient: RecipientOption) {
        _uiState.update { it.copy(purchaseRecipient = recipient) }
    }

    /**
     * 确认购买
     */
    fun confirmPurchase() {
        val state = _uiState.value
        // 连点确认只发一次请求
        if (state.isPurchasing) return
        val item = state.itemToPurchase ?: return
        val quantity = state.purchaseQuantity
        val recipient = state.purchaseRecipient.id

        viewModelScope.launch {
            _uiState.update { it.copy(isPurchasing = true) }

            val result = shopRepository.purchaseItem(item.id, quantity, recipient)

            result.fold(
                onSuccess = { purchaseResult ->
                    _uiState.update { state ->
                        state.copy(
                            isPurchasing = false,
                            showPurchaseConfirm = false,
                            itemToPurchase = null,
                            purchaseQuantity = 1,
                            purchaseResult = purchaseResult,
                            showPurchaseResult = true,
                            balance = purchaseResult.newBalance ?: state.balance
                        )
                    }
                },
                onFailure = { e ->
                    _uiState.update {
                        it.copy(
                            isPurchasing = false,
                            showPurchaseConfirm = false,
                            itemToPurchase = null,
                            error = "购买失败: ${e.message}"
                        )
                    }
                }
            )
        }
    }

    fun hidePurchaseResult() {
        _uiState.update {
            it.copy(
                showPurchaseResult = false,
                purchaseResult = null
            )
        }
    }

    fun clearError() {
        _uiState.update { it.copy(error = null) }
    }
}
