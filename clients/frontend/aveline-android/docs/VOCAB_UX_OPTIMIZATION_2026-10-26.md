# 背单词模块体验优化任务书（2026-10-26）

> 给执行方（其他 LLM）看的任务文档。只描述问题、原因、改法和验收标准，不含代码实现。
> 改动前先读 `.trae/rules/RULES.md`、`.trae/skills/autarkia-clients/SKILL.md`；行数上限见 `tests/scripts/docs/check_file_sizes.py`。
> 本地不跑 gradle，编译与测试走 `.github/workflows/android-ci.yml`。
> 路径前缀统一省略为 `study/` = `clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile/presentation/study/`。

基线：commit `e4027047`（词汇模块按设计稿改版）之后的状态。视觉样式这轮不动，只改**转场、状态衔接、删冗余**。

---

## 0. 任务总览与执行顺序

| 编号 | 任务 | 优先级 | 主要文件 |
| --- | --- | --- | --- |
| T1 | 修复「整页切换」双层动画与空白页闪现 | P0 | `StudyScreenV2.kt`、`StudyVocabBookHost.kt` |
| T2 | 开始复习/背新词：点击即反馈，不再「点了没反应→突然滑进来」 | P0 | `StudyVocabReviewManager.kt`、`VocabHomeSections.kt`、`VocabBookScreens.kt` |
| T3 | 进入/退出背词会话改为「会话级」转场（纵向），与子页面「推入」区分 | P0 | `StudyVocabBookHost.kt` |
| T4 | 最后一张卡 → 结算页：立即切换，不等三次网络请求；防重复评分 | P0 | `StudyVocabReviewManager.kt`、`VocabReviewScreen.kt` |
| T5 | 切换词书：去掉旧书内容闪现与「暂无单词数据」闪现 | P0 | `StudyViewModel.kt`、`VocabBookScreens.kt`、`StudyVocabBookHost.kt` |
| T6 | 卡片内微动效：翻答案、下一张、进度条 | P1 | `VocabReviewScreen.kt` |
| T7 | 词汇模块错误/提示没有任何展示 | P1 | `StudyScreenV2.kt` |
| T8 | 删除死代码与空目录 | P1 | 见第 3 节 |
| T9 | 删除/收起低价值功能（需按第 4 节结论执行） | P1 | 见第 4 节 |
| T10 | 动效参数统一成 token | P2 | 新增 `theme/Motion.kt` |
| T11 | 预测性返回（Android 14 Predictive Back） | P2 | `StudyVocabBookHost.kt` |

建议拆成 3 个提交：**T1+T3+T10**（转场骨架）→ **T2+T4+T5+T7**（状态衔接）→ **T6+T8+T9**（微动效与删减）。每个提交都应能独立编译。

---

## 1. 现状：为什么过渡动画差（根因）

当前结构是**两层动画叠在一起**：

```
StudyScreenV2
 └─ AnimatedVisibility(showVocabHost)          ← 外层：整体右滑入/右滑出 + 淡入淡出 300ms
     └─ StudyVocabBookHost
         └─ AnimatedContent(currentScreen)     ← 内层：按 enum 序号左右滑 + 淡 300ms
             NONE / BOOK_LIST / BOOK_DETAIL / MISTAKES / REVIEW / SUMMARY
```

### 问题 1：退出时内外两层同时动，中间露出空白页（最明显）

- `StudyScreenV2.kt:363-371`：`showVocabHost` 由 `isReviewMode || sessionSummary != null || vocabSubScreen != DASHBOARD` 计算。
- 一旦返回词汇主页，`currentScreen` 立刻变成 `VocabScreen.NONE`（`StudyVocabBookHost.kt:55-62`），而 `NONE` 分支**什么都不渲染**（`:153`）。
- 于是外层在右滑淡出的同时，内层也在执行「旧页面 → 空白」的滑出 + 淡出。用户看到的是：页面内容先往右溜走、剩下一块纯 `Background` 色的空板子再往右滑走，并且淡出被叠了两次，前半段就已经几乎透明。

