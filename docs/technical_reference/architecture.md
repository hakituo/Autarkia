# 架构速览（分层图 / 技术栈 / C++ 集成策略）

> 本文同步自项目内部技术参考，仅描述公开可见的实现。
> 由 `scripts/doc_records/sync_tech_docs.py` 生成，请勿直接编辑；修改请改真源后重新生成。
> 文档入口：[技术参考目录](README.md)

---

## 1.1 分层架构

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              Clients Layer (客户端层)                                │
│  Web (React) │ Android (Kotlin) │ iOS (Swift) │ Electron │ QQ Bot │ Telegram │ Obsidian │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                              Interface Layer (接口层)                                │
│                    HTTP REST API │ WebSocket │ OpenAI Compatible                    │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                               Core Layer (核心层)                                    │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                          Core Engine (核心引擎)                              │   │
│  │  Engine │ EventBus │ LifecycleManager │ ModelManager │ ConfigManager │ ServiceRegistry │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                         Services (服务层 - 25+ 子模块)                       │   │
│  │  Aveline │ ActiveCare │ Workspace │ Scheduler │ Immune │ AutoHeal │ CharacterDaily │   │
│  │  SelfImprovement │ DataOps │ Study │ LifeSim │ Journal │ Daily │ VTube │ ...         │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                           Agents (Agent 层)                                  │   │
│  │  ChatAgent │ PersonaSystem / Prompt                                          │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                          Modules (模块层)                                    │   │
│  │  LLM │ Vision │ Voice │ Image │ Memory                                        │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │                          Tools (工具层 - 26+ 工具)                           │   │
│  │  Study │ Daily │ Diary │ Reminder │ Status │ Food │ Search │ ...             │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  Emotion (情绪系统) │ People Profile (人物档案)                                │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                              Memory Layer (记忆层)                                   │
│              WeightedMemory │ VectorSearch │ KeywordIndex │ Distillation          │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                             Scheduler Layer (调度层)                                 │
│              C++ Scheduler │ GlobalTaskScheduler │ BioSystem                      │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                              Storage Layer (存储层)                                  │
│                    JSON Files │ ChromaDB │ SQLite │ Redis (L2)                   │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## 1.2 技术栈详情

| 层级    | 技术组件               | 版本要求    | 说明            |
| ----- | ------------------ | ------- | ------------- |
| 后端框架  | FastAPI            | 0.100+  | 异步Web框架       |
| 后端运行时 | Uvicorn            | 0.23+   | ASGI服务器       |
| LLM推理 | llama-cpp-python   | 0.2.50+ | GGUF模型推理      |
| LLM推理 | Transformers       | 4.35+   | HuggingFace模型 |
| 向量数据库 | ChromaDB           | 0.4+    | 向量存储与检索       |
| 前端框架  | React              | 18.2+   | UI框架          |
| 前端构建  | Vite               | 5.0+    | 构建工具          |
| 状态管理  | Zustand            | 5.0+    | 轻量级状态管理       |
| 移动端   | Capacitor\&jetpack | 8.0+    | 跨平台桥接         |
| 桌面端   | Electron           | 33.0+   | 桌面应用框架        |
| 调度与计算 | C++17 / Pybind11   | -       | 高性能算子与硬件调度    |

### Python 依赖与运行环境

- `venv_cpu` 是 Windows 日常默认环境，使用 CPU 版 Torch；QQ Adapter 与主程序共用该环境。
- `venv_core` 保留 CUDA 版 Torch，用于确实需要 GPU 的本地推理任务。
- Linux 对等环境：`venv_cpu/`（torch 2.13+cpu，日常默认）与 `.venv/`（uv 管理，
  torch cu130，角色等同 `venv_core`）；启动器 `start.sh` 默认 venv_cpu、
  `start_venv_core.sh` 走 .venv 并置 `XIAOYOU_START_LOCAL_LLM=1`。
- 远程访问走 Tailscale 组网（`100.64.0.0/10`）：Web 前端 3000、后端 8000 直接可达，Web 端从
  非回环地址打开时走同源 Vite 代理，后端 Origin 校验放行本机回环 / 私网 / 组网来源
  （`core/middleware/trusted_origin.py`）。Cloudflare Tunnel 已停用，代码不再硬编码相关域名；
  隧道总控留在独立仓库 `d:\AI\cloudflared`（github.com/hakituo/cloudflared），仅在需要让未装
  Tailscale 的设备访问时才回滚启用。
- `pyproject.toml` / `uv.lock` 管理项目包的直接依赖与跨平台解析；`requirements/base.txt`
  是完整 Windows 运行环境锁，CPU/GPU Torch 锁必须在其后分步安装
  （Linux 走 `requirements/cpu.txt` / `requirements/gpu.txt` 的 PyTorch 官方索引）。
- 两套环境统一使用 `tests/scripts/environment/verify_runtime_dependencies.py` 检查
  `pip check`、重复元数据、关键导入、OpenCV 所有权和 Torch 设备状态。
- SoX / FFmpeg 是部分语音链的外部原生工具，Python requirements 仅安装封装库；
  需要时应提供项目本地可执行文件并加入服务进程 `PATH`。

## 1.3 混合架构设计原则 (Hybrid Architecture)

本项目采用严格的 **"Python 做胶水与业务编排，C++ 做引擎与重度计算"** 的混合架构范式：

- **Python 负责“大脑”**：处理高变动的业务逻辑（如 Active Care 决策流）、FastAPI 路由、WebSocket 连接并发、以及大模型 Prompt 的动态组装。
- **C++ 负责“肌肉”**：通过 Pybind11 提供零内存拷贝（Zero-Copy）的 Python Binding，专门解决 Python GIL 锁导致的 CPU 瓶颈。目前 C++ 接管了以下五大核心算子（均已集成到主程序）：
  1. **调度器 (`cpp_scheduler`)**：硬件资源与任务排队。
  2. **记忆检索 (`cpp_memory_index`)**：海量记忆的 SIMD 余弦距离计算。
  3. **极速分词 (`cpp_fast_tokenizer`)**：BPE Token 估算与长文本防爆显存截断。→ 集成到 `inference_utils.py`
  4. **音频流处理 (`cpp_audio_processor`)**：毫秒级 VAD (语音活动检测) 与去静音。→ 集成到 `stt_connector.py` / `stt_engine.py`
  5. **模型推理 (`cpp_bert_engine`)**：基于 ONNX Runtime 的轻量级意图识别。→ 集成到 `bert_runtime_mixin.py`

## C++ 模块集成策略
所有C++模块均采用 **动态检测 + 优雅降级** 模式：
- 通过 `importlib.util.find_spec()` 检测模块是否可用
- 不可用时自动回退到原有Python实现
- C++模块不作为硬性依赖，保证项目在无编译环境下的可用性
