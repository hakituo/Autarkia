# ActiveCareService（主动关怀）

> 本文同步自项目内部技术参考，仅描述公开可见的实现。
> 由 `scripts/doc_records/sync_tech_docs.py` 生成，请勿直接编辑；修改请改真源后重新生成。
> 文档入口：[技术参考目录](../README.md)

---

## 3.2 ActiveCareService

**文件**: `core/services/active_care/core/service.py`

**职责**: 主动关怀服务

**模块化架构**:

```python
class ActiveCareService:
    def __init__(self):
        self.storage = ActiveCareStorage()
        self.context = ActiveCareContext(self.storage)
        self.scheduler_logic = ActiveCareSchedulerLogic()
        self.decision = ActiveCareDecision(self.storage)
        self.executor = ActiveCareExecutor(self.context, self.storage)
        self.vocab = ActiveCareVocabulary(self.storage)
        self.mode_state = ActiveCareModeState()
        self.checker = ProactiveChecker(...)
```

**子模块架构**（2026-04-28 代码审查优化后，2026-06-19 阶段 A 八轨道拆分，2026-06-19 目录整理为子目录）:

| 模块                 | 文件                     | 职责                                     |
| ------------------ | ---------------------- | -------------------------------------- |
| state\_keys        | `shared/state_keys.py` | 状态键 StateKeys 与低打扰清理字典构建（**build_reduced_mode_clear_updates**、**build_goodnight_clear_updates**） |
| keywords           | `shared/keywords.py` | 晚安/早安/睡眠暗示/专注/题材等关键词与匹配模式 |
| mode\_reasons      | `shared/mode_reasons.py` | 低打扰原因取值域（SLEEP/FOCUS/QUIET_MODE_REASONS、SLEEP_HINT_REASON）、SkipReasons、SysPromptType |
| tuning             | `shared/tuning.py` | 通用数值阈值（间隔/生成/提醒/退避/抖动/情绪乘数） |
| sleep\_thresholds  | `shared/sleep_thresholds.py` | 睡眠与晚安相关窗口阈值（自动醒来、晚安信号间隔、作息自适应） |
| scheduling\_utils  | `shared/scheduling_utils.py` | 调度纯函数（**calculate_non_response_backoff**，Equal Jitter 退避） |
| text\_utils        | `shared/text_utils.py` | 文本归一化、时长解析/格式化、人设 token 解析 |
| prompt\_helpers    | `shared/prompt_helpers.py` | Prompt 片段构建（**build_sleep_status_description**、**build_quiet_mode_instruction**、动作指令变体） |
| daily\_record\_sync | `shared/daily_record_sync.py` | 睡眠区间回写 Daily Record（**sync_sleep_to_daily_record**，shared 下唯一带 IO 的模块） |
| constants（兼容门面）| `shared/constants.py` | 2026-09-03 起仅保留向后兼容 re-export，新代码一律引用上述原子模块 |
| prompt\_builder    | `prompt/prompt_builder.py` | Prompt V2 兼容门面；section 模型、过滤、约束、任务与装配集中在 `prompt/sections/` |
| prompt\_context\_builders | `prompt/prompt_context_builders.py` | Prompt 上下文构建（设备/生物/健康/食物/学习上下文，人设风格加载） |
| topic\_diversity   | `prompt/topic_diversity.py` | 话题多样性控制（detect_topic_category，check_topic_cooldown，build_topic_diversity_constraint） |
| persona\_resolver  | `core/services/active_care/core/persona_resolver.py` | 人设文件名解析、共享分层 Prompt 加载、决策轻量身份投影、语气参考与运行时交互模式读取 |
| postprocessor      | `postprocess/postprocessor.py` | 后处理管线；睡眠净化已拆分到 `postprocess/sleep_sanitizer.py`，去重已拆分到 `postprocess/deduplicator.py`，泄露检测已拆分到 `postprocess/leak_detector.py`，保留转发方法 |
| sleep\_sanitizer   | `postprocess/sleep_sanitizer.py` | 睡眠净化器（SleepSanitizer，晚安/睡眠状态消息过滤） |
| deduplicator       | `postprocess/deduplicator.py` | 去重器（Deduplicator，发送历史相似度检测） |
| leak\_detector     | `postprocess/leak_detector.py` | 泄露检测器（LeakDetector，提示词泄漏检测与拦截） |
| send\_validator    | `postprocess/send_validator.py` | 发送门硬 Gate（元信息/泄漏/超长/铺垫转场/状态报备前缀+提问判定）；规则常量在 `postprocess/send_validator_rules.py`，命中可压缩类交 pipeline 压缩一步 |
| event\_target\_guard | `postprocess/event_target_guard.py` | 硬事件最终发送守卫；校验数字健康目标应用并去除未确认的强退结果断言 |
| state\_persistence | `storage/state_persistence.py` | 状态持久化（事件记录、发送历史）                       |
| executor           | `core/services/active_care/core/executor.py`     | 核心编排器薄壳门面（协调上述模块）；QQ 连接解析已拆分到 `core/services/active_care/core/qq_connection_resolver.py`，LLM 生成已拆分到 `core/services/active_care/core/response_generator.py`，硬件意图已拆分到 `core/services/active_care/core/hardware_intent.py`，历史解析已拆分到 `core/services/active_care/core/history_processor.py`，LLM 输入构建已拆分到 `core/services/active_care/core/input_builder.py`，上下文组装已拆分到 `core/services/active_care/core/context_builder.py`，会话路由已拆分到 `core/services/active_care/core/conversation_router.py`，消息分发已拆分到 `core/services/active_care/core/message_dispatcher.py`，提醒处理已拆分到 `core/services/active_care/core/reminder_handler.py`，触发前置准备已拆分到 `core/services/active_care/core/trigger_preparer.py`，生成+后处理已拆分到 `core/services/active_care/core/generation_pipeline.py`，发送后收尾已拆分到 `core/services/active_care/core/post_send_handler.py`，保留 trigger_message 核心调度编排（重叠保护 → 准备 → 生成 → 纠偏 → 分发 → 收尾 → 失败回退）+ 12 兼容入口 + 8 委托方法 + get_active_care_executor 工厂函数 |
| history\_processor | `core/services/active_care/core/history_processor.py` | 历史消息纯解析（HistoryProcessor，emoji 剥离/最近历史文本/助手消息提取/时间戳解析） |
| input\_builder     | `core/services/active_care/core/input_builder.py` | LLM 输入构建（ModelInputBuilder，沉默区间策略/自问自答防护/晚安守卫/主动触发输入） |
| context\_builder   | `core/services/active_care/core/context_builder.py` | 上下文组装+Prompt（TriggerContextBuilder，历史缓存/触发上下文/睡眠状态/模式状态/Prompt 构建） |
| conversation\_router | `core/services/active_care/core/conversation_router.py` | 会话路由（ConversationRouter，目标会话解析/QQ persona conversation_id 构建） |
| message\_dispatcher | `core/services/active_care/core/message_dispatcher.py` | 消息分发+回调（MessageDispatcher，消息分发/状态保存/日记写入/非响应计数/主动消息持久化） |
| reminder\_handler  | `core/services/active_care/core/reminder_handler.py` | 提醒处理（ReminderHandler，到期提醒检查/完成/格式化） |
| decision\_executor | `decision/decision_executor.py` | 决策执行器；动作构建已拆分到 `decision/action_builder.py`，上下文采集已拆分到 `decision/context_gatherer.py`，保留转发方法 |
| action\_builder    | `decision/action_builder.py` | 动作构建器（build_available_actions，apply_action_overrides，should_force_send） |
| context\_gatherer  | `decision/context_gatherer.py` | 上下文采集器（get_workspace_snapshot，get_recent_history，get_user_signal_and_intent，build_urgent_needs） |
| decision           | `decision/decision.py` | LLM 决策 + Bandit 动作选择；输出解析已拆分到 `decision/decision_output_parser.py`，指令构建已拆分到 `decision/decision_instruction_builder.py`，保留转发方法 |
| decision\_output\_parser | `decision/decision_output_parser.py` | 决策输出解析（_parse_decision_output，JSON 修复，regex fallback，peer chat 输出解析） |
| decision\_instruction\_builder | `decision/decision_instruction_builder.py` | 决策指令构建（_build_daily_routine_probe_instruction，_build_specific_instruction） |
| proactive\_checker | `core/services/active_care/core/proactive_checker.py` | 薄壳门面 + 核心协调器（保留 perform_check/_run_decision_core）；睡眠会话状态机已拆分到 `core/services/active_care/core/sleep_session_manager.py`，初始化/状态恢复已拆分到 `checker/checker_init_state.py`，客户端门控已拆分到 `checker/checker_client_gate.py`，节流调度已拆分到 `checker/checker_throttle.py`，状态检测已拆分到 `checker/checker_state_detector.py`，事件检测已拆分到 `checker/checker_event_handler.py`，动作流程已拆分到 `checker/checker_action_flow.py`，时间检测已拆分到 `checker/checker_time_gate.py`，睡眠会话兼容垫片已拆分到 `checker/sleep_session_compat.py`（mixin 继承），本类保留转发方法向后兼容 |
| checker\_init\_state | `checker/checker_init_state.py` | 检查器初始化与状态恢复（CheckerInitState）：决策时间戳管理、per-persona 独立决策时间、从持久化存储恢复状态 |
| checker\_client\_gate | `checker/checker_client_gate.py` | 检查器客户端门控（CheckerClientGate）：活跃客户端、用户进程活动、主人设运行时交互模式、分级模式与客户端类型检测 |
| checker\_throttle | `checker/checker_throttle.py` | 检查器节流与时间调度（CheckerThrottle）：间隔抖动计算（apply_interval_jitter）、非响应退避乘数计算 |
| checker\_state\_detector | `checker/checker_state_detector.py` | 状态检测（CheckerStateDetector，从 proactive_checker.py 拆分）：`execute_decision_flow`（决策流程准备）、`build_unified_decision_ctx`（统一决策上下文）、`inject_peer_chat_info`（双角色互聊注入）、`check_daily_record_auto_wakeup`（起床自动退出睡眠）、`execute_peer_chat_check`（已废弃兼容）。构造器接收 `checker=self`，方法内通过 `checker.xxx` 访问原 self 属性 |
| checker\_event\_handler | `checker/checker_event_handler.py` | 事件检测（CheckerEventHandler，从 proactive_checker.py 拆分）：`handle_due_reminder`（到期提醒处理，含重试策略、间隔保护、起床提醒跳过）。构造器接收 `checker=self` |
| checker\_action\_flow | `checker/checker_action_flow.py` | 动作流程（CheckerActionFlow，从 proactive_checker.py 拆分）：`build_priority_and_select_action`（优先级构建+动作选择+LLM决策）、`execute_send_or_skip`（发送/跳过执行，含交互保护、硬性间隔、退避、提醒分工检查、主动关怀时段分工检查）。构造器接收 `checker=self` |
| checker\_time\_gate | `checker/checker_time_gate.py` | 时间检测（CheckerTimeGate，从 proactive_checker.py 拆分）：`apply_silence_overrides`（长沉默和无发送超时覆盖逻辑，委托 DecisionExecutor.should_force_send）。构造器接收 `checker=self` |
| sleep\_session\_compat | `checker/sleep_session_compat.py` | 睡眠会话兼容 mixin（SleepSessionCompatMixin，从 proactive_checker.py 拆分）：10 个委托给 `self._sleep_session_manager` 的兼容垫片方法。ProactiveChecker 通过继承此 mixin 保持向后兼容 |
| sleep\_session\_manager | `core/services/active_care/core/sleep_session_manager.py` | 晚安低打扰状态机；清醒信号只退出低打扰，不再把推断时刻同步为正式睡眠/起床事实。通过 weakref 持有 checker 引用以支持 `_get_config_value` 的运行时 mock |
| intent\_detector   | `detection/intent_detector.py` | 意图检测（**BERT语义先行+关键词兜底**，新增 `_detect_bert_state_event()` 通用BERT状态事件检测）                 |
| activity\_detector | `detection/activity_detector.py` | 活动检测；活动映射已拆分到 `detection/activity_maps.py`，保留转发方法 |
| activity\_maps     | `detection/activity_maps.py` | 活动映射表（is_system_process，classify_by_process_name，classify_by_window_title，extract_relevant_keyword） |
| priority\_analyzer | `decision/priority_analyzer.py` | 优先级分析；每日推送已拆分到 `decision/daily_push_priority.py`，画像关键词已合并到 `decision/portrait_keyword_map.py`，保留转发方法。**冷却时长已改为委托 `core/services/priority`**（不再本地硬编码） |
| priority\_levels | `core/services/priority/levels.py` | 跨模块共用优先级词汇：`PriorityLevel` 档位（ROUTINE<PENDING<DUE_SOON<OVERDUE<CRITICAL）、reason→档位、档位→冷却时长、计划项 high/normal/low→档位。聊天议程阶梯与主动关怀共用，避免「谁更急/多久能再催」三处各写一份 |
| priority\_throttle | `core/services/priority/throttle.py` | 共用节流判定：`ThrottlePolicy`（cooldown_seconds / once_per_day / chitchat_turns 三维度）+ `may_fire` / `remaining_cooldown_seconds` / `blocked_reason`。**判定规则共用、持久化各留各家**（agenda 用当日 json、active_care 用 state_data） |
| daily\_push\_priority | `decision/daily_push_priority.py` | 每日推送优先级（build_daily_push_priority_candidates，analyze_daily_push_priority，persist_daily_push_priority_analysis） |
| portrait\_keyword\_map | `decision/portrait_keyword_map.py` | 画像关键词映射（check_portrait_keyword_coverage，detect_user_already_covered，**统一了 decision.py 和 priority_analyzer.py 的重复映射**） |
| schedule\_adapter  | `scheduling/schedule_adapter.py` | 作息学习适配器（从每日记录学习作息规律，动态调整推断睡眠时间窗口和沉默阈值，自适应白天判定，30分钟缓存） |
| schedule\_config\_loader | `scheduling/schedule_config_loader.py` | 作息调度配置加载（load_schedule_configs，build_default_push_schedule，build_default_quiet_hours，cleanup_legacy_schedule_files） |
| gate\_scorer       | `detection/gate_scorer.py` | 软评分门控系统（7层门控从硬拦截改为评分制0.0-1.0，硬门控仍为硬拦截，软门控加权几何平均，概率决策） |
| scheduler\_logic   | `scheduling/scheduler_logic.py` | 智能心跳间隔计算（随机因子 0.85~1.15，边界 max(active,quiet)*2） |
| storage            | `storage/storage.py`    | 持久化（JSON + 延迟写入缓冲）+ **get_last_thought 异步方法**；共享低打扰状态与带来源的 Samsung Health 睡眠区间统一落在 `active_care/user_sleep_state.json`，persona 状态读取时合并该真源 |
| context            | `core/services/active_care/core/context.py`       | 上下文管理；会话解析已拆分到 `core/services/active_care/core/conversation_resolver.py`，作息配置已拆分到 `scheduling/schedule_config_loader.py`，保留转发方法 |
| conversation\_resolver | `core/services/active_care/core/conversation_resolver.py` | 会话 ID 解析与候选排序（resolve_primary_conversation_id，缓存，persona token 匹配） |
| peer\_script\_generator | `peer_chat/peer_script_generator.py` | 剧本生成；分发已拆分到 `peer_chat/peer_script_dispatch.py`，后处理钩子已拆分到 `peer_chat/peer_script_hooks.py`，保留转发方法 |
| peer\_script\_dispatch | `peer_chat/peer_script_dispatch.py` | 剧本分发（dispatch_script，逐条 WebSocket 广播） |
| peer\_script\_hooks | `peer_chat/peer_script_hooks.py` | 剧本后处理钩子（run_peer_post_hooks，日记/社交事件/巡逻触发） |