### 问题 2：从词书详情 / 结算页进入背词，会「先退出再进入」来回弹一次

- `StudyVocabBookHost.kt:140-143`：词书详情点「开始背新词」时，**先**把子页面设回 `DASHBOARD`，**再**调用 `onStartNewWords()`。
- `onStartNewWords()` 是异步网络请求（`StudyVocabReviewManager.kt:347-399`），请求回来才把 `isReviewMode` 置 true。
- 中间这段时间 `showVocabHost == false` → 整个宿主右滑退出回到主页 → 网络回来 → 再右滑进入复习页。
- 结算页「继续下一组」（`StudyVocabBookHost.kt:112-118`）同理：先清空 `sessionSummary`，再异步开新组，也会弹一次。

### 问题 3：点「开始复习」没有任何反馈

- `startReview()` / `startNewWordsSession()` 只更新 `StudyUiState.isLoading`，但词汇页**没有任何地方读取它**（全模块 grep `isLoading` 只有笔记/计划在用）。
- 网络 300ms~2s 期间按钮无变化；可以连点，连点会并发发起多个 `startReviewSession()`。
- 网络回来后页面才突然从右侧滑入，体感是「卡了一下然后猛地跳进去」。

### 问题 4：所有页面用同一种横滑，层级感错误

- 进入「背词会话」与进入「词书列表」都是从右边推入，方向由 enum 的 `ordinal` 决定（`StudyVocabBookHost.kt:85`）。
- 背词是一个**沉浸式会话**（有关闭 ×、有计时），语义上应是从底部升起的模态层；词书列表/详情/错题本才是普通的「推入」子页面。
- 用 ordinal 判断方向还会出错：`MISTAKES(3) → REVIEW(4)` 被当作前进，`SUMMARY(5) → BOOK_LIST(1)` 被当作后退，与实际层级无关。

### 问题 5：最后一张卡评分后页面「冻住」

- `submitReview()`（`StudyVocabReviewManager.kt:411-499`）在最后一张时不推进本地状态，直接调 `finishSession()`。
- `finishSession()` 串行做三件事：等待上一次评分同步 → `endReviewSession()` → `getDailyReviewBatch()` 预取下一组（`:504-525`），全部完成才切到结算页。
- 这期间用户停在最后一张的答案面，评分按钮仍可点，**再点一次会对同一个词重复提交评分**。

### 问题 6：切换词书时内容闪烁

- `StudyVocabBookHost.kt:129-132`：选书时异步 `onSwitchBook()`，**同时**立刻打开详情页。
- 详情页 `LaunchedEffect(Unit) { onLoadBookWords() }`（`VocabBookScreens.kt:192`）这时拉的还是**旧书**的单词，标题也还是旧书名（`currentBook` 尚未更新）。
- 切书成功后 `switchVocabBook()`（`StudyViewModel.kt:323-334`）把 `bookWords` 清空 → 页面闪一下「该词书暂无单词数据」→ 再次 `loadBookWords()` → 新书单词出现。单词列表一共会变 3 次。
- 切书后不刷新 `bookProgress` / `reviewOverview` / 今日待背数，回到主页数字还是旧书的。

### 问题 7：卡片切换完全没有动画

- `VocabReviewScreen.kt:71-109`：问题面 / 答案面是 `if/else` 硬切；下一张卡也是直接替换。进度条有 `animateFloatAsState`，但卡片本身没有任何过渡。

---

## 2. 改法（逐项）

### T1 修复双层动画（P0）

**目标**：词汇模块的全屏层只保留**一层**负责「进/出」，内部页面之间的切换由另一层负责，且两者不会同时对同一块内容做动画。

做法（二选一，推荐 A）：

