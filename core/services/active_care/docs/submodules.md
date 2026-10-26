# 子目录拆分说明

> Active Care 子文档 · 上级入口：[README.md](../README.md)
> 只写当前实现；变更史进 `docs/updates/`。

---

### 9. 子目录拆分说明

原 55 个平铺文件已整理为 10 个子目录 + `state/`（已存在），每个源文件保留转发方法保持向后兼容。

#### 9.1 core/ — 核心编排与服务入口（18个文件）

| 文件 | 职责 |
|------|------|
| `service.py` | 服务主类 |
| `proactive_checker.py` | 主动关怀检查器（初始化/门控/节流已拆分到 `checker/`，保留转发方法） |
| `proactive_loop.py` | 主动关怀循环 |
| `watchdog.py` | 看门狗 |
| `startup_handler.py` | 启动处理 |
| `executor.py` | 执行器门面（QQ连接/LLM生成/硬件意图/触发三段均已拆分，保留转发方法） |
| `trigger_preparer.py` | 触发前置准备（会话路由 → 早安注入 → 历史/上下文 → Prompt，返回 `PreparedTrigger`） |
| `generation_pipeline.py` | 生成 + 后处理管线（预生成文案复用 / 隔离 LLM 路径 → postprocessor） |
| `post_send_handler.py` | 发送后收尾（清早安 pending、通知服务、写日记、清推迟提醒） |
| `context.py` | 上下文管理（会话解析/作息配置已拆分，保留转发方法） |
| `conversation_resolver.py` | 会话 ID 解析与候选排序 |
| `response_generator.py` | LLM 响应生成与 fallback |
| `qq_connection_resolver.py` | QQ/NapCat/官方机器人/WebSocket 连接解析 |
| `hardware_intent.py` | 硬件震动/灯效意图策略 |
| `sleep_policy.py` | 睡眠策略 |
| `sleep_session_manager.py` | 睡眠会话状态机管理器 |
| `user_response_handler.py` | 用户响应处理 |
| `persona_resolver.py` | 人设解析 |

#### 9.2 decision/ — 决策引擎与执行（11个文件）

| 文件 | 职责 |
|------|------|
| `decision.py` | 决策引擎（输出解析/指令构建已拆分，保留转发方法） |
| `decision_executor.py` | 决策执行器（动作构建/上下文采集已拆分，保留转发方法） |
| `decision_context.py` | 决策上下文 |
| `decision_tools.py` | 决策工具 |
| `decision_output_parser.py` | 决策输出解析（JSON 修复，regex fallback，peer chat 解析） |
| `decision_instruction_builder.py` | 决策指令构建 |
| `action_builder.py` | 动作构建器 |
| `context_gatherer.py` | 上下文采集器 |
| `daily_push_priority.py` | 每日推送优先级 |
| `portrait_keyword_map.py` | 画像关键词映射（统一了 decision.py 和 priority_analyzer.py 的重复映射） |
| `priority_analyzer.py` | 优先级分析（每日推送/画像关键词已拆分，保留转发方法） |

#### 9.3 detection/ — 检测与识别（4个文件）

| 文件 | 职责 |
|------|------|
| `activity_detector.py` | 活动检测（活动映射已拆分到 `activity_maps.py`，保留转发方法） |
| `activity_maps.py` | 活动映射表（进程名/窗口标题分类） |
| `intent_detector.py` | 意图检测（BERT 语义先行 + 关键词兜底） |
| `gate_scorer.py` | 软评分门控系统（7 层） |

#### 9.4 postprocess/ — 后处理管线（4个文件）

| 文件 | 职责 |
|------|------|
| `postprocessor.py` | 后处理管线（睡眠净化/去重/泄露检测已拆分，保留转发方法） |
| `sleep_sanitizer.py` | 睡眠净化器（SleepSanitizer） |
| `deduplicator.py` | 去重器（Deduplicator） |
| `leak_detector.py` | 泄露检测器（LeakDetector） |

#### 9.5 peer_chat/ — 同伴对话（5个文件）

| 文件 | 职责 |
|------|------|
| `peer_chat_scheduler.py` | 同伴对话调度 |
| `peer_script_generator.py` | 剧本生成（分发/钩子已拆分，保留转发方法） |
| `peer_script_dispatch.py` | 剧本分发（逐条 WebSocket 广播） |
| `peer_script_hooks.py` | 剧本后处理钩子（日记/会话记录/巡逻触发） |
| `peer_chat_metrics.py` | 同伴对话指标 |

