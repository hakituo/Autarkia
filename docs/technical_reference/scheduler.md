# 调度系统（C++ 调度器 / 生物学状态）

> 本文同步自项目内部技术参考，仅描述公开可见的实现。
> 由 `scripts/doc_records/sync_tech_docs.py` 生成，请勿直接编辑；修改请改真源后重新生成。
> 文档入口：[技术参考目录](README.md)

---

## 6. 调度系统技术详解

## 6.1 C++调度器架构

**目录**: `cpp_scheduler/`

**核心组件**:

| 组件                         | 文件                                                            | 职责            |
| -------------------------- | ------------------------------------------------------------- | ------------- |
| ResourceIsolationScheduler | `cpp_modules/cpp_scheduler/core/resource_isolation_scheduler.h` | 资源隔离调度器       |
| AsyncScheduler             | `cpp_modules/cpp_scheduler/core/async_scheduler.h`            | 异步任务调度主循环     |
| GpuLlmWorker               | `cpp_modules/cpp_scheduler/workers/gpu_llm_worker.h`          | GPU LLM 工作器    |
| CpuTtsWorker               | `cpp_modules/cpp_scheduler/workers/cpu_tts_worker.h`          | CPU TTS 工作器    |
| TaskQueue                  | `cpp_modules/cpp_scheduler/queue/task_queue.h`                | 任务队列（含优先级）    |
| BioStateStore              | `cpp_modules/cpp_scheduler/core/bio_state_store.h`            | 生物学状态存取       |

**Python绑定**:

```python
# core/services/scheduler/cpp_scheduler_engine.py
class CPPSchedulerEngine:
    def __init__(self):
        self._scheduler = None  # C++调度器实例

    async def initialize(self) -> None:
        """初始化调度器"""
        self._scheduler = create_scheduler(self.config)

    async def submit_llm_task(
        self,
        prompt: str,
        model_config: LLMModelConfig,
        priority: int = 1,
    ) -> AsyncGenerator:
        """提交LLM任务"""
```

**增强功能 (2026-04-03 更新)**:

| 功能                  | 说明                              | 配置项                                                                                                                          |
| ------------------- | ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| **Circuit Breaker** | C++后端连续失败3次后自动熔断，降级到Python后端    | `XIAOYOU_CPP_BREAKER_THRESHOLD` (默认3)`XIAOYOU_CPP_BREAKER_MIN_COOLDOWN_S` (默认5s)`XIAOYOU_CPP_BREAKER_MAX_COOLDOWN_S` (默认60s) |
| **OOM自动重试**         | Python后端OOM时自动卸载并重试             | `XIAOYOU_LLM_OOM_MAX_RETRIES` (默认1)                                                                                          |
| **C++→Python降级**    | C++后端失败时自动切换到Python后端执行         | 自动触发                                                                                                                         |
| **KV Cache保存/恢复**   | 紧急卸载时先保存KV Cache，后台加载CPU实例后恢复   | 自动启用                                                                                                                         |
| **会话KV Cache重置**    | 清除短期记忆时按 conversationId 同步清除显存 sequence、token 镜像与 KV Swap；局部裁剪不受支持时整条重算 | 自动启用 |
| **NVIDIA SMI监控**    | 使用nvidia-smi获取显存使用量（不依赖PyTorch） | 自动启用                                                                                                                         |
| **推理统计信息**          | 记录token生成数量、推理耗时等性能指标           | 通过 `get_last_llm_stats()` 查询                                                                                                 |

**当前模块拆分（2026-06 重构为子目录结构）**:

调度服务已从扁平结构重构为子目录组织，按职责清晰分层：

**顶层文件**:
- `cpp_scheduler_engine.py` — `CPPSchedulerEngine`（单例）主引擎，协调各子模块，提供统一调度接口
  - `clear_conversation_cache(conversation_id)` 通过绑定调用 `GPULLMWorker.clearConversationCache`，供 ChatAgent 清除记忆时同步失效运行时 KV Cache
- `scheduler_wrapper.py` — C++ 扩展绑定层（`_import_scheduler_py` 查找并导入 C++ scheduler 扩展，处理 Windows DLL 搜索路径）

**`bio/` 生物系统**:
- `bio_state.py` — `build_biological_status(bio_system)`：从 C++ bio_system 抽取神经递质/energy/sleep_debt/circadian_phase/cognitive_delay
- `bio_system_manager.py` — `BioSystemManager`：`get_biological_system` / `apply_bio_before_infer`（推理前应用认知延迟/能量消耗）

**`client/` C++ 调度器 HTTP 客户端**:
- `cpp_client.py` — `CPPSchedulerClient`（httpx.AsyncClient，30s 超时，`connect`/`submit_llm_task`/`submit_tts_task`）
- `cpp_config_builder.py` — `CPPConfigBuilder`：dict 配置映射到 C++ `LLMModelConfig`（驼峰/下划线双写属性）