- **A（推荐，改动小）**：保留外层 `AnimatedVisibility` 负责整体进出；内层 `AnimatedContent` 的 `targetState` **不再出现 `NONE`**。
  - 在宿主内记住「最后一个非 NONE 页面」：当计算结果是 `NONE` 时，继续渲染上一个页面，让外层把它完整地带出去。
  - 删除 `VocabScreen.NONE` 枚举值和 `NONE -> {}` 分支。
  - 外层与内层只能有一处设置 `background(Background)`，另一处去掉（现在两处都有：`StudyScreenV2.kt:368` 与 `StudyVocabBookHost.kt:94`）。
- **B**：把词汇主页（DASHBOARD）也纳入同一个 `AnimatedContent`，外层 `AnimatedVisibility` 删掉。缺点是主页在 HorizontalPager 里，要挪层级，改动大。

**验收**：
- 从词书列表 / 错题本 / 复习 / 结算任意页返回词汇主页，全程看不到空白底板；内容和底板一起移动。
- 动画期间只有一层在做淡出（录屏逐帧看，不应出现前 1/3 时间就几乎全透明）。

### T2 开始复习 / 背新词即时反馈（P0）

1. `VocabUiState` 增加一个「正在启动」字段，例如 `launching: VocabLaunch?`（`REVIEW` / `NEW_WORDS` / `null`），由 `StudyVocabReviewManager` 在请求开始时置位、结束（成功或失败）时清空。不要再借用 `StudyUiState.isLoading`。
2. `EntryButtons`（`VocabHomeSections.kt:49`）与词书详情底部按钮（`VocabBookScreens.kt:257-264`）、结算页「继续下一组」按钮：`launching != null` 时对应按钮 `loading = true`，其他入口 `enabled = false`。`AvelineButton` 已经支持 `loading` 参数，不需要新组件。
3. `startReview()` / `startNewWordsSession()` 开头加防重入：`launching != null` 直接 return。
4. **改调用顺序**：词书详情「开始背新词」与结算页「继续下一组」**不再先**把子页面设回 DASHBOARD / 清空 summary。改为：请求成功后，在**同一次** state 更新里同时设置 `isReviewMode = true`、清空 `sessionSummary`；宿主随后把子页面重置为 DASHBOARD（可在 `isReviewMode` 变为 true 时由宿主统一处理）。这样 `showVocabHost` 全程为 true，不会弹出再弹入。
5. 失败时保持在原页面，按钮恢复，并通过 T7 的提示条显示原因（例如「当前词书没有新词了」）。

**验收**：
- 点击后 ≤100ms 内按钮出现 loading；连点不会发出第二个请求。
- 从词书详情、结算页进入背词，宿主不会出现「退出→再进入」的往返。
- 网络失败或无新词时有可见提示，页面不跳。

### T3 区分「会话」与「子页面」两种转场（P0）

在宿主的 `transitionSpec` 里按**页面类型**而不是 ordinal 决定动画。页面分两类：

- 子页面（push）：`BOOK_LIST`、`BOOK_DETAIL`、`MISTAKES`
- 会话（modal）：`REVIEW`、`SUMMARY`

| 从 → 到 | 动画 | 时长 / 曲线 |
| --- | --- | --- |
| 主页 → 子页面，子页面 → 更深子页面 | 新页从右侧 100% 推入；旧页向左位移 30% 并压暗（不要整屏滑走） | 300ms，EmphasizedDecelerate |
| 子页面返回 | 上面的反向 | 250ms，EmphasizedAccelerate |
| 主页/词书详情 → 复习 | 复习页从下方 8% 位移 + 淡入 + 0.96→1 缩放；底下的页面原地淡出到 0.6 再消失 | 320ms，EmphasizedDecelerate |
| 复习 × 关闭 → 主页 | 复习页向下 8% + 淡出 | 220ms，EmphasizedAccelerate |
| 复习 → 结算 | 淡出穿过（fade through）：旧页 90ms 淡出，新页 210ms 淡入 + 0.98→1 缩放 | 共 300ms |
| 结算 → 复习（继续下一组） | 同样用 fade through，不要横滑 | 300ms |
| 结算 → 主页 | 同「复习关闭」 | 220ms |

