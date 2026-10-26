# 核心组件（全局调度 / C++ 引擎 / 生物状态 / GPU / 模型）

> 调度服务子文档 · 上级入口：[README.md](../README.md)
> 只写当前实现；变更史进 `docs/updates/`。

---

## 核心组件

### 1. GlobalTaskScheduler (全局任务调度器)

**文件**: `task_scheduler.py`

统一全局任务调度器，管理所有后台任务：

```python
class GlobalTaskScheduler:
    def __init__(self):
        self._tasks: Dict[str, Dict] = {}
        self._task_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._worker_count: int = 3

    async def submit_task(
        self,
        name: str,
        coro: Callable,
        priority: TaskPriority = TaskPriority.MEDIUM,
        task_type: TaskType = TaskType.DEFAULT,
    ) -> str:
        """提交任务到调度器"""

    async def cancel_task(self, task_id: str) -> bool:
        """取消任务"""

    async def get_task_status(self, task_id: str) -> Optional[TaskInfo]:
        """获取任务状态"""
```

**任务优先级**:
| 优先级 | 值 | 说明 |
|--------|---|------|
| LOW | 0 | 低优先级 |
| MEDIUM | 1 | 中优先级 |
| HIGH | 2 | 高优先级 |
| CRITICAL | 3 | 关键任务 |

**任务类型**:
| 类型 | 说明 |
|------|------|
| DEFAULT | 默认（IO密集型或普通异步任务） |
| CPU_BOUND | CPU密集型（使用线程池） |
| GPU_BOUND | GPU密集型（使用GPU锁） |

**任务状态（统一契约）**:

为避免 Python/C++/API 字段漂移，任务状态已统一对齐 `core/contracts/states.py::TaskStatus`：

| 状态 | 说明 |
|------|------|
| pending | 等待执行 |
| running | 正在执行 |
| completed | 执行完成 |
| failed | 执行失败 |
| cancelled | 已取消 |

> 说明：C++ Scheduler 的 HTTP API 也已同步输出 `pending/running/...`，不再使用 `queued/processing` 等非标准字符串。

### 2. CPPSchedulerEngine (C++调度引擎)

**文件**: `cpp_scheduler_engine.py`

C++高性能调度引擎的Python集成：

```python
class CPPSchedulerEngine:
    async def submit_llm_task(
        self,
        prompt: str,
        model_config: LLMModelConfig,
        priority: int = 1,
    ) -> AsyncGenerator:
        """提交LLM任务"""

    async def get_status(self) -> Dict[str, Any]:
        """获取调度器状态"""

    async def shutdown(self):
        """关闭调度器"""
```

**特性**:
- 高性能C++调度核心
- GPU资源隔离
- 多Worker支持
- 生物学状态驱动
- C++→Python 熔断降级
- KV Cache 紧急保存/恢复
- 按会话清理 KV Cache：短期记忆重置会同步失效对应 `conversationId` 的显存 sequence、token 镜像和 KV Swap
- M-RoPE 兼容回退：llama.cpp 不支持局部 sequence 裁剪时，整条清空并从位置 0 重新 prefill
- Llama C++ 实现按推理、会话缓存、生命周期、运行时辅助拆为四个翻译单元，避免模型加载与缓存状态继续堆入生成循环文件
- 推理统计与显存监控

### 3. Biological Status (生物学状态)

**文件**: `bio_state.py`

生物学状态构建，用于驱动智能调度：

```python
def build_biological_status(bio_system: Any) -> Optional[Dict[str, Any]]:
    """构建生物学状态"""
    return {
        "neurotransmitters": {
            "dopamine": float,
            "serotonin": float,
            "norepinephrine": float,
            "oxytocin": float,
            "cortisol": float,
        },
        "energy": float,
        "sleep_debt": float,
        "circadian_phase": str,
        "cognitive_delay": float,
    }
```

**神经递质影响**:
| 神经递质 | 影响 |
|---------|------|
| dopamine | 奖励/动机，影响任务优先级 |
| serotonin | 情绪稳定，影响响应延迟 |
| norepinephrine | 注意力，影响并发度 |
| oxytocin | 社交连接，影响交互频率 |
| cortisol | 压力水平，影响资源分配 |

### 4. GPU Resource Manager (GPU资源管理器)

**文件**: `gpu_resource_manager.py`

GPU资源管理：

```python
class GPUResourceManager:
    async def acquire_gpu(self, task_id: str, memory_required: int) -> bool:
        """获取GPU资源"""

    async def release_gpu(self, task_id: str):
        """释放GPU资源"""

    def get_available_memory(self) -> int:
        """获取可用显存"""
```

### 5. LLM Model Manager (LLM模型管理器)

**文件**: `llm_model_manager.py`

LLM模型生命周期管理：

```python
class LLMModelManager:
    async def load_model(self, model_id: str, config: Dict) -> bool:
        """加载模型"""

    async def unload_model(self, model_id: str):
        """卸载模型"""

    async def get_model(self, model_id: str) -> Optional[Any]:
        """获取模型实例"""
```