**App 通知推送与背单词定时（2026-09-14）**:

- **统一推送出口** `core/services/notification/app_push.py`：一条通知同时走三条通道——`NotificationManager` 入队（`/api/v1/tutor/notifications` 轮询兜底，App 不在线也不丢）、WebSocket `notification` 广播（在线即时弹）、FCM 离线推送（可插拔，见下）。载荷同时带 `body` 与 `content`（安卓只读 `body`，后端历史只发 `content`，曾导致通知正文为空），并带 `target`（取值 `TARGET_CHAT/VOCAB/STUDY/LIFE/SETTINGS`）供客户端深链；同步版 `push_app_notification` 用 `get_main_loop()` + `run_coroutine_threadsafe` 供 APScheduler 等后台线程调用。
- **FCM 离线通道** `core/services/notification/fcm_push.py`：HTTP v1（用项目已有的 PyJWT 签服务账号 JWT → 换 access_token → `messages:send`，不引入 firebase-admin）。配置在 `config/yaml/app.yaml` 的 `push` 段（`config/settings_infra.py::PushNotificationSettings`）；`fcm_enabled` + `fcm_project_id` + `fcm_service_account_path` 三项与安卓端已注册 token 齐全才生效，缺任一项静默降级回上面两条通道，绝不抛异常。token 由安卓 `POST /api/v1/system/mobile-push-token` 上报，存在 `user_preferences.json` 的 `mobile_push_token`。
- **每日单词推送**：`core/services/active_care/shared/vocabulary.py::check_daily_vocabulary()` 由 `core/services/active_care/core/watchdog.py::run_maintenance_loop` 调用，`daily_vocab_push_due()` 按 `study.daily_vocab_push_hours`（默认 8 点，刻意与催背时刻错开）判断是否到点；按 `daily_vocab_status.json` 日期去重，服务在到点之后才启动则当天补推一次。
- **背单词催背**：`core/tools/study/english/vocab_review_reminder.py` 按 `study.vocab_reminder_hours`（默认 12/16/20/22）多时刻检查，判据是 `get_today_review_status()["completed"]`，背完即停，内置默认推送通道（target=vocab）。