- 外层 `AnimatedVisibility` 的 enter/exit 也要跟着分类：如果第一屏是会话类，用纵向；是子页面类，用横向。可把「进入时的页面类型」作为参数传给外层，或采用 T1 的方案 B 统一一层处理。
- 动画期间禁止重复点击（`AnimatedContent` 过渡中的旧页面不接收点击；在旧页面上加 `Modifier.pointerInput` 吞掉事件，或用 `transition.isRunning` 禁用按钮）。

**验收**：
- 进复习是「从下面升起」，进词书是「从右边推入」，两种手感一眼能分辨。
- 结算 ↔ 复习之间不再出现左右横滑。

### T4 最后一张卡 → 结算立即切换（P0）

1. 结算页只依赖 `reviewResults`（本地已有）和 `hasMore`（需要下一组）。所以最后一张评分后**立即**进入结算：同一次 state 更新里 `isReviewMode = false`、`sessionSummary = 占位值`（或新增 `isFinishing = true`）。
2. `finishSession()` 后台继续做「等评分同步 → 结束会话 → 预取下一组」。预取完成前，「继续下一组」按钮显示 loading；预取结果为空时降级为「返回词汇页」。
3. `submitReview()` 开头加保护：当前已在结算中（`isFinishing` 或 `sessionSummary != null`）直接 return，杜绝重复评分。
4. `endReviewSession()` 失败时：结算页照常显示本地结果，顶部提示「同步失败，稍后自动重试」，不要把用户踢回主页。

**验收**：最后一张点评分到结算页出现 ≤350ms（只受动画时长影响，与网络无关）；快速双击评分按钮只产生一次提交。

### T5 切换词书不闪（P0）

1. `switchVocabBook(filename)`：**乐观更新**——请求发出前就把 `currentBook = filename`、`bookWords = emptyList()`、`bookWordsLoading = true`（新增字段）写进 state。请求失败再回滚到原书并提示。
2. 详情页去掉 `LaunchedEffect(Unit) { onLoadBookWords() }` 的无条件加载；改为：`bookWords` 为空且不在加载中、且 `currentBook` 已是目标书时才加载。保证一次选书只拉一次单词列表。
3. 详情页三态：`bookWordsLoading` → 显示 8~10 行骨架行（与真实行同高，避免列表跳动）；加载完成且为空 → 才显示「该词书暂无单词数据」；有数据 → 列表淡入（150ms）。
4. 切书成功后刷新：`loadVocabInsights()`（词书进度）、`loadReviewOverview()`、`loadLearnWords()`。若本地有未背完的**新词**队列且属于旧书，清掉它（复习队列与词书无关，可保留）。
5. 列表里点的是当前这本书时，只打开详情不重新请求（现已如此，保持）。

**验收**：选一本新书 → 详情页标题立即是新书名 → 骨架 → 新书单词，全程不出现旧书单词，也不出现「暂无单词数据」。返回主页后进度条和「今天 N 个词」已是新书数据。

### T6 卡片内微动效（P1）

- 问题面 → 答案面：答案区 `fadeIn + 向上 12dp`，150ms；评分栏与答案区同步淡入。不要做 3D 翻转（与当前克制的视觉风格不符）。
- 下一张卡：以 `currentCardIndex` 为 key 做 `AnimatedContent`，旧卡向左 24dp + 淡出，新卡从右 24dp + 淡入，180ms。`不认识`（重排到队尾）可改为旧卡向下 16dp 淡出，暗示「放回去了」。
- 进度条已有动画，保持；顶部「x / y」数字可用 `AnimatedContent` 做竖向滚动数字（可选）。
- 评分按钮按下时给轻触感反馈（`HapticFeedbackType.TextHandleMove` 或 `LongPress` 中较轻的），可选。