**`inference/` 推理执行**:
- `inference_executor.py` — `InferenceExecutor`：推理任务执行器（架构明确为"Python 路由层 → C++ 执行层，不存在 Python 后端降级"）
- `cpp_llm_handler.py` — C++ 后端 LLM 推理路径（`on_token` 回调 + `asyncio.Queue` + `call_soon_threadsafe` 桥接异步流）
- `python_llm_handler.py` — Python 后端 LLM 推理路径（`llama_cpp`，.gguf 模型热切换，`_llm_setup_lock` 串行化加载）
- `inference_stats.py` — `record_llm_inference_stats` / `get_last_llm_stats`
- `inference_utils.py` — `messages_to_text`/`clamp_messages`/`clamp_text`/token 估算（尝试加载 C++ 加速分词器）

**`lifecycle/` 调度器生命周期**:
- `scheduler_lifecycle.py` — `SchedulerLifecycle`：`start(worker_count, gpu_config, preload_llm)` 初始化并启动 C++ ResourceIsolationScheduler
- `health_monitor.py` — `HealthMonitor`：`health_check_gpu_worker` 提交简单推理测试验证 GPU worker 健康

**`model/` 模型与 GPU 资源**:
- `llm_model_manager.py` — `LLMModelManager`：LLM 模型生命周期管理（加载/卸载/切换，`_patch_llama_cpp_internals` 防崩溃，`ThreadPoolExecutor` 加载）
- `gpu_resource_manager.py` — GPU 资源管理（`_cleanup_gpu_instance` 清理旧 LLM 实例并释放显存，`_update_resource_manager_state` 同步状态）

**C++ Llama Worker 实现**:
- `llama_model_impl.cpp` — tokenization 与生成循环
- `llama_model_cache.cpp` — 会话 sequence、KV Cache、KV Swap 与清理
- `llama_model_lifecycle.cpp` — 模型/context 初始化、关闭和状态查询
- `llama_model_runtime.cpp` — decode 超时、batch、采样和 UTF-8 辅助

**`task/` 任务调度**:
- `task_scheduler.py` — `GlobalTaskScheduler`：统一全局任务调度器（`TaskPriority`/`TaskType`/`TaskInfo`，状态对齐 `core.contracts.TaskStatus`）
- `task_scheduler_adapter.py` — `TaskSchedulerAdapter`：适配器，封装 `GlobalTaskScheduler`，支持无缝切换到 C++ 资源隔离调度器
- `async_task_wrapper.py` — 异步任务包装器（扩展 `TaskType`：CPU/GPU/IO/TTS/STT/IMAGE/LLM，`EnhancedTaskInfo`）

**`utils/` 工具函数**:
- `circuit_breaker.py` — 断路器机制（`BreakerState`/`BreakerRegistry`，指数退避倍增 cooldown，兼容旧 dict 接口）
- `error_utils.py` — 错误检测与友好转换（`is_oom_error`/`is_cuda_backend_error`/`friendly_llm_error`）
- `kv_cache_manager.py` — KV Cache 紧急保存/恢复（`save_llm_state_emergency`/`restore_llm_state_emergency`，失败非致命）
- `nvidia_smi_monitor.py` — nvidia-smi 显存读取（优先 pynvml，回退子进程，2 秒 TTL 缓存）
- `resource_utils.py` — 资源管理公共工具（`MemoryPressureResult`/`check_memory_pressure`/`offload_tts_services`/`read_kv_swap_config`/`set_llm_config_attr`/`get_cuda_free_mb`）
- `startup_config.py` — 启动配置（`resolve_llm_backend` 按 gpu_config + 环境变量 + settings 决定 cpp/python，`apply_biological_config` 写入 C++ `BiologicalConfig`）

**断路器状态查询示例**:

```python
engine = get_scheduler_engine()

# 查询断路器状态
breaker_status = engine.get_breaker_status()
# 返回: {"llm": {"is_open": False, "failures": 0, ...}, "image": {...}}

# 查询最近一次推理统计
stats = engine.get_last_llm_stats()
# 返回: {"backend": "cpp", "generated_tokens": 150, "inference_time_s": 2.35, ...}
```

## 6.2 生物学状态驱动

**文件**: `core/services/scheduler/bio/bio_state.py`（已迁移到 `bio/` 子目录）

**神经递质模型**:

```python
@dataclass
class Neurotransmitters:
    dopamine: float = 0.5      # 多巴胺：奖励/动机
    serotonin: float = 0.5     # 血清素：情绪稳定
    norepinephrine: float = 0.5 # 去甲肾上腺素：注意力
    oxytocin: float = 0.5      # 催产素：社交连接
    cortisol: float = 0.3      # 皮质醇：压力水平
```

**认知延迟计算**:

```python
def calculate_cognitive_delay(bio_state: BiologicalState) -> float:
    """计算认知延迟（秒）"""
    base_delay = 0.5

    # 能量影响
    energy_factor = 1.0 + (1.0 - bio_state.energy) * 0.5

    # 睡眠债务影响
    sleep_factor = 1.0 + bio_state.sleep_debt * 0.3

    # 皮质醇影响
    stress_factor = 1.0 + bio_state.neurotransmitters.cortisol * 0.2

    return base_delay * energy_factor * sleep_factor * stress_factor
```
