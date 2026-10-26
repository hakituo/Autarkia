# 使用示例

> Active Care 子文档 · 上级入口：[README.md](../README.md)
> 只写当前实现；变更史进 `docs/updates/`。

---

## 使用示例

### 启动服务

```python
from core.services.active_care.core.service import get_active_care_service

# 获取服务实例
service = get_active_care_service()

# 启动服务
await service.start()

# 停止服务
await service.stop()
```

### 手动触发关怀

```python
# 手动触发关怀检查
result = await service.checker.check_proactive_care()
if result:
    action = result.get("action")
    context = result.get("context")
    success, message = await service.executor.execute_care(action, context)
```

### 更新奖励

```python
# 用户积极响应后更新奖励
await service.decision.update_policy_reward(
    action="greeting",
    reward=1.0  # 0.0-1.0
)
```

### 设置模式

```python
# 设置专注模式
service.mode_state.set_mode("focus")

# 设置睡眠模式
service.mode_state.set_mode("sleep")
```
