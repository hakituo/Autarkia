# Scheduler Service (调度服务)

## 概述

调度服务是 Autarkia 的任务调度核心，负责 GPU/CPU 任务的统一调度、资源管理、优先级队列等功能。该服务集成了 C++ 高性能调度引擎，支持生物学状态驱动的智能调度。

> 本文是入口索引，实现细节在 [docs/](docs/) 下按主题拆分。
> 改代码前先在 `.trae/context/routing/scheduler.md` 定位到具体文件。

---

## 子文档导航

| 主题 | 文档 | 内容 |
| --- | --- | --- |
| 核心组件 | [docs/components.md](docs/components.md) | GlobalTaskScheduler、CPPSchedulerEngine、生物状态、GPU 资源、模型管理 |
| 架构设计 | [docs/architecture.md](docs/architecture.md) | 调度流程与 C++ 调度引擎架构 |
| 使用示例 | [docs/usage.md](docs/usage.md) | 提交 / 查询 / 取消任务，C++ 引擎调用 |
| 配置 | [docs/config.md](docs/config.md) | 启动配置、LLM 后端、Worker 与 GPU 配置 |
| 性能特性 | [docs/performance.md](docs/performance.md) | 吞吐量、延迟、资源利用率 |
| 错误处理 | [docs/errors.md](docs/errors.md) | OOM 错误、CUDA 后端错误 |

---

## 子目录

服务已从扁平结构重构为按职责分层的子目录，顶层只保留主引擎（`cpp_scheduler_engine.py`）与 C++ 扩展绑定层（`scheduler_wrapper.py`）：

```
bio/        生物系统（神经递质、能量、睡眠债务等状态）
client/     C++ 调度器 HTTP 客户端与配置构建
inference/  推理执行（C++ / Python 双后端、统计、工具）
lifecycle/  调度器生命周期管理与健康检查
model/      LLM 模型与 GPU 资源管理
task/       任务调度核心（调度器、适配器、异步包装器）
utils/      通用工具（断路器、错误处理、KV Cache、显存监控、资源工具、启动配置）
```

> `lib/` 目前在磁盘上存在，但尚未在上述分层说明中登记，待补。

重构未改变对外 API 与导入路径（通过 `__init__.py` 重新导出），只调整内部组织结构。

---

## 相关文档

- [调度系统技术细节](../../../.trae/context/tech/scheduler.md)
- [系统架构文档](../../../PROJECT_TECHNICAL_REFERENCE.md)
- [服务层文档](../README.md)
- [核心层文档](../../README.md)
- [C++ 调度器文档](../../../cpp_modules/cpp_scheduler/README.md)

---

## 维护约定

1. **细节写 `docs/`，不写回本文件**；新增主题就在上表加一行并建文件。
2. **只写当前实现**：重构史进 `docs/updates/`，不在 README 里保留「重构前 / 重构后」对比。
3. **子目录职责表**：新增或删除子目录时，同步改本文件的列表。
