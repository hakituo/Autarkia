# 学习工具（背单词 / 专注番茄钟）

> 本文同步自项目内部技术参考，仅描述公开可见的实现。
> 由 `scripts/doc_records/sync_tech_docs.py` 生成，请勿直接编辑；修改请改真源后重新生成。
> 文档入口：[技术参考目录](../README.md)

---

## 3.12 学习工具 - 背单词模块（Study Tools - Vocabulary）

**文件**: `core/tools/study/english/` | Facade: `vocabulary_manager.py` | 详细文档: `core/tools/study/english/README.md`

**定位**: 面向单一用户的背单词系统，对外统一走 `get_vocabulary_manager()` 单例门面。后端服务层 `core/services/study/service.py` 透传，安卓端 `StudyVocabReviewManager` 驱动复习会话。

**模块结构（2026-08 解耦自原 VocabularyManager God Class）**:
- `loader.py` — `VocabDataStore`：路径解析、词典/例句/进度懒加载与落盘、查询、导入/切换
- `fsrs_scheduler.py` — FSRS(`Scheduler`/`Card`)间隔调度 + SM-2 回退 + 当前/历史双套 quality→Rating 映射 + daily/unfamiliar 同步
- `quiz.py` — `get_daily_words`（当日固定历史补漏批次 + FSRS 到期词）、测验生成与判分
- `stats.py` — 统计、错词/弱词、App 错题与 unfamiliar 计数合并、记忆曲线、`get_review_overview`、streak
- `daily_word_log.py` — 每日生词日志 `daily/YYYY/MM/DD.txt`（单例；薄壳门面 + mixin，按职责拆到 `daily_word_log_source/review/queue/words/marks.py`）
- `vocab_review_reminder.py` — 复习定时提醒（APScheduler，通道留接口）

**词书来源（2026-08 从考纲压缩版换为 ECDICT；2026-08-25 恢复可复现生成与释义分层）**:
- 由 `scripts/study/vocabulary/build_wordbooks.py` 基于 **ECDICT**（`external/ECDICT-master/ecdict.csv`）重建，筛选 8 个考纲标签（zk/gk/cet4/cet6/ky/toefl/ielts/gre）并保留进度、daily、unfamiliar 手动补词；默认只生成报告，`--write` 才原子替换并备份现有词书。
- `CET-全量.json`：全量释义总表约 1.5 万词，每条带 `tags` 标注所属级别；仅作复习释义兜底查询，不显示在词书选择列表。
- 分级词书：`CET4-顺序.json`（四级基础，默认词书）/ `CET6-顺序.json` / `考研-顺序.json` / `托福-顺序.json` / `雅思-顺序.json` / `GRE-顺序.json`，词书选择页按级别切换，背新词按当前词书取词。
- 构建器保留 `vt/vi`，清除字面量换行残片，把 `[经][机][医][化]` 等领域义写入 `extended_translations`；Sentence 文件仅提供例句、短语与音标，附带释义不会进入 Words。
- `config/study/vocabulary_sense_overrides.json` 维护少量人工核对的 `primary_translations`。Android 仅对 `primary=true` 加粗，并将专业义及来源补充义默认折叠；未核对词不自动加粗第一条。
- 进度文件：`output/user_data/vocab_progress.json`（FSRS 状态以 `fsrs_` 前缀存储，due/last_review 为 UTC 时间戳）。

