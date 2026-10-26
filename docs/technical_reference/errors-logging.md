# 错误处理与日志系统

> 本文同步自项目内部技术参考，仅描述公开可见的实现。
> 由 `scripts/doc_records/sync_tech_docs.py` 生成，请勿直接编辑；修改请改真源后重新生成。
> 文档入口：[技术参考目录](README.md)

---

## 11. 错误处理与日志系统

## 11.1 异常定义

**文件**: `core/exceptions.py`

```python
class AutarkiaError(Exception):
    """基础异常类"""
    def __init__(self, message: str, code: str = "UNKNOWN_ERROR"):
        self.message = message
        self.code = code
        super().__init__(self.message)

class ModelNotFoundError(AutarkiaError):
    """模型未找到"""
    def __init__(self, model_id: str):
        super().__init__(f"Model not found: {model_id}", "MODEL_NOT_FOUND")

class ResourceExhaustedError(AutarkiaError):
    """资源耗尽"""
    def __init__(self, resource: str, required: int, available: int):
        super().__init__(
            f"Resource exhausted: {resource} (required: {required}, available: {available})",
            "RESOURCE_EXHAUSTED"
        )

class OOMError(AutarkiaError):
    """内存不足"""
    def __init__(self, details: str):
        super().__init__(f"Out of memory: {details}", "OOM_ERROR")
```

## 11.2 日志系统

**文件**: `core/utils/logger.py`（主日志系统）。旧模块 log_config.py 已删除，兼容逻辑并入 logger.py。

```python
# 推荐使用方式
from core.utils.logger import get_logger

logger = get_logger(__name__)
logger.info("消息内容")

# 带上下文的日志
logger.info("操作完成", extra={"context": {"user_id": "123", "action": "login"}})
```

**日志系统特性**:
- 异步日志支持（QueueHandler + QueueListener）
- colorama 颜色支持（Windows 兼容）
- 日志脱敏（log_sanitizer）
- AutoHeal 集成（ERROR+ 级别自动转发给异常检测器）
- 模块级日志文件
- 按日期自动分目录

**当日日志导航与板块分流**:

- `logs/YYYY/M/D/README.md`：查看顺序和板块说明。
- `important.log`：仅保留 WARNING+ 以及收发消息、健康起床、服务启停等关键事件。
- `sections/01_active_care.log` ~ `sections/07_other.log`：每条日志按 logger
  名称只进入一个功能板块。
- `autarkia_main.log`：保留完整聚合流，用于跨板块时序追踪，不作为日常首要排查入口。

**独立 debug 调试日志（统一归口 `logs/` 目录，受 `config/debug_config.py` 开关控制，全部默认关闭）**:

| 日志文件 | 开关 | 用途 |
|---------|------|------|
| `logs/active_care_debug.log` | `active_care_ws` | WebSocket 实时晚安/唤醒意图检测过程 |
| `logs/ws_handshake_debug.log` | `websocket_handshake` | WebSocket 握手诊断（403/连接失败定位，5MB 轮转） |
| `logs/api_calls_simple.log` | `api_call_log` | LLM API 调用记录 |
| `logs/server_debug.log` | `server_debug` | 桌面端 FastAPI server 进程调试（pywebview） |

> 约定：`debug_config.py` 集中管理所有独立 debug 日志开关，开启方式为 YAML（`config/yaml/app.yaml` 的 `debug:` 段）或环境变量 `XIAOYOU_DEBUG__<开关名>=true`。关闭时对应日志零写入，避免根目录/无控落盘堆积。

## 11.3 原子文件 I/O

**文件**: `core/utils/atomic_io.py`

```python
# 同步版本
from core.utils.atomic_io import safe_json_dump, safe_json_load

safe_json_dump(data, "path/to/file.json")
data = safe_json_load("path/to/file.json", default={})

# 异步版本
from core.utils.atomic_io import async_safe_json_dump, async_safe_json_load

await async_safe_json_dump(data, "path/to/file.json")
data = await async_safe_json_load("path/to/file.json", default={})

# 启用 fsync 保证数据持久化
safe_json_dump(data, "path/to/file.json", use_fsync=True)
```

**原子写入特性**:
- 线程+进程安全的临时文件命名（追加 uuid 保证协程间唯一）
- 指数退避重试（覆盖 Windows 杀毒软件/索引器锁）
- 可选 fsync 支持
- Windows 错误码检测（winerror 5/32）
- 同步/异步双版本
- **陈旧临时文件自动清理**：每次写入前清理同前缀、修改时间超过 5 分钟的 `.tmp_*` 残留（防止进程崩溃时临时文件泄漏）

**Conversation ID → Scope 解析**:
- `core/utils/data/data_paths.py::resolve_data_scope_from_conversation_id` 负责从 conversation_id 解析数据 scope
- 支持 5 种格式：`__scope__`、`peer_*`、`__persona__`/`__circle__`、default 系列、其他兜底
- 支持 `core_ling`/`core_aveline`/`ling`/`qilai` 等 persona slug 映射
