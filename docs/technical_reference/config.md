# 配置系统

> 本文同步自项目内部技术参考，仅描述公开可见的实现。
> 由 `scripts/doc_records/sync_tech_docs.py` 生成，请勿直接编辑；修改请改真源后重新生成。
> 文档入口：[技术参考目录](README.md)

---

## 10. 配置系统详解

## 10.1 配置文件结构

```
config/
├── integrated_config.py         # 配置主入口（Settings + get_settings）
├── yaml_loader.py               # YAML解析、环境变量展开、配置映射
├── model_detector.py            # 模型目录解析与自动探测
├── cache_manager.py             # 启动缓存读写、签名校验、失效重建
└── yaml/
    ├── app.yaml                 # 主配置入口（imports + 运行时总配置）
    └── sections/
        ├── modeling.yaml        # 模型本体参数
        └── model_routing.yaml   # 模型场景路由
```

## 10.2 当前配置职责划分

- `integrated_config.py`
  - 定义 `AppSettings` 与各子配置类
  - 提供 `get_settings()` / `reset_settings_cache()` / 兼容 `Config`
- `yaml_loader.py`
  - 负责 `app.yaml` 解析、imports 展开、环境变量展开与 YAML → Settings 覆盖映射
- `model_detector.py`
  - 负责本地 LLM / 图像 / 视觉 / Whisper / GPT-SoVITS 自动探测
- `cache_manager.py`
  - 负责启动缓存文件、版本号、路径签名与缓存读写

## 10.3 主配置入口

```yaml
# config/yaml/app.yaml
imports:
  - "sections/modeling.yaml"
  - "sections/model_routing.yaml"

server:
  port: 8000

chat:
  context_budget:
    # 120 条 ≈ 60 轮（user + assistant 各一条）；chars 与之配套，避免长会话先被字符闸门截断
    cloud_max_history_messages: 120
    cloud_max_history_chars: 24000
```

```yaml
# config/yaml/sections/modeling.yaml
model:
  llm:
    provider: "deepseek"
  # 仅控制 ModelManager 的模型选择注册池，不限制业务路由直接调用。
  registered_cloud_providers:
    - "deepseek"
    - "openrouter"
    - "minimax"
  # 本地模型路径与候选清单只在这里声明一次（详见 10.3.1）
  path: "models/llm/Qwen3.5-9B-Q4_K_M.gguf"
  generation:
    temperature: 1.1

```

`ModelManager` 只把 `registered_cloud_providers` 中的云端供应商加入模型选择注册池；
`model_routing.yaml` 中的视觉、回退和后台任务路由仍可按完整 `cloud:` 路径直接调用。

## 10.3.1 本地模型配置的唯一真源（2026-09-24 统一）

本地模型（文本 / 视觉 / 语音识别 / 生图底模）的路径与候选清单**只在
`config/yaml/sections/modeling.yaml` 声明一次**，其他模块一律从 `settings.model` 读取：

| 声明字段 | 含义 |
| --- | --- |
| `model.path` | 当前生效的本地文本模型（GGUF） |
| `model.whisper_path` | 本地语音识别模型目录（faster-whisper 格式） |
| `model.vision_path` | 本地视觉模型目录；留空表示视觉走云端 provider |
| `model.llm_candidates` / `image_candidates` / `vision_candidates` / `asr_candidates` | 自动探测候选，按顺序取第一个存在的 |
| `model.image_provider` / `default_image_model` / `fallback_image_model` / `image_model_aliases` | 生图后端与底模（别名为键，值为磁盘真实文件名） |

`config/model_detector.py` 只负责“按声明顺序取第一个存在的”，并把声明路径纳入启动
缓存签名；它自身不再内置任何模型名，扫描兜底时忽略 `mmproj*.gguf`，避免视觉投影文件
被误当作可独立加载的语言模型。`config/integrated_config.py` 与
`core/modules/llm/module.py` 也不再各自兜底模型名——路径为空时直接报错，而不是静默
换成别的模型。该约定由 `tests/scripts/config/verify_local_model_config.py` 守护。

## 10.3.2 环境变量约定（2026-09-24 校正）

| 类别 | 读取方式 | 例子 |
| --- | --- | --- |
| pydantic 前缀式 | 各 `settings_*.py` 的 `SettingsConfigDict(env_prefix=...)` | `XIAOYOU_VOICE_ENABLED`、`XIAOYOU_STUDY_ENABLED`、`XIAOYOU_SCHEDULER_ENABLED`；嵌套用双下划线 `XIAOYOU_DEBUG__LIFE_SIMULATION` |
| 直接读取式 | 代码里 `os.getenv` / `os.environ.get` | `QWEATHER_*`、`ASR_MODEL_PATH`、`XIAOYOU_TEXT_MODEL_PATH`、`TTS_API_BASE` |
| 多 API key | 代码遍历 `os.environ` 按前缀匹配 | `<PROVIDER>_API_KEY_<别名>`（别名转小写），如 `DEEPSEEK_API_KEY_Yeye` → 路由用 `cloud:deepseek:yeye:<model>` |

三条硬约定：

1. **无前缀的裸键一律无效**——历史上 `.env.example` 里的
   `TEXT_MODEL_PATH` / `MODEL_TYPE` / `OLLAMA_*` / `REDIS_*` / `PROXY_*` / `TTS_*` 等 29 个键
   在代码里没有任何读取点，已全部删除。
2. **不要写 `KEY=`（空值）**：python-dotenv 会把空字符串注入环境，`os.getenv("X", default)`
   拿到的是 `""` 而不是 `default`，反而覆盖代码默认值；用不到的项整行注释掉。
3. 本地模型「路径」不通过环境变量配置，<br>只声明在 `modeling.yaml`（见 10.3.1）；
   环境变量里只保留 `XIAOYOU_TEXT_MODEL_PATH` / `XIAOYOU_SD_MODEL_PATH` 两个临时覆盖口子。

约定由 `tests/scripts/config/verify_env_template.py` 守护：模板不允许出现无读取点的死键、
必需键（云端密钥 / 火山 TTS / 和风天气 / 主人 QQ 号）不得从模板消失、本机 `.env` 与模板的
漂移会给出告警。目录职责与加载链路见 `config/README.md`。

```yaml
# config/yaml/sections/model_routing.yaml
model_routing:
  default_chat_model: "cloud:deepseek:deepseek-v4-pro"
  chat_models:
    ling: "cloud:deepseek:deepseek-v4-flash"
```

## 10.4 配置类

```python
# config/integrated_config.py

from pydantic import BaseSettings

class LLMSettings(BaseSettings):
    backend: str = "cpp"
    model_path: str = "models/qwen-7b.gguf"
    n_gpu_layers: int = 35
    n_ctx: int = 4096
    temperature: float = 0.7
    max_tokens: int = 2048

class TTSSettings(BaseSettings):
    engine: str = "qwen3_tts"
    sample_rate: int = 24000
    speed: float = 1.0
    pitch: float = 1.0

class ActiveCareSettings(BaseSettings):
    enabled: bool = True
    base_interval: int = 1800
    silence_threshold: int = 2700
    max_interval: int = 7200
    min_interval: int = 600

class Settings(BaseSettings):
    llm: LLMSettings = LLMSettings()
    tts: TTSSettings = TTSSettings()
    active_care: ActiveCareSettings = ActiveCareSettings()

    class Config:
        env_file = ".env"
        env_nested_delimiter = "__"
```