#### 9.6 prompt/ — 提示词构建（3个文件）

| 文件 | 职责 |
|------|------|
| `prompt_builder.py` | Prompt 组装（上下文构建/话题多样性已拆分，保留转发方法） |
| `prompt_context_builders.py` | Prompt 上下文构建（设备/生物/健康/食物/学习上下文） |
| `topic_diversity.py` | 话题多样性控制 |

#### 9.7 scheduling/ — 调度与时间管理（5个文件）

| 文件 | 职责 |
|------|------|
| `scheduler_logic.py` | 心跳间隔计算 |
| `schedule_adapter.py` | 作息学习适配器 |
| `schedule_config_loader.py` | 作息调度配置加载 |
| `delayed_scheduler.py` | 延迟调度 |
| `delayed_task_handler.py` | 延迟任务处理 |

#### 9.8 storage/ — 存储与持久化（3个文件）

| 文件 | 职责 |
|------|------|
| `storage.py` | 存储层（JSON + 延迟写入缓冲）；用户级 `user_sleep_state.json` 同时保存共享低打扰状态与带来源的 Samsung Health 睡眠区间，读取 persona 状态时统一覆盖旧副本 |
| `state_persistence.py` | 状态持久化（事件记录、发送历史） |
| `user_profile_service.py` | 用户画像 |

#### 9.9 checker/ — 检查器子模块（3个文件）

| 文件 | 职责 |
|------|------|
| `checker_init_state.py` | 检查器初始化与状态恢复（CheckerInitState） |
| `checker_client_gate.py` | 检查器客户端门控（CheckerClientGate，活跃检测、私密模式） |
| `checker_throttle.py` | 检查器节流与时间调度（CheckerThrottle，抖动、退避） |

#### 9.10 shared/ — 共享常量与工具（11个文件）

原 `constants.py` 于 2026-09-03 按职责拆分为 9 个原子模块，只保留兼容 re-export 门面：

| 文件 | 职责 |
|------|------|
| `state_keys.py` | `StateKeys` 状态键 + `build_reduced_mode_clear_updates()` / `build_goodnight_clear_updates()` |
| `keywords.py` | 晚安/早安/睡眠暗示/清醒/专注/题材关键词与匹配模式（纯数据） |
| `mode_reasons.py` | 低打扰原因取值域（`SLEEP/FOCUS/QUIET_MODE_REASONS`、`SLEEP_HINT_REASON`）、`SkipReasons`、`SysPromptType` |
| `tuning.py` | 通用数值阈值（检查间隔/生成参数/提醒重试/退避/抖动/情绪乘数） |
| `sleep_thresholds.py` | 睡眠与晚安窗口阈值（自动醒来、晚安信号间隔、作息自适应） |
| `scheduling_utils.py` | 调度纯函数 `calculate_non_response_backoff()`（Equal Jitter） |
| `text_utils.py` | `normalize_content`、时长解析/格式化、人设 token 解析 |
| `prompt_helpers.py` | Prompt 片段构建（睡眠状态描述、静默指令、动作指令变体） |
| `daily_record_sync.py` | `sync_sleep_to_daily_record()`（shared 下唯一带 IO 的模块） |
| `constants.py` | 兼容门面：集中 re-export 上述模块，`__all__` 覆盖 75 个历史导出名 |
| `vocabulary.py` | 词汇学习 |

> 新代码请直接引用原子模块，不要再从 `constants.py` 门面取常量；
> 验证脚本：`tests/scripts/active_care/verify_shared_constants_decoupled.py`。

#### 9.11 state/ — 统一状态管理模块（5个文件，已存在）

| 文件 | 职责 |
|------|------|
| `base.py` | 状态管理基类 |
| `sleep_state.py` | 用户级低打扰与睡眠状态；聊天只进入/退出低打扰，正式睡眠区间由 Samsung Health 写入并标注 main_sleep/nap |
| `focus_state.py` | 专注/学习状态 |
| `mode_state.py` | 模式状态 |
| `manager.py` | 统一状态管理器 |
