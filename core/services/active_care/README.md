# Active Care Service (主动关怀服务)

## 概述

主动关怀服务是 Autarkia 的智能交互核心，负责在用户无主动操作时，根据时间、用户状态、情绪等因素主动发起关怀交互。该服务采用模块化设计，支持多模式决策、硬件联动、词汇学习等功能。

> 本文是入口索引，实现细节在 [docs/](docs/) 下按主题拆分。
> 改代码前先在 `.trae/context/routing/active-care.md` 定位到具体文件。

---

## 子文档导航

| 主题 | 文档 | 内容 |
| --- | --- | --- |
| 核心组件 | [docs/components.md](docs/components.md) | 服务主类、检查器、决策引擎、执行器 |
| 四层改造与 Prompt | [docs/pipeline.md](docs/pipeline.md) | 决策 / 生成 / 频控 / 发送四层，Prompt V2 与人设联动 |
| 运行时状态 | [docs/runtime.md](docs/runtime.md) | 上下文管理、调度逻辑、词汇学习、模式状态 |
| 子目录拆分 | [docs/submodules.md](docs/submodules.md) | 每个子目录放什么、职责边界 |
| 架构设计 | [docs/architecture.md](docs/architecture.md) | 睡眠事实与室友共享边界、词汇任务事实边界、工作流程 |
| 使用示例 | [docs/usage.md](docs/usage.md) | 启动服务、手动触发、更新奖励、设置模式 |
| 配置 | [docs/config.md](docs/config.md) | 服务配置、时间段、动作权重 |
| 硬件联动 | [docs/hardware.md](docs/hardware.md) | 震动控制、呼吸灯控制 |
| 性能特性 | [docs/performance.md](docs/performance.md) | 响应时间、资源占用 |

---

## 子目录

`active_care/` 按职责分层，逐个目录的说明见 [docs/submodules.md](docs/submodules.md)：

```
core/        核心编排与服务入口
decision/    决策引擎与执行
detection/   检测与识别
postprocess/ 后处理管线
peer_chat/   同伴对话
prompt/      提示词构建
scheduling/  调度与时间管理
storage/     存储与持久化
checker/     检查器子模块
shared/      共享常量与工具
state/       统一状态管理
```

> `cadence/` 目前在磁盘上存在，但 `docs/submodules.md` 的子目录说明里尚未登记，待补。

---

## 相关文档

- [主动关怀技术细节](../../../.trae/context/tech/services/active-care.md)
- [系统架构文档](../../../PROJECT_TECHNICAL_REFERENCE.md)
- [服务层文档](../README.md)
- [核心层文档](../../README.md)
- [模式设计文档](./ACTIVE_CARE_MODE_DESIGN_2026-03-08.md)

---

## 维护约定

1. **细节写 `docs/`，不写回本文件**；新增主题就在上表加一行并建文件。
2. **只写当前实现**：变更史进 `docs/updates/`，README 里不保留「2026-xx-xx 改造」这类流水。
3. **子目录职责表**：新增/删除子目录时同步改 `docs/submodules.md` 与本文件的两处列表。