**免费模型聚合路由与失败回退（2026-09-09）**：Active Care、日记/总结、自愈、记忆蒸馏、角色日程生成与睡眠判定统一使用 `cloud:openrouter:openrouter/free`，不再绑定会限时下线的具体 `:free` 型号；免费路由抛异常或返回 `[DEBUG_ERROR]`（包括 404/429）时，`CloudRouterLLMModule` 保留原温度、输出长度和工具参数，一次性回退到 `cloud:minimax:MiniMax-M3`。决策工具调用必须 `await llm.chat(...)`，禁止把 coroutine 对象传给输出解析器。

**reasoning-only 硬隔离（2026-09-09）**：OpenRouter 免费聚合路由可能选到只返回 `reasoning_details`、正文为空的模型。`reasoning_only=true` 在 `CloudRouterLLMModule` 中等同模型失败并立即触发官方 M3 回退；Active Care 生成层同时保留第二道硬隔离，绝不把 `reasoning_text` 交给正文提取或发送门。

**提醒与普通主动关怀边界（2026-08-18）**:

- AI 自动生成的 Journal 日计划只作为 `daily_push_priority` / MDP 的决策素材，不再把每个时间块批量注册为 Workspace 硬提醒。
- 用户明确新增或修改的定时计划使用 `metadata.delivery_mode=hard`，到期后仍可独立执行。
- 历史 `source=daily_task` 且没有 `delivery_mode=hard` 的待发项会被静默完成，然后继续普通 MDP 决策，避免到期事件绕过未回复退避。
- 双角色时段协商缺失或失败时，`ProactiveAssignmentRegistry` 按日期与时段稳定选出唯一兜底主导；非主导只能在超时后接管。
- CharacterDaily 接管 Peer Chat 调度后，同时运行提醒分工与主动关怀时段分工协商。Peer Chat 剧本聚合双方与主人的真实近期聊天和上次互聊，优先使用具体有趣的素材。

