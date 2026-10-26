# 数据流与调用链路

> 本文同步自项目内部技术参考，仅描述公开可见的实现。
> 由 `scripts/doc_records/sync_tech_docs.py` 生成，请勿直接编辑；修改请改真源后重新生成。
> 文档入口：[技术参考目录](README.md)

---

## 9. 数据流与调用链路

## 9.1 对话主链路

```
用户消息
    │
    ▼
routers/api_v1/chat.py::chat()
    │
    ▼
core/services/aveline/service.py::AvelineService.chat()
    │
    ├──▶ core/services/aveline/chat_agent.py::ChatAgent.process()
    │        │
    │        ├──▶ 意图识别
    │        ├──▶ 记忆检索 (memory/weighted_memory_manager.py)
    │        ├──▶ 情绪更新 (core/emotion/manager.py)
    │        └──▶ LLM调用
    │
    ├──▶ core/services/scheduler/task/task_scheduler.py::submit_task()
    │        │
    │        └──▶ cpp_scheduler/ (C++调度引擎)
    │
    ├──▶ 记忆写入 (memory/weighted_memory_manager.py)
    │
    └──▶ WebSocket/HTTP返回
```

## 9.2 主动关怀链路

```
lifecycle_manager.initialize_active_care_service()
    │  读取 active_care_enabled 配置 → enable_proactive_checker
    ▼
core/services/active_care/core/service.py::ActiveCareService._proactive_loop()
    │
    ├──▶ if checker: ProactiveChecker.perform_check()
    │        │
    │        ├──▶ 客户端检测 / 私密模式检测
    │        ├──▶ 睡眠会话状态处理
    │        ├──▶ Focus reduced policy 检查
    │        ├──▶ Sleep probe policy 检查
    │        ├──▶ PriorityAnalyzer 优先级分析
    │        ├──▶ DecisionExecutor 动作选择 + LLM 决策
    │        └──▶ Executor.trigger_message() 消息生成和发送
    │
    └──▶ else: _fallback_proactive_check()  # 保底触发（checker 未启用时）
             │
             └──▶ Executor.trigger_message(sys_prompt_type="share_thought")

关键配置项（config/yaml/app.yaml）:
- active_care_enabled: true/false  → 控制 ProactiveChecker 是否启用
- active_care_require_active_client: true/false  → 是否要求有活跃客户端
- active_care_min_gap_seconds: 600  → 最小消息间隔
- active_care_default_next_check_seconds: 300  → 默认检查间隔
- active_care_daily_limit: 30  → 每日消息上限

关键阈值（2026-09-03 拆分为 `shared/tuning.py` 通用阈值 + `shared/sleep_thresholds.py` 睡眠阈值）:
- SILENCE_BREAKER_SECONDS: 1800  → 沉默打破阈值
- LONG_SILENCE_THRESHOLD_SECONDS: 600  → 长沉默判定阈值
- BACKOFF_BASE: 1.4, BACKOFF_CAP: 6.0  → 统一退避算法基数和上限
- JITTER_LOW_RATIO: 0.9, JITTER_HIGH_RATIO: 1.1  → 对称抖动因子
- EMOTION_INTERVAL_MULTIPLIERS  → 情绪-间隔乘数映射（配置化）
- AUTO_WAKE_MAX_HOURS: 14  → 自动退出晚安模式最大小时数
- GOODNIGHT_SIGNAL_GAP_SECONDS: 300  → 晚安后信号判定间隔
- INTERVAL_MIN_SECONDS: 30  → 最小检查间隔

决策上下文阈值（core/services/active_care/decision/decision_context.py）:
- long_silence_seconds: 3600（当 min_gap≤1200）或 min_gap*3（当 min_gap>1200）
- no_send_for_too_long: min_gap*2  → 无发送超时判定
```

## 9.2.1 今日计划落盘与提醒链路

```
用户消息（如“帮我计划一下今天干什么”）
    │
    ▼
core/services/aveline/service.py::generate_response()
    │
    ├──▶ 通过 BERT 意图识别 `GENERATE_DAILY_PLAN`
    ├──▶ 追加 Plan Instruction，强制模型输出 HH:MM-HH:MM 时间块
    │
    ▼
core/services/aveline/response_postprocess.py::maybe_capture_daily_plan()
    │
    ├──▶ 解析回复中的时间计划
    ├──▶ 必要时用 LLM 做 JSON 提取兜底
    │
    ▼
core/services/workspace/service.py::replace_daily_plan()
    │
    ▼
core/services/workspace/daily_task_service.py::replace_daily_plan()
    │
    ├──▶ 替换旧的 planner_ai / study_progress pending 任务
    ├──▶ 保留 manual 与已完成任务
    ├──▶ 为 timed task 重新创建 reminder
    │
    ▼
core/services/active_care/core/service.py::notify_workspace_plan_updated()
    │
    ├──▶ 提前调整 checker.next_decision_ts
    └──▶ 唤醒 Active Care loop，等待最近一个计划提醒点
```

## 9.3 记录落盘链路

```
core/services/workspace/service.py::WorkspaceService
    │
    ├──▶ core/services/journal/storage.py (日记)
    │        │
    │        └──▶ companion_data/user_data/daily/YYYY/MM/DD/diary/*.json
    │
    ├──▶ core/services/daily/manager.py (画像)
    │        │
    │        └──▶ companion_data/user_data/daily_records/YYYY/M/D/daily_record.json
    │
    ├──▶ status_manager.py (状态)
    │        │
    │        └──▶ companion_data/user_data/status/user_status.json
    │
    ├──▶ daily_task_service.py (每日任务 / 今日计划)
    │        │
    │        ├──▶ companion_data/user_data/daily_records/YYYY/M/D/daily_record.json
    │        └──▶ companion_data/user_data/reminders.json
    │
    ├──▶ core/food/manager.py (角色自主进食)
    │        │
    │        └──▶ companion_data/aveline_data/life_records/YYYY/M/D/daily_record.json
    │
    └──▶ 本地JSON存储
```
