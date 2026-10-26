# 启动配置

> 调度服务子文档 · 上级入口：[README.md](../README.md)
> 只写当前实现；变更史进 `docs/updates/`。

---

## 配置

### 启动配置

**文件**: `startup_config.py`

```python
# LLM后端配置
LLM_BACKEND = "cpp"  # "cpp" | "python" | "cloud"

# Worker数量
WORKER_COUNT = 3

# GPU配置
GPU_MEMORY_FRACTION = 0.8

# 生物学配置
BIOLOGICAL_CONFIG = {
    "base_energy": 100.0,
    "sleep_debt_rate": 0.1,
    "recovery_rate": 0.05,
}
```