**统一工具函数**（2026-04-26 DRY优化新增）:

| 工具函数 | 位置 | 用途 |
| --- | --- | --- |
| `resolve_active_care_model_path()` | `config/model_config.py` | 统一模型路径解析（优先级：hint→config→settings→LLM→provider） |
| `should_force_send()` | `decision/action_builder.py` | 统一长沉默/无发送超时覆盖判断（从 decision_executor.py 迁移） |
| `build_sleep_status_description()` | `shared/prompt_helpers.py` | 统一睡眠状态描述文本构建 |
| `build_reduced_mode_clear_updates()` | `shared/state_keys.py` | 统一构建 reduced_mode 清理状态字典（5字段重置） |
| `build_goodnight_clear_updates()` | `shared/state_keys.py` | 统一构建 goodnight+reduced_mode 清理状态字典（7字段重置） |
| `_get_scheduler_engine()` | `decision/decision.py` | CPPSchedulerEngine 模块级单例缓存 |
| `safe_timestamp()` | `core/utils/time/timestamp_utils.py` | 统一时间戳解析（毫秒→秒自动转换） |

**私密模式**（2026-04-11 新增）:

当用户切换到 sensitive 人设时，自动进入私密模式：

- Active Care 跳过所有主动消息调度（`proactive_checker._check_private_mode()`）
- 后台圈子循环自动退出（`DualRoleCoordinator._is_sensitive_persona()`）
- 切换回非 sensitive 人设后自动恢复

