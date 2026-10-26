# 其余服务（Workspace / Scheduler / MetaIntent / 平台杂项）

> 本文同步自项目内部技术参考，仅描述公开可见的实现。
> 由 `scripts/doc_records/sync_tech_docs.py` 生成，请勿直接编辑；修改请改真源后重新生成。
> 文档入口：[技术参考目录](../README.md)

---

## 3.3 WorkspaceService

**文件**: `core/services/workspace/service.py`

**职责**: 工作空间统一记录执行层

**存储路径**:

| 数据类型   | 存储路径                                                                          |
| ------ | ----------------------------------------------------------------------------- |
| 用户状态   | `companion_data/user_data/status/user_status.json`                            |
| 日记     | `companion_data/user_data/daily/YYYY/MM/DD/diary/*.json`                      |
| 明日计划   | `companion_data/user_data/daily/YYYY/MM/DD/plan.json`                         |
| 每日画像   | `companion_data/user_data/daily_records/YYYY/M/D/daily_record.json`           |
| 提醒     | `companion_data/user_data/reminders.json`                                     |
| 角色仿生档案 | `companion_data/aveline_data/aveline_life/YYYY/M/D/bionic_delay_profile.json` |
| 角色进食记录 | `companion_data/aveline_data/life_records/YYYY/M/D/daily_record.json`         |

**起床时间合并规则**:

- `core/services/health_sync/wakeup.py` 会将健康设备的 `sleep_end`
  转换为配置时区后写入对应自然日的 `daily_record.sleep_cycle.wakeup`。
- 起床来源优先级为：用户手动修正 > Samsung Health > Active Care
  睡眠会话 > 聊天中的明确时间 > 聊天当前时刻推断。
- 讨论、询问或纠正“记录里的起床时间”不触发被动起床写入；
  低优先级聊天推断不得覆盖健康设备数据。

**关键方法**:

```python
class WorkspaceService:
    async def get_daily_workspace_snapshot(self, date: str) -> Dict:
        """获取每日工作空间快照"""
        return {
            "status": await self.status_manager.get_status(),
            "journal": await self.journal_service.get_entries(date),
            "reminders": await self.reminder_manager.get_reminders(date),
            "daily_record": await self.daily_manager.get_record(date),
        }
```

## 3.4 SchedulerService

**文件**: `core/services/scheduler/task/task_scheduler.py`

**职责**: 全局任务调度

**任务优先级**:

```python
class TaskPriority(IntEnum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3
```

**任务类型**:

```python
class TaskType(Enum):
    DEFAULT = "default"      # IO密集型
    CPU_BOUND = "cpu_bound"  # CPU密集型
    GPU_BOUND = "gpu_bound"  # GPU密集型
```

**关键方法**:

```python
class GlobalTaskScheduler:
    async def submit_task(
        self,
        name: str,
        coro: Callable,
        priority: TaskPriority = TaskPriority.MEDIUM,
        task_type: TaskType = TaskType.DEFAULT,
    ) -> str:
        """提交任务"""

    async def cancel_task(self, task_id: str) -> bool:
        """取消任务"""

    async def get_task_status(self, task_id: str) -> Optional[TaskInfo]:
        """获取任务状态"""
```

---

## 3.5 MetaIntentService（元认知服务）— ⚠️ 待定模块

**文件**: `core/services/metacognition/service.py`

**当前状态**: 此模块的功能已被现有系统覆盖，暂不接入主流程。

**覆盖情况**:

| 元认知功能 | 已被覆盖的系统 |
|-----------|-------------|
| 意图追踪 | PersistentStateTracker + BERT 意图检测 |
| 主动提醒 | Active Care（reminder / health_reminder / wake_up_greeting） |
| 历史检索 | RAG search_memory（语义级检索） |
| 行为记录 | 日记系统（Journal）+ tomorrow_tone 回注 + 明日学习生活计划（Plan） |
| 计划执行 | 明日计划（PlanItem TODO 勾选）+ Priority 系统联动主动推送 |
| 去重/防重复 | Active Care 三层去重 + 二次改写 |

**潜在方向（待讨论）**:
- AI 回复风格的量化追踪与自适应
- 对话节奏感知（用户回复间隔变化趋势）
- 跨人设行为一致性校验

**相关 Bug 修复**: Active Care 话题冷却从只覆盖 sleep 扩展到覆盖所有已定义话题类别（greeting/care），见 `prompt_builder.py` 的 `check_topic_cooldown`

---

## 3.9 其他服务模块（2026-06 新增汇总）

以下服务模块为近期新增，体量较小，统一说明：

