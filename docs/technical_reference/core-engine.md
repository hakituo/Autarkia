# 核心引擎层（core_engine）

> 本文同步自项目内部技术参考，仅描述公开可见的实现。
> 由 `scripts/doc_records/sync_tech_docs.py` 生成，请勿直接编辑；修改请改真源后重新生成。
> 文档入口：[技术参考目录](README.md)

---

## 2. 核心引擎层技术详解

## 2.x 状态契约统一（避免漂移）

项目中“资源状态、模型状态、服务健康、任务状态”曾在多个模块各自定义/各自输出，长期会导致 API 字段漂移、监控/调试困难。

现在统一收敛为：

- 统一枚举：`core/contracts/states.py`
- `/health` 聚合端点会同时输出：
  - `resources`（系统资源快照，来自 `core/services/monitoring/resource_monitor.py::to_contract_dict()`）
  - `resource_manager`（模型/显存调度快照，来自 `core/resource_manager.py::get_resource_stats()`，包含 `snapshot`）
  - `gpu_gate`（全局 GPU 背压门控状态，来自 `core/utils/concurrency/resource_lock.py`）
  - `tasks`（活跃任务列表，来自 `core/services/scheduler/task/task_scheduler.py`）
  - `lifecycle`（服务初始化状态，来自 `core/core_engine/lifecycle_manager.py`）

其中：

- `TaskStatus` 对齐 `pending/running/completed/failed/cancelled`
- 模块初始化态使用 `ModuleInitState`（例如 LLM/调度器适配器会在 `get_status()/get_stats()` 中增加 `init_state` 字段）
- 模型运行态与初始化态分离：`ModelRuntimeState`（loaded/offloaded/unloaded）不等同于 `ModuleInitState`

建议：新模块对外输出状态时优先复用契约枚举值，避免再引入 `queued/processing` 等不一致的字符串。

## 2.1 CoreEngine 类（已删除）

> **已删除 (2026-06-17)**：`core/core_engine/engine.py` 已作为死代码删除。该文件头部明确标注"已废弃，已被 ServiceLifecycle + EventBus 完全覆盖"。全项目搜索确认生产代码无任何 import 引用。
>
> 当前核心引擎层的职责由以下组件承担：
> - **EventBus** (`event_bus.py`)：事件总线
> - **LifecycleManager** (`lifecycle_manager.py`)：生命周期管理（`ServiceLifecycle` 类）
> - **ServiceRegistry** (`service_registry.py`)：默认服务注册逻辑
> - **ServiceSingletons** (`service_singletons.py`)：业务单例管理（Aveline/Vision/ActiveCare）
> - **ModelManager** (`model_manager.py`)：模型管理
> - **ConfigManager** (`config_manager.py`)：配置管理

启动流程改为：

```
main.py → core/lifecycle/lifespan.py → lifecycle_manager.initialize_default_services()
                                      → lifecycle_manager.initialize_all()
```

## 2.2 LifecycleManager 类

**文件**: `core/core_engine/lifecycle_manager.py`

**职责**: 服务注册、并行初始化、优雅关闭、自动重启

**启动流程**:

```
main.py → lifespan.py → lifecycle_manager.initialize_default_services()
                        → lifecycle_manager.initialize_all()
```

**服务优先级分组**（同优先级并行初始化，跨优先级串行）:

| 优先级 | 服务 | 说明 |
|--------|------|------|
| 1 | resource_manager, log_sanitizer, cpu_processor | 基础资源层，互不依赖 |
| 2 | config_manager, search_cache_manager, cache_system, system_memory_manager | 配置与缓存层 |
| 3 | image_manager, cpp_scheduler_engine | 调度器层（依赖 resource_manager） |
| 4 | task_scheduler, monitoring_system | 任务与监控层 |
| 5 | immune_system, websocket_adapter | 安全与通信层 |
| 6 | aveline_service, active_care_service | 业务服务层，互不依赖 |
| 7 | auto_heal_service | 自愈服务（依赖 aveline_service 进行 LLM 分析） |

**关键优化**:
- 延迟导入：所有服务注册使用函数级延迟导入，避免启动时加载重模块
- 预加载机制：并行初始化前先串行预加载 `preload_modules` 中的模块
- `asyncio.gather()` 实现同优先级服务的并行初始化

## 2.3 EventBus 类

**文件**: `core/core_engine/event_bus.py`

**职责**: 模块间通信、事件发布订阅

**关键方法**:

```python
class EventBus:
    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}
        self._event_queue: asyncio.Queue = asyncio.Queue()

    def subscribe(self, event_type: str, handler: Callable) -> None:
        """订阅事件"""

    def unsubscribe(self, event_type: str, handler: Callable) -> None:
        """取消订阅"""

    async def publish(self, event_type: str, data: Any) -> None:
        """发布事件"""

    async def _process_events(self) -> None:
        """事件处理循环"""
```

**事件类型**:

| 事件类型              | 说明     | 数据结构                     |
| ----------------- | ------ | ------------------------ |
| `system.startup`  | 系统启动   | `{}`                     |
| `system.shutdown` | 系统关闭   | `{}`                     |
| `model.loaded`    | 模型加载完成 | `{model_id, model_type}` |
| `model.unloaded`  | 模型卸载完成 | `{model_id}`             |
| `memory.updated`  | 记忆更新   | `{memory_id, weight}`    |
| `emotion.changed` | 情绪变化   | `{emotion, intensity}`   |

## 2.3 ResourceManager 类

**目录**: `core/resource/`（主模块）, `core/resource_manager.py`（兼容层）

**职责**: 统一管理系统资源（内存、CPU、GPU、磁盘），并将基础资源组件与主调度逻辑解耦

**模块结构**（2026-05-29重构）:

现在采用模块化结构：

- `core/resource/config.py` — 配置管理（ResourceConfig数据类）
- `core/resource/monitor.py` — 资源监控 + GPU缓存优化（0.5秒TTL）
- `core/resource/model_manager.py` — 模型生命周期管理
- `core/resource/cleanup.py` — 清理策略（策略模式，支持动态冷却时间）
- `core/resource/gpu.py` — GPU显存管理和模型卸载/加载
- `core/resource/manager.py` — 主管理器，整合所有子模块
- `core/resource_components.py` — 基础组件（ResourceMonitor, ModelResource等）
- `core/resource_manager.py` — 兼容层，从新模块导入

**关键方法**:

ResourceManager类提供以下核心功能：
- 模型注册/卸载管理
- 重负载任务资源准备
- 三级清理策略（常规/临界/紧急）
- GPU模型自动回迁
- 资源状态监控和统计

**资源优先级**:

| 优先级 | 模型类型      | 说明    |
| --- | --------- | ----- |
| 10  | LLM       | 最高优先级 |
| 8   | Vision    | 视觉模型  |
| 6   | TTS       | 语音合成  |
| 4   | Image Gen | 图像生成  |
| 2   | STT       | 语音识别  |
