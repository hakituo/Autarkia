# 模块层（LLM / 视觉 / 语音 / 文本模型 / 图像生成）

> 本文同步自项目内部技术参考，仅描述公开可见的实现。
> 由 `scripts/doc_records/sync_tech_docs.py` 生成，请勿直接编辑；修改请改真源后重新生成。
> 文档入口：[技术参考目录](README.md)

---

## 4. 模块层技术详解

## 4.1 LLM模块

**文件**: `core/modules/llm/module.py`

**模块职责拆分**:

| 模块          | 文件                                 | 职责                            |
| ----------- | ---------------------------------- | ----------------------------- |
| OpenAI兼容客户端 | `openai_compat/client.py`          | 编排层：payload 构造→重试→错误判定→解析/转发     |
| Aveline客户端  | `openai_compat/aveline_client.py`  | Aveline专用配置                   |
| DeepSeek客户端 | `openai_compat/deepseek_client.py` | DeepSeek专用配置                  |
| MiniMax客户端  | `openai_compat/minimax_client.py`  | MiniMax专用配置                   |
| Ark客户端      | `openai_compat/ark_client.py`      | 火山方舟专用配置                      |
| 智谱AI客户端    | `openai_compat/zhipu_client.py`    | 智谱AI专用配置(思考模式/联网搜索/视觉模型)     |
| API监控       | `openai_compat/api_monitor.py`     | API调用计数、调用栈追踪、日志记录            |
| 消息工具        | `openai_compat/message_utils.py`   | 消息规范化、角色映射、Payload构建          |
| 错误处理        | `openai_compat/error_handling.py`  | 网络错误分类、瞬时错误判断、非200响应判定（是否重试/重建payload） |
| 重试策略        | `openai_compat/retry.py`           | 重试次数与退避，chat/stream_chat 共用          |
| 会话管理        | `openai_compat/session_mixin.py`   | 常驻/临时 session，动态 api_key 走临时 session  |
| DSML流式兜底    | `openai_compat/dsml_stream.py`     | 跨 chunk 缓冲 DSML token 并解析成 tool_calls  |
| 调用来源        | `openai_compat/caller_source.py`   | 从调用栈提取业务层函数名（缓存日志定位来源）        |
| 缓存标记        | `openai_compat/cache_markers.py`   | 按provider注入cache_control断点与OpenRouter session_id |
| 流式解析器       | `openai_compat/stream_parser.py`   | SSE流式响应解析、content/reasoning提取 |

**双模式架构**:

```python
class LLMModule:
    def __init__(self, config: Dict):
        self.backend = config.get("backend", "gguf")
        self.model = None
        self.device = config.get("device", "cuda")

    async def load_model(self) -> None:
        """加载模型"""
        if self.backend == "gguf":
            from .gguf_backend import GGUFBackend
            self.model = GGUFBackend(self.config)
        elif self.backend == "transformers":
            from .transformers_backend import TransformersBackend
            self.model = TransformersBackend(self.config)
        elif self.backend == "cloud":
            from .cloud_backends import CloudBackend
            self.model = CloudBackend(self.config)

    async def generate(self, prompt: str, **kwargs) -> str:
        """同步生成"""

    async def stream_generate(self, prompt: str, **kwargs) -> AsyncGenerator:
        """流式生成"""
```

**GGUF后端配置**:

```python
GGUFConfig = {
    "model_path": "models/qwen-7b.gguf",
    "n_gpu_layers": 35,
    "n_ctx": 4096,
    "n_batch": 512,
    "f16_kv": True,
}
```

**云端后端配置**:

```python
CloudConfig = {
    "provider": "siliconflow",  # openai, dashscope, deepseek
    "api_key": "xxx",
    "model": "Qwen/Qwen2.5-7B-Instruct",
    "base_url": "https://api.siliconflow.cn/v1",
}
```

## 4.2 视觉模块

**文件**: `core/modules/vision/module.py`

**支持模型**:

| 模型          | 类型 | 说明               |
| ----------- | -- | ---------------- |
| Qwen-VL     | 本地 | 通义视觉语言模型         |
| Qwen2-VL    | 本地 | 通义视觉语言模型v2       |
| SiliconFlow | 云端 | SiliconFlow视觉API |

**关键方法**:

```python
class VisionModule:
    async def describe_image(self, image_path: str, prompt: str) -> str:
        """图像描述"""

    async def analyze_image(self, image_path: str, questions: List[str]) -> Dict:
        """图像分析"""

    async def ocr(self, image_path: str) -> str:
        """文字识别"""
```

## 4.3 语音模块

**文件**: `core/voice/tts_engine.py`、`core/voice/cloud_tts_helpers.py`

**TTS引擎路由**:

```python
class TTSEngine:
    def __init__(self, config: Dict):
        self.engines = {
            "qwen3_tts": Qwen3TTS(config),
            "gpt_sovits": GPTSoVITS(config),
            "cloud": CloudTTS(config),
        }
        self.current_engine = config.get("engine", "qwen3_tts")

    async def synthesize(self, text: str, **kwargs) -> bytes:
        """语音合成"""
        engine = self.engines[self.current_engine]
        try:
            return await engine.synthesize(text, **kwargs)
        except Exception:
            # 回退到下一个引擎
            for name, engine in self.engines.items():
                if name != self.current_engine:
                    return await engine.synthesize(text, **kwargs)
```

**TTS配置**:

```python
TTSConfig = {
    "engine": "qwen3_tts",
    "sample_rate": 24000,
    "reference_audio": "reference.wav",
    "speed": 1.0,
    "pitch": 1.0,
}
```

**当前职责拆分**:

- `tts_engine.py`
  - 引擎路由
  - GPT-SoVITS / Qwen3TTS / CloudTTS 总入口
  - 设备迁移与资源管理对接
- `cloud_tts_helpers.py`
  - Cloud TTS 会话复用
  - HTTP 请求构造与发送
  - Cloud TTS 关闭清理
- `multimodal/tts_manager.py`（TTSCacheManager）
  - LRU 缓存层 + 请求去重
  - 同步/异步双 API（`text_to_speech` / `async_text_to_speech`）
  - 线程安全后台事件循环（`_init_lock` 独立锁）
  - Future 超时机制（`_wait_for_inflight_async`）
  - 磁盘空间监控与配额驱逐
  - 文本规范化提升缓存命中率
  - 结构化异常（`TTSError` → `TTSInitializationError` / `TTSSynthesisError` / `TTSTimeoutError` / `TTSDiskSpaceError`）
  - `TTSCacheConfig` 可配置参数（7项）
  - `health_check()` 健康检查端点
  - `shutdown()` 优雅关闭

**客户端直连云端 TTS（2026-10-17）**:

- `GET /api/v1/media/tts/direct-config`（`routers/v1/media_tts_client.py`）向已鉴权客户端下发云端 TTS 凭据与音色映射：火山 provider 带 appid/api_key/resource_id/cluster/voice_map/key_map/aliases，OpenAI 兼容 provider 带 base_url/api_key/model；本地 provider 返回 `enabled=false`，配置 `voice.tts.client_direct=false` 可整体关闭。该端点只服务 Android App；QQ（`clients/bots/qq/voice_service.py`）与 Telegram（`clients/bots/telegram/media_sender.py`）仍固定请求后端 `POST /api/v1/media/tts`。
- Android `TTSEngine` 先调用 `CloudTtsSynthesizer` 直连云端（火山 `x-api-key` + `X-Api-Resource-Id`；OpenAI 兼容 `/v1/audio/speech`），失败或未启用时回退 `POST /api/v1/media/tts`；文本清洗由 `TtsTextSanitizer` 复刻 `TextProcessor` 的媒体标签 / 括号 / 参数标记语义。
- 聊天媒体由 Android `LocalMediaStore` 本地优先保存（`filesDir/chat_media`，缓存 key 只取 URL path，与后端地址无关），WS/SSE 收到图片/视频即预取，换后端后历史媒体仍可显示。

## 4.4 文本模型适配模块（已下线）

原 text_model_adapter.py 与两个 text_adapter_* 辅助文件已删除，适配职责一分为二：

- 本地推理（Transformers / llama.cpp）→ `core/modules/llm/`
- 远端后端（ollama / vllm / dashscope / 云 API）→ `core/llm/openai_compat/`

统一入口是 `core/modules/llm/module.py`；新代码不要再引用旧适配层。

## 4.5 图像生成模块

**文件**: `core/image/image_manager.py`、`core/image/forge_runtime.py`

**多后端支持**:

```python
class ImageManager:
    def __init__(self, config: Dict):
        self.backends = {
            "forge": ForgeClient(config),
            "siliconflow": SiliconFlowClient(config),
            "comfy": ComfyClient(config),
        }
        self.current_backend = config.get("backend", "forge")

    async def generate(self, prompt: str, **kwargs) -> str:
        """生成图像"""

    async def img2img(self, image: str, prompt: str, **kwargs) -> str:
        """图像到图像"""

    async def get_available_models(self) -> List[str]:
        """获取可用模型"""
```

**当前职责拆分**:

- `image_manager.py`
  - provider 路由
  - 图像任务前后的资源协调
  - Forge / ComfyUI / SiliconFlow 统一业务入口
- `forge_runtime.py`
  - Forge 进程拉起
  - 就绪检查
  - 预热
  - 进程终止与回收