**复习调度要点（2026-08 修复）**:
- `get_daily_words(limit=0)` 返回当天首次生成的全部待复习词，不做人为数量截断。系统把历史候选持久化到 `_review_batch_state.json`，再将与 FSRS 合并后的最终全集锁定到 `_review_queue_state.json`；后续刷新只扣除完成项，不会在同日动态补入新候选。
- 例外：用户手动编辑历史 daily 文件时，批次状态中记录的文件内容签名会失配（系统自身 mark/remove 写入通过 `self_written_signatures` 区分），此时只把新出现的待复习词增量补进当天队列，已完成项与既有顺序不变。
- daily 记录在从未进入 progress、记录日期晚于最后复习，或同日最后评分为 Again（旧语义 `1/2`，新语义 `1`）时参与待复习。排序优先级为近期仍不会词、FSRS 普通到期词、历史漏推词；已有 FSRS 进度不会重置，`#` 标题/注释不参与解析。
- App 实际评分为 `1=Again, 2=Hard, 3=Good, 4=Easy`。FSRS 使用按日调度，关闭分钟级 learning/relearning steps 与 interval fuzzing：Again/Hard 由 daily 次日优先机制承接，Good/Easy 进入长期天级间隔，重建结果可重复。
- **历史评分有两套语义**：`LEGACY_RATING_CUTOFF = 2026-09-01T15:47:29+08:00` 之前后端按旧 0-5 量表解释（1/2→Again、3→Hard、4→Good、5→Easy），之后为现行 1/2/3/4。`rebuild_fsrs_card_from_history()` 按事件发生时间选择 schema（`historical_quality_to_rating`），`quality_to_rating()` 只描述当前 API。评分语义修正用 `scripts/maintenance/migrate_vocab_fsrs_history.py`（默认 dry-run，`--apply` 自动备份并写 `rating_migration_version`，`--rollback` 回滚），只重算状态、不改写 history。
- AI `word_quiz` 默认读取今天前最近的非空 daily 日志；可显式读取 `unfamiliar`，或用 `source=both` 获取严格分区的两套结果。结果携带 `source/scope/dates_with_words`，防止模型把空 daily 结果复述成上一轮 unfamiliar 结果。
- AI 的 unfamiliar 抽词池即时合并既有 App 历史错题与长期文件计数，无需迁移或改写原文件；Android 提交评分后，Again（以及仍很脆弱的新词判 Hard）同步增加 unfamiliar 难词计数，其余递减（最低 0）。`GET /api/v1/vocab/mistakes` 同样返回合并视图，`error_count=max(progress_error_count, unfamiliar_count)` 避免同一错误重复计数。
- 自动判分只产生 Good/Again：quiz 答对记 `quality=3`（Good），答错记 `1`（Again）；Easy 保留给用户明确表示毫不费力的场景。history 事件可选 `source`（`manual_review`/`quiz`/`daily_retry`/`same_session_retry`/`ai_unfamiliar_check`），无 source 的旧记录按 `manual_review` 兼容。
- 安卓复习：Again 本轮最多重排 2 次（含首次共出现 3 次）；结算页按单词去重统计会/不会。
- Android 使用 `study_vocab_session` 私有 SharedPreferences 保存未完成会话的动态队列、卡片索引、Again 次数和本轮结果。快照版本已升级为 v3，使修复前生成的错误队列失效；已提交评分仍保留在后端 FSRS。冷启动先恢复有效快照，再决定是否拉取远端列表；完整结算后清理快照。

**安卓复习 UI 关键文件**:
- `StudyVocabReviewManager.kt` — 评分提交、Again 重排、结果去重（`dedupeResults`）
- `StudyVocabSessionStore.kt` — 未完成复习/背新词会话的本地快照与版本校验
- `StudyVocabReview.kt` — 翻卡会话 + 结算页（`VocabSessionSummary` 展示会/不会明细 + 例句区）

***

## 3.13 学习服务 - 专注番茄钟模块（Study - Focus Pomodoro）

**文件**: `core/services/study/focus_session_service.py` | 模型: `focus_session_models.py` | 策略: `focus_monitor_policy.py` | 配置: `config/focus_monitor_config.py` | 路由: `routers/v1/study_focus.py` | AI 工具: `core/tools/focus_session_tool.py` | 模块指南: `.trae/skills/autarkia-study-focus/SKILL.md`

**定位**: 后端权威的专注会话 + 摄像头状态监控（人在/离开/疑似分心）+ 温柔探班 + 严格模式低频视觉复核 + 跨端（Web/Android）同步 + AI 只读聚合查询。

**核心机制**:
- **后端权威计时**: `FocusSessionService` 维护会话状态机（idle→active→paused→finished），接收端侧 MediaPipe FaceDetector 产出的结构化观察（presence/activity/confidence/signals），按 `sequence` 幂等处理（乱序/重复忽略），心跳超时自动暂停，结束总结并同步 `DailyTracker`。
- **监控策略**: `focus_monitor_policy.py` 根据 `config/focus_monitor_config.py` 阈值决定温柔探班时机；严格模式下在持续分心、已授权摄像头、冷却结束、专注时长足够时，建议低频视觉复核。
- **落盘**: `companion_data/user_data/focus_sessions/YYYY/MM/DD.txt`（filelock + 原子写）。

**隐私红线（强制）**:
- 后端存储与返回均不含 base64 / 图像 / 音频 / 视频；观察 payload 含图像字段会被 `_validate_observation` 丢弃。
- 视觉复核帧（`POST /vision-review`）仅在单次请求内临时送视觉模型，只把结论文本写入 `vision_review_events`，不落盘任何图像。

**跨端**:
- Web 端侧 MediaPipe 检测，Android 经 `AvelineApiService` / `StudyRepository` / `StudyFocusViewModel` 复用同一后端会话，实现跨端共享一个专注会话。

**AI 只读工具**:
- `get_current_focus_session` / `get_focus_session_summary`：返回聚合专注数据（focus_rate/remaining_seconds/nudge_count 等），裁剪所有图像字段，无法开启监控或读取画面。