| 服务 | 文件 | 职责 |
|------|------|------|
| **CommandHandler** | `core/agents/chat_agent_components/handler.py` | 命令处理系统。用字典映射处理斜杠命令（`/clear` `/save` `/load` `/memory` `/setmemory` `/system` `/help`），内部持有轻量级 `WeightedMemoryManager` 与默认 chat agent |
| **MessageComposer** | `core/services/active_care/prompt/sections/composer.py` | 消息组装器（静态工具类）。统一构造 `UnifiedMessage`：文本/图片/语音消息，以及流式响应 chunk 字典 |
| **UDPBeaconService** | `core/services/discovery/udp_beacon.py` | UDP 服务发现信标。向局域网广播 `AVELINE_SERVER\|http://<ip>:<port>[\|http://<vpn-ip>:<port>]`（端口 28899，默认 5 秒间隔），供安卓客户端零配置发现后端。第三段是**可选**的组网地址，客户端据此自动填组网槽位；载荷拼装在 `build_message()`，与客户端 `BeaconPayload.parse()` 是一对线上契约（两侧各有单测钉住） |
| **find_vpn_address** | `core/services/discovery/vpn_address.py` | 组网地址探测。用 `psutil.net_if_addrs()` 枚举网卡，挑出 CGNAT `100.64.0.0/10` 段（Tailscale / WireGuard 默认分配段）的 IPv4 地址。与「局域网 IP」取法不同：后者是默认路由出口地址，组网地址在另一张虚拟网卡上，只能枚举网卡拿到 |
| **IntentService** | `core/services/intent/service.py` | 意图识别服务。BERT 模型为主 + 高频正则规则第一层拦截的混合方案。导出 `rule_classify_intent`/`classify_intent`/`normalize_slots`，覆盖切换/列表/清空记忆/帮助/模型/语音/人设/延迟/系统状态/赞美等意图 |
| **ReactionManager** | `core/services/reaction/reaction_manager.py` | 自发反应管理器。基于系统状态/环境/上次交互时间触发角色自发反应；带冷却时间（默认 5 分钟，演示模式 10 秒），依赖 `AvelineCharacter` 的反射（reflexes） |
| **RemoteOpsService** | `core/services/remote_ops/service.py` | 远程操作服务（单例）。封装 workspace 的文件动作（list/read/write/append/mkdir/exists），带 `max_chars`/`limit` 限制；`approve_action`/`reject_action` 为审批预留接口，学习文件操作已改为沙箱内直接执行，当前直接返回「无需审批」 |
| **UserPhysiologyService** | `core/services/user_physiology/service.py` | 用户生理状态服务。按 user_id 维护最新生理指标，原子写 JSON（`runtime/user_physiology.json`），线程锁保护 |
| **VTubeStudioService** | `core/services/vtube/service.py` | VTube Studio 集成服务。基于 `pyvts` 控制 VTube Studio 模型，按情绪触发 hotkey/表情；后台 `_connect_loop` 异步连接，配置走 `settings.vtube` |

**API 契约层**（`core/api/`，新增）:
- `contract.py` — `success_response(data, message)` 与 `error_response(error_code, message, request_id, details)` 统一封装；`validate_internal_token` 校验 `X-Internal-Token`
- `error_response.py` — `ErrorCode` 枚举覆盖系统/请求/认证/资源/LLM/任务调度/速率限制/业务领域错误码

**业务管理器**（`core/managers/`，新增）:
- `notification_manager.py` — `NotificationManager`（单例）：按 user_id 维护 `deque(maxlen=50)` 通知队列，`has_active_connections`（60 秒窗口）
- `preference_manager.py` — `PreferenceManager`（单例）：持久化到 `runtime/user_preferences.json`，偏好含 mode/active_care_enabled/response_length/conversation_style/sensitivity/debug_visible
- `session_manager.py` — `SessionManager`：多会话管理器，按 scope（aveline/ling）+ legacy 三处文件聚合加载

**虚拟环境间通信**（`core/env/`，新增）:
- `env_communication_manager.py` — 环境通信管理器（`Message` dataclass，`MessageQueue` 进程间队列按 topic 订阅通知）
- `websocket_client.py` — WebSocket 客户端（`WebSocketMessage` dataclass，处理 `ConnectionClosedOK/Error`）

**应用生命周期**（`core/lifecycle/`，新增）:
- `lifespan.py` — FastAPI 应用生命周期管理。`_force_kill_self` 强杀进程树（psutil）；`_install_windows_console_close_handler` 处理 Windows 控制台关闭事件；集成 `lifecycle_manager`/`service_registry`/`EventBus`/`performance_monitor`/`discovery.udp_beacon` 的启停

**Journal 计划中途重排**（`core/services/journal/plan_checkpoint_service.py`，新增）:
- 在 `12:00` 与 `18:00` 两个检查点对“今日用户计划”做自动复盘，配置位于 `config/yaml/app.yaml -> journal_plan.checkpoint_reassessment`
- 复盘入口由 `ActiveCare` 主循环顺带调用，避免新增独立守护线程
- 判断条件优先走代码规则：超时未完成、剩余负载明显超过剩余时间、傍晚仍零完成时触发自动压缩
- 重排时复用计划生成模型路由（`character_daily_models.plan_generator`），只重写“今天剩余时段”的待办项
- 已完成/已跳过/进行中的旧项保留，明显错过的旧项沉淀为 `skipped`，新生成项重新同步提醒与 `plan.md`