**验收**：连续快速评分 20 张不掉帧、不会因动画未结束而吞掉点击（动画期间的点击应作用于新卡）。

### T7 词汇模块提示不可见（P1）

- 现状：`StudyScreenV2.kt:236-255` 只展示 `successMessage`，而且是在顶层页头下方；进入「更多 → 词汇」或全屏宿主后，这块被盖住或不显示。`uiState.error`（如「当前词书没有新词了」「切换词书失败」「提交复习失败」）**在学习页任何地方都不展示**。
- 改法：在 `StudyScreenV2` 根 `Box` 最上层放一个 `SnackbarHost`（或复用项目已有的提示组件），同时消费 `successMessage` 和 `error`，展示后调用 `onClearError()`。全屏宿主打开时也必须可见。

**验收**：断网点「开始复习」能看到失败原因；词书无新词时能看到提示。

### T10 动效 token（P2）

- 新增 `theme/Motion.kt`：`MotionDuration.Short = 150 / Medium = 250 / Long = 300 / Session = 320`，`MotionEasing.EmphasizedDecelerate = CubicBezierEasing(0.05f, 0.7f, 0.1f, 1f)`、`EmphasizedAccelerate = CubicBezierEasing(0.3f, 0f, 0.8f, 0.15f)`、`Standard = CubicBezierEasing(0.2f, 0f, 0f, 1f)`。
- 词汇模块所有 `tween(300)` 改为引用 token。`navigation/graph/NavTransitions.kt` 的 `ANIM_DURATION` 可以之后再迁移，这次不强制。
- 尊重系统「移除动画」：读取 `Settings.Global.ANIMATOR_DURATION_SCALE`，为 0 时所有转场退化为 0ms 淡入淡出。

### T11 预测性返回（P2，可选）

- 子页面支持 `PredictiveBackHandler`：手势拖动时页面跟手右移并缩放到 0.9，松手完成返回，取消则回弹。复习会话的手势返回等同于点 ×。
- 需确认 `AndroidManifest.xml` 已开启 `android:enableOnBackInvokedCallback="true"`，没开就先不做。

---

## 3. 死代码与空目录（T8，直接删）

删除前每一项都再 grep 一次确认无引用（`main` 与 `test` 两个源集都要搜）。

| 项 | 位置 | 说明 |
| --- | --- | --- |
| `VocabUiState.dailyWords` | `study/VocabUiState.kt:75` | 全项目无读取 |
| `VocabUiState.dictStats` | `study/VocabUiState.kt` | 全项目无读取 |
| `StudyWord` 数据类 | `study/StudyVocabularyModels.kt:55` | 只被 `dailyWords` 引用，随之删除 |
| `StudyVocabReviewManager.loadNewWords()` | `study/StudyVocabReviewManager.kt:197` | 无调用方（背新词走 `startNewWordsSession`） |
| `StudyVocabTab.kt` 整个文件 | `study/StudyVocabTab.kt` | 纯参数转发的薄壳；`StudyMoreTab` 直接调用 `VocabHomeScreen` |
| `VocabScreen.NONE` | `study/StudyVocabBookHost.kt` | T1 完成后删除 |
| `NEW_WORDS_BATCH_SIZE_OPTIONS` / `REVIEW_BATCH_SIZE_OPTIONS` 别名 | `study/VocabUiState.kt` | 两者都等于 `VOCAB_BATCH_SIZE_OPTIONS`，统一用一个 |
| `StudyFocusViewModel.startBackendSync()` / `clearBackendSession()` | `study/StudyFocusViewModel.kt:371-375` | 无调用方 |
| `StudyPlanFocusLink.consumeSelected()` / `resolveUnique()` | `study/StudyPlanFocusLink.kt:58,71` | 无调用方（实际用的是 `*Target` 版本） |
| 空目录 `presentation/food/`、`presentation/shop/`、`presentation/utils/` | — | 目录内没有任何文件 |
| `StudyTabV2` 里的 5 个「Legacy loading targets」 | `study/StudyScreenV2.kt:59-64` | 不是可见 Tab，只被当作「加载触发器」。改为显式回调 `onLoadVocab()` / `onLoadPlan()` 等，然后删掉这 5 个枚举值（中等改动，可单独提交） |

