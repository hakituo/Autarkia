package com.aveline.ai.mobile.presentation.study

import kotlinx.serialization.Serializable

/** 单张卡片的复习结果（用于会话总结的会/不会清单） */
@Serializable
data class ReviewResultItem(
    val word: String,
    /** true=会(Hard/Good/Easy)，false=不会(Again)；仅用于结算展示，不改变 FSRS 评分语义 */
    val known: Boolean,
    val translation: String
)

/** 词典搜索结果项 */
data class DictSearchResult(
    val word: String,
    val translation: String
)

/** 复习总览数据 */
data class ReviewOverview(
    val dueTodayCount: Int = 0,
    val streakDays: Int = 0,
    val learnedWords: Int = 0,
    val dueWords: Int = 0,
    val masteredWords: Int = 0,
    val newToday: Int = 0,
    val reviewToday: Int = 0
)

/** 高错词项 */
data class MistakeWord(
    val word: String,
    val errorCount: Int,
    val translation: String
)

const val DEFAULT_NEW_WORDS_BATCH_SIZE = 20
const val DEFAULT_REVIEW_BATCH_SIZE = 20

/** 背新词与复习共用同一组分档，避免两处设置口径不一致。 */
val VOCAB_BATCH_SIZE_OPTIONS = listOf(10, 20, 50)

/** 正在向后端领取的会话类型（点击入口到进入复习之间的等待态）。 */
enum class VocabLaunch { REVIEW, NEW_WORDS }

/** 词汇模块子页面层级（由 [StudyScreenV2] 提升持有）。 */
enum class VocabSubScreen {
    DASHBOARD,
    BOOK_LIST,
    BOOK_DETAIL,
    MISTAKES
}

/**
 * 词汇复习域 UI 状态。
 *
 * 从原 `StudyUiState` 中抽取，由 [StudyVocabReviewManager] 独立维护，
 * 与 `StudyUiState` 共享同一 ViewModel 作用域但状态流分离，职责更清晰。
 *
 * @property learnWords 待复习/待学习词汇列表(含完整释义)
 * @property isReviewMode 是否处于复习模式(全屏覆盖)
 * @property currentCardIndex 当前复习卡片索引
 * @property showAnswer 当前卡片是否展示答案
 * @property sessionStats 复习会话统计
 * @property sessionSummary 会话总结(复习完成后展示,null 表示无)
 * @property launching 正在启动的会话，非空时入口按钮转圈且忽略重复点击
 * @property isFinishing 结算页已展示、后台仍在同步收尾并预取下一组
 */
data class VocabUiState(
    val learnWords: List<DailyWord> = emptyList(),
    val isReviewMode: Boolean = false,
    /** 是否处于背新单词模式（复用复习界面，区分标题与提示文案） */
    val isNewWordsMode: Boolean = false,
    /**
     * 当前本地队列所属业务日期（yyyy-MM-dd），空串表示没有未走完的会话。
     *
     * 退出全屏复习不等于结束会话：此时队列里还压着 Again 重排到队尾的词。
     * 带上日期是为了让跨天的残留队列自动失效，避免「昨天没背完」把今天的
     * 列表锁死；会话正常结束时清空。
     */
    val sessionDate: String = "",
    /**
     * 当前会话 ID（前台计时上报的幂等键）。空串表示没有进行中的计时会话。
     */
    val sessionId: String = "",
    /** 已暂停时落盘的累计前台秒数（运行中的实时值由计时器单独暴露）。 */
    val sessionElapsedSeconds: Int = 0,
    val currentCardIndex: Int = 0,
    val showAnswer: Boolean = false,
    /** 本轮每个词被 Again 重排到队尾的次数（独立计数，不受 reviewResults 去重影响） */
    val redoCounts: Map<String, Int> = emptyMap(),
    val sessionStats: SessionStats? = null,
    /** 本轮复习逐词结果（会/不会），用于结算页清单 */
    val reviewResults: List<ReviewResultItem> = emptyList(),
    val sessionSummary: Any? = null,
    val launching: VocabLaunch? = null,
    val isFinishing: Boolean = false,
    /** 新词排序模式: sequential(顺序) / shuffle(乱序) */
    val wordOrder: String = "sequential",
    /** 每次背新词的分组数量 */
    val newWordsBatchSize: Int = DEFAULT_NEW_WORDS_BATCH_SIZE,
    /** 每次复习的分组数量 */
    val reviewBatchSize: Int = DEFAULT_REVIEW_BATCH_SIZE,
    /** 今日已背单词明细（新学/复习、评分、时间） */
    val todayVocab: TodayVocabSummary? = null,
    /** 当前词书学习进度 */
    val bookProgress: VocabBookProgress? = null,
    /** 可用词书文件名列表(来自后端 available_word_files) */
    val vocabBooks: List<String> = emptyList(),
    /** 当前选中的词书文件名 */
    val currentBook: String = "",
    /** 词书内单词列表(查看词书时填充) */
    val bookWords: List<BookWord> = emptyList(),
    /** 词书单词列表加载中（切书后到新书单词返回前，详情页显示骨架） */
    val bookWordsLoading: Boolean = false,
    /** 词书内单词总数 */
    val bookTotal: Int = 0,
    /** 词典搜索结果 */
    val searchResults: List<DictSearchResult> = emptyList(),
    val isSearching: Boolean = false,
    /** 复习总览 */
    val reviewOverview: ReviewOverview? = null,
    /** 高错词列表 */
    val mistakes: List<MistakeWord> = emptyList()
)

/** 词书内单个单词(用于词书浏览列表) */
data class BookWord(
    val word: String,
    val translation: String
)

/** 今日已背的单个单词 */
data class TodayVocabWord(
    val word: String,
    val translation: String,
    /** new=今天首次学；review=复习既有词 */
    val status: String,
    /** 今天这个单词的评分次数（Again 重排会 >1） */
    val reviews: Int,
    /** 今天最后一次评分：1=Again 2=Hard 3=Good 4=Easy */
    val lastQuality: Int,
    /** 最后一次评分时间 HH:mm */
    val lastReviewAt: String
)

/** 今日已背汇总 */
data class TodayVocabSummary(
    val date: String,
    val total: Int,
    val newWords: Int,
    val reviewWords: Int,
    val reviewEvents: Int,
    val againWords: Int,
    val knownWords: Int,
    val words: List<TodayVocabWord>
)

/** 当前词书学习进度 */
data class VocabBookProgress(
    val currentBook: String,
    val totalWords: Int,
    val learnedWords: Int,
    val remainingWords: Int,
    val masteredWords: Int,
    val learningWords: Int,
    val dueWords: Int,
    val progressPercent: Float,
    val todayNew: Int,
    val todayReview: Int
)
