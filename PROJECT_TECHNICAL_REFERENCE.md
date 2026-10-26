# Autarkia 项目技术参考文档

**入口**: [docs/technical_reference/README.md](docs/technical_reference/README.md)

> 本文档已按主题拆分为 `docs/technical_reference/` 下的多个文件，本文件只保留入口，
> 以免旧链接失效。按主题导航请点上面的入口，或直接跳转：

| 主题 | 文档 |
| --- | --- |
| 架构速览（分层 / 技术栈 / C++ 集成） | [architecture.md](docs/technical_reference/architecture.md) |
| 核心引擎 | [core-engine.md](docs/technical_reference/core-engine.md) |
| 服务层（14 个服务族） | [services/README.md](docs/technical_reference/services/README.md) |
| 模块层 | [modules.md](docs/technical_reference/modules.md) |
| 记忆系统 | [memory.md](docs/technical_reference/memory.md) |
| 调度系统 | [scheduler.md](docs/technical_reference/scheduler.md) |
| 接口层 | [interfaces.md](docs/technical_reference/interfaces.md) |
| 客户端层 | [clients.md](docs/technical_reference/clients.md) |
| 数据流与调用链路 | [data-flow.md](docs/technical_reference/data-flow.md) |
| 配置系统 | [config.md](docs/technical_reference/config.md) |
| 错误处理与日志 | [errors-logging.md](docs/technical_reference/errors-logging.md) |
| 性能优化 | [performance.md](docs/technical_reference/performance.md) |

## 关于本文件

`docs/technical_reference/` 由 `scripts/doc_records/sync_tech_docs.py` 从内部技术参考
（`.trae/context/tech/`）生成，**不要手工编辑**；需要改内容时改真源后重新生成。

文档描述的是当前代码状态；与代码不一致时以代码为准。