---

## 4. 低价值功能（T9）

词汇主页（`VocabHomeScreen.kt`）现在从上到下依次是：今日总量 → 两个入口 → 词书 → 三项统计 → 记忆曲线 → 三行设置 → 词典搜索 → 错题本 → 手动记录。一屏放不下，核心入口之外的东西太多。

| 功能 | 结论 | 理由 / 做法 |
| --- | --- | --- |
| **手动记录背词数**（`ManualRecordRow`、`VocabManualRecordDialog.kt`、`manualStudyToday`、`addManualStudy` 全链路） | **删除** | 现在已有前台自动计时 + 每词 FSRS 评分记录，手填数字和自动数据口径冲突，还会污染「今日已背」。连同 `StudyViewModel.addManualStudy/loadManualStudyToday`、`StudyRepository.addManualStudy`、`AvelineApiService.addManualStudy` 一起删；后端接口是否保留由后端另行决定，不在本任务内 |
| **记忆保持预测曲线**（`MemoryCurveSection`） | **删除** | 没有坐标轴和说明，只有两端两个百分比，看了也不知道该做什么。`ReviewOverview.memoryCurve` 字段随之删除 |
| **三行设置**（出词顺序、新词每组、复习每组） | **收起** | 不常改。挪到词汇页标题栏右侧齿轮按钮打开的底部弹窗（`ModalBottomSheet`），主页不再展示 |
| **主页词典搜索** | **建议删除（需用户确认）** | 和「背单词」主流程无关，且搜索结果直接把主页撑长。如用户要保留，改为标题栏的搜索图标打开独立搜索页 |
| **三项统计**（连续天数 / 已掌握 / 今日已背） | 保留 | 有激励作用，体量小 |
| **错题本** | 保留 | 有用，入口保持一行 |
| **「更多 → 学习记录」**里的手动开始/结束学习会话（`StudyOverviewTab`） | **需用户确认** | 与「专注」Tab 的番茄钟功能重叠。若确认不用，删除 `StudyMoreSection.RECORDS` 入口及 `StudyOverviewTab.kt` 中的录入部分 |

删减后的主页结构：**今天 N 个词 → [开始复习] [背新词] → 当前词书 + 进度 → 三项统计 → 错题本一行**。

### 入口层级（建议，需用户确认）

现在要背单词得走 **学习 → 更多 → 词汇**，再点「开始复习」，共 4 步。「今天」Tab 里没有任何词汇入口。建议二选一：

- 在「今天」Tab 加一张词汇卡片：「今天 N 个词 · [开始]」，点开始直接进入复习会话（复用 T3 的会话转场）。
- 或把「词汇」提升为学习页的一级 Tab，替换使用频率较低的一项。

---

## 5. 统一验收清单

录屏（60fps）逐项检查，交付时附录屏或 GIF：

1. 主页 → 换词书 → 选另一本 → 详情 → 开始背新词 → 背完一组 → 结算 → 继续下一组 → × 关闭。全程无空白底板、无往返弹跳、无旧数据闪现。
2. 主页 → 开始复习：100ms 内按钮 loading；连点无重复请求。
3. 最后一张卡评分 → 结算 ≤350ms；快速双击只提交一次。
4. 断网操作各入口都有可见错误提示。
5. 系统「移除动画」打开后，所有页面切换为即时切换，功能正常。
6. 系统返回键在每一层都只退一层（现有行为，回归检查）。
7. `tests/scripts/docs/check_file_sizes.py` 通过；Android CI 编译通过；`app/src/test/.../study/` 下现有单测通过。
8. 第 3 节每个删除项删完后全项目 grep 无残留引用。
