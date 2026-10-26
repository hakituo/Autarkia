# 配置项（服务 / 时间段 / 动作）

> Active Care 子文档 · 上级入口：[README.md](../README.md)
> 只写当前实现；变更史进 `docs/updates/`。

---

## 配置

### 服务配置

```python
# config/integrated_config.py
class ActiveCareSettings:
    # 基础间隔（秒）
    base_interval: int = 1800  # 30分钟

    # 静默阈值（秒）
    silence_threshold: int = 2700  # 45分钟

    # 最大间隔（秒）
    max_interval: int = 7200  # 2小时

    # 最小间隔（秒）
    min_interval: int = 600  # 10分钟
```

### 时间段配置

```python
# 时间段定义
TIME_PERIODS = {
    "morning": (6, 12),    # 早晨
    "afternoon": (12, 18), # 下午
    "evening": (18, 22),   # 傍晚
    "night": (22, 6),      # 深夜
}
```

### 动作配置

```python
# 动作权重
ACTION_WEIGHTS = {
    "greeting": 1.0,
    "reminder": 1.2,
    "weather": 0.8,
    "health": 1.0,
    "emotion": 1.1,
    "study": 0.9,
    "random": 0.7,
}
```
