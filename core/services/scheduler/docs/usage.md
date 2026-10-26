# 使用示例

> 调度服务子文档 · 上级入口：[README.md](../README.md)
> 只写当前实现；变更史进 `docs/updates/`。

---

## 使用示例

### 提交任务

```python
from core.services.scheduler.task_scheduler import get_task_scheduler, TaskPriority, TaskType

scheduler = get_task_scheduler()

# 提交普通异步任务
task_id = await scheduler.submit_task(
    name="data_processing",
    coro=process_data(),
    priority=TaskPriority.MEDIUM,
    task_type=TaskType.DEFAULT,
)

# 提交CPU密集型任务
task_id = await scheduler.submit_task(
    name="heavy_computation",
    coro=compute_heavy(),
    priority=TaskPriority.HIGH,
    task_type=TaskType.CPU_BOUND,
)

# 提交GPU任务
task_id = await scheduler.submit_task(
    name="llm_inference",
    coro=run_llm_inference(),
    priority=TaskPriority.CRITICAL,
    task_type=TaskType.GPU_BOUND,
)
```

### 查询任务状态

```python
# 获取任务状态
status = await scheduler.get_task_status(task_id)
if status:
    print(f"Task {task_id}: {status.status}")
    if status.result:
        print(f"Result: {status.result}")
    if status.error:
        print(f"Error: {status.error}")
```

### 取消任务

```python
# 取消任务
success = await scheduler.cancel_task(task_id)
if success:
    print(f"Task {task_id} cancelled")
```

### 使用C++调度引擎

```python
from core.services.scheduler.cpp_scheduler_engine import cpp_scheduler_engine

# 提交LLM任务
async for chunk in cpp_scheduler_engine.submit_llm_task(
    prompt="你好，请介绍一下自己。",
    model_config=LLMModelConfig(
        model_path="models/qwen-7b.gguf",
        n_gpu_layers=35,
        n_ctx=4096,
    ),
    priority=2,
):
    print(chunk, end="", flush=True)

# 获取状态
status = await cpp_scheduler_engine.get_status()
print(f"Running tasks: {status['running']}")
print(f"Pending tasks: {status['pending']}")
```