**隐私隔离开关**（2026-06-01 新增）:

配置项 `chat.privacy_isolation`（默认 `False`），控制 sensitive 类别记忆的隔离行为：

- `False`：sensitive 仅作为标签，记忆正常进入上下文、被搜索工具搜到
- `True`：完全隔离，sensitive 记忆不进上下文、不被搜索到

影响范围：`search_memory_tool`、`search_chat_history_tool`、`context_budget.fetch_history_for_scope`

**确认型回忆闸门**（2026-10-11 新增）：

两个检索工具返回前先经 `core/tools/recall_intent.py::is_confirmation_only_recall()` 判定本轮用户原话（runtime ctx 的 `last_user_text`）：保守三条件「回忆线索 + 确认句式 + 无索取细节疑问词」。确认型（「你还记得这个吗」）照常检索核实记忆存在，但只回传数量与「简短承认、等下文」的行为约束，不回正文（`build_confirmation_reply()`），防止角色把检索结果当台词背出；内容型（含「什么/怎么/经过」等）正常返回正文，末尾统一附 `CONTENT_USAGE_NOTE` 提示用自己的话讲。无命中时两型都照旧返回「未找到」。peer 跨角色回顾不走此闸门。

**决策算法**: 题材感知 MDP 优先，Contextual Bandit 兜底

