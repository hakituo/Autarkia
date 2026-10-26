# 错误处理（OOM / CUDA）

> 调度服务子文档 · 上级入口：[README.md](../README.md)
> 只写当前实现；变更史进 `docs/updates/`。

---

## 错误处理

### OOM错误

```python
def _is_oom_error(msg: str) -> bool:
    lowered = (msg or "").lower()
    return any(
        k in lowered
        for k in [
            "out of memory",
            "cuda error",
            "ggml-cuda",
            "cublas",
            "vram",
            "memory allocation",
        ]
    )
```

### CUDA后端错误

```python
def _is_cuda_backend_error(msg: str) -> bool:
    lowered = (msg or "").lower()
    return any(
        k in lowered
        for k in [
            "ggml-cuda",
            "cuda error",
            "cublas",
            "hip error",
            "illegal memory access",
        ]
    )
```