`DecisionExecutor.select_action` 优先级链路：
1. daily priority `top_intent` 命中 → 用 `top_intent`
2. `must_probe`（画像/任务探测）→ 调用 `_select_mdp_or_bandit` 从"非 do_nothing"动作中选（2026-08-14 修复：此前硬编码 `curious_question` 会架空 MDP，导致 Q 表白学）
3. `urgent_needs` → `bio_complaint` 或 `_select_mdp_or_bandit`
4. else → `_select_mdp_or_bandit`

`_select_mdp_or_bandit`：MDP Q 表非空 → `mdp.select_action`（ε-greedy over Q 表）；冷启动/异常 → 回退 `select_action_bandit`。

题材感知 MDP（`decision/mdp.py`）：
- 状态 `S=(tod_slot, last_topic_sub, last_reply)`，动作 `A=intent`，奖励 `R=(+1 回复 / -1 忽略)`
- 增量 Q-learning 更新（带衰减学习率），Q 表存 `active_care_mdp.json`
- `update` 在用户响应/消息分发后触发（reward 学习），`select_action` 在决策时查表（动作选择）

```python
class ActiveCareDecision:
    async def select_action_bandit(self, ctx: Dict, actions: List[str]) -> str:
        """Contextual Bandit 兜底动作选择（MDP 冷启动/异常时使用）"""
        # 1. 长时间沉默打破器（移除 do_nothing）
        # 2. ε-greedy 探索/利用
        # 3. JITAI 启发式覆盖（urgent_needs/CPU 过热）

    async def update_policy_reward(self, action: str, reward: float):
        """更新动作奖励值"""
```

**动作类型**:

| 动作       | 触发条件      | 说明   |
| -------- | --------- | ---- |
| greeting | 静默时间 > 阈值 | 问候   |
| reminder | 有未完成提醒    | 提醒   |
| weather  | 天气变化      | 天气提醒 |
| health   | 能量低/饥饿    | 健康关怀 |
| emotion  | 情绪低落      | 情绪关怀 |
| study    | 学习时间      | 学习提醒 |
| random   | 随机触发      | 随机闲聊 |
