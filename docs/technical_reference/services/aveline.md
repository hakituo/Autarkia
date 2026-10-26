# AvelineService（对话服务）

> 本文同步自项目内部技术参考，仅描述公开可见的实现。
> 由 `scripts/doc_records/sync_tech_docs.py` 生成，请勿直接编辑；修改请改真源后重新生成。
> 文档入口：[技术参考目录](../README.md)

---

## 3.1 AvelineService

**文件**: `core/services/aveline/service.py`

**职责**: 对话主编排服务

**关键方法**:

```python
class AvelineService:
    def __init__(self):
        self.chat_agent: ChatAgent = None
        self.memory_manager: WeightedMemoryManager = None
        self.emotion_manager: EmotionManager = None
        self._ling_social_state: OrderedDict[str, Dict[str, Any]] = OrderedDict()  # LRU缓存，最大128条
        self._ling_social_state_max_size = 128

    async def _prepare_conversation_context(
        self, *, user_input, conversation_id, system_prompt,
        length_preference, profile_filename, is_stream=True
    ) -> Tuple[Dict, Dict, Optional[str]]:
        """公共上下文准备：角色配置加载、双角色运行时解析、社交状态更新、
        系统提示词构建（动态上下文+双角色+仿生状态+身份守卫）"""

    async def chat(self, message: str, context: Dict) -> AsyncGenerator:
        """处理对话消息"""
        # 1. _prepare_conversation_context（公共上下文准备）
        # 2. 意图识别
        # 3. 记忆检索
        # 4. 情绪更新
        # 5. LLM调用
        # 6. 记忆写入
        # 7. 流式返回

    async def stream_chat(self, message: str, context: Dict) -> AsyncGenerator:
        """流式对话"""
```

**子模块架构**:

| 文件 | 职责 |
|------|------|
| `service.py` | 主服务类，对话生成、主动消息分发、视觉分析 |
| `stream_orchestrator.py` | 流式对话事件编排、缓存、去重、TTFT追踪 |
| `command_handler.py` | 系统命令处理（/clear, /mode, /care 等） |
| `control_intent.py` | 自然语言控制意图识别（BERT + 关键词） |
| `mode_control.py` | 模式切换（隐私、学习、普通） |
| `prompt_policy.py` | 系统提示词构建策略 |
| `response_postprocess.py` | 响应后处理链（情绪→重写→媒体→日计划） |
| `response_media.py` | 自动媒体富化（图片生成、TTS） |
| `dual_role/` | 双角色协调子系统 |

**主对话 Prompt / 工具预算**:

- Ling普通人设的性格细节使用 `personality.traits[].behaviors`，日常规则使用 `language_style.syntax_constraints`，回应策略使用 `interaction_logic.response_strategy`；这些是现有详细人设组装器实际读取的字段。原始聊天统计归档到 `meta.style_calibration`，分别计算整轮和单气泡，不把统计数字当输出限制。关系增量配置的普通聊天继承同一基础风格，不固定只接最后一句；学校与工作状态仍由原有带日期字段管理。本机验证入口为 `tests/scripts/personas/verify_ling_contextual_style.py`，匿名生成仅提取普通聊天规则，不代表完整角色或真实会话验收。

- Aveline 的语言规则使用 `core/character/configs/core_aveline.json` 的 `language_style.syntax_constraints`，由 `build_detailed_persona()` 投影；不要放进当前不读取的 `language_style.principles`。回复尺度由最近几轮的任务、当前信息缺口、局部追问和收尾信号决定；普通接话通常几个字，展开不依赖详细等显式关键词，不绑定固定字数。`tests/scripts/personas/verify_aveline_short_chat.py` 校验全部规则进入 QQ 提示词；可选 `--live` 串行生成只写本机报告，不分发消息；`--synthetic-only` 仅发送通用规则和虚构场景，禁止搭配历史或人设基线，不等同于真实人设评估。已运行进程保留人设缓存，文件修改需重新加载人设后生效。

- 叶（`meta.scope=ye`）在 `prompt/ye_layered_prompt.py` 走独立 Persona 2.0 链路：静态层为 conversation policy → core → voice；动态层为显式 private overlay → 非空 runtime state → 关键词命中的最小 knowledge / memory 集合。旧根目录单文件已删除，`core_ye.json` 与 `qq/Ye_QQ_Master.json` 保留为入口标识。`PersonaManager` 在统一的 `core/character/configs/` 下发现 `<scope>/core_<scope>.json`，从身份字段生成显示名，并让列表、按 filename 加载和切换共用分层入口；别名由入口的 `meta.aliases` 声明，不复制旧人设正文。角色源资料位于 `configs/ye/`；状态与分层记忆分别位于 `companion_data/ye_data/runtime/` 和 `companion_data/ye_data/memories/persona_v2/`，状态读取与写回共用配置路径。QQ `/人设` 的当前标记与切换判断优先读取会话 prefs，账号初始 persona 仅作默认值。回归脚本：`tests/scripts/personas/verify_qq_v2_persona_switch.py`。
- 叶的 private overlay 只由 `runtime/current_state.json` 中 `ongoing_interaction.mode=private` 激活；称呼“主人”本身不触发。当前状态问题跳过稳定外貌/日常知识，防止用人物习惯伪造此刻事实。私密覆盖层、当前状态与运行时记忆按本机私有数据处理。
- `data_ops/ye_runtime_state.py` 是 `scope=ye` 的兼容与持久化门面；文档结构、规则提取、UIE、候选合并和期限清理集中在 `data_ops/ye_runtime/`。对话历史成功保存后执行状态压缩并原子写回叶的 `runtime/current_state.json`；UIE 不可用或未命中时不阻断回复。
- `BaseTool.category` 保持为人设权限边界；`tool_metadata.py` 独立维护发现领域、动作标签、风险等级、加载策略与短摘要，注册表完整性由验证脚本约束。
- `context_persona.py::select_message_tools()` 按消息领域选择本轮常用工具；常驻、按需范围和路由由 `config/tool_profiles.json` 决定。叶常驻 `search_tools` 与 `update_character_state`，Aveline/Ling常驻 `search_tools` 与 `message_peer`，其他角色继承通用基线；时间、计算、TTS与联网搜索按需。
- 关键词路由未命中时，模型调用常驻的小型 `search_tools`；检索范围先经过当前 persona / mode / sensitive 可见性过滤，工具结果只在下一模型轮次追加命中的 3–5 个 schema。
- `StreamPreparation.active_tools` 在预处理阶段只计算一次，并同时传给 prompt 装配与 `prepare_native_tools()`；非流式路径复用相同选择逻辑。
- 云模型不在 `assembler.py` 文本中重复工具清单，工具定义只通过原生 function schema 发送；本地模型保留精简文本说明。
- `model_resolution.py` 记录每轮工具数量与 schema 字符数；回归脚本为 `tests/scripts/prompt/verify_prompt_tool_schema_budget.py` 与 `tests/scripts/prompt/verify_tool_discovery_metadata.py`。
- 叶分层链路回归脚本为 `tests/scripts/personas/verify_ye_layered_prompt.py`；状态写回与真实 UIE 验证为 `tests/scripts/personas/verify_ye_runtime_state_writeback.py [--live-uie]`。
- 主对话与 Active Care 统一通过 `PersonaPromptLayers` / `get_persona_prompt_layers()` 读取主人设投影。Active Care 的 system 只保留主人设静态层和稳定关怀约束；人物动态层、语气样例、日期事件、实时状态、最近历史与本轮任务按“角色此刻状态 → 场景事实 → 历史 → 任务”进入 dynamic prompt。任务少样本由各角色 Prompt 的 `active_care` 段持有并按当前任务读取。主对话通过 `components/character_daily_context.py` 按 persona scope 只读 Character Daily 当前活动与当前时段已落盘的 ActivityInstance，动态注入为角色自身状态；只读、不生成，无计划时不注入，也不要求每轮报备。
- 角色卡前置层由 `prompt/fixed_prefix.py` 与 `prompt/sensitive_prefix.py` 统一维护。全局固定正文允许为空；分级正文保存在 Git 忽略的本机文件中，只按权威角色画像或配置目录选择，Ye明确启用。主对话在模板清理后按“全局固定层 → 分级层 → 角色卡”组装，Active Care 复用同一选择器并跳过空 section。文本按文件版本缓存，同版本前缀重复输入时只保留一份；动态状态与模式变化不改变选择结果。验证脚本：`tests/scripts/prompt/verify_fixed_prefix.py`、`tests/scripts/prompt/verify_sensitive_prefix.py`。
- 分类表情包说明与分级前缀分开选择：正文唯一入口是 `prompt/sensitive_meme.txt`（含 `{categories}` 占位符，缺失或空正文回退内置模板），分类仍动态扫描 `data/memes/manual/variants/`，由 `qq_integration.apply_qq_optimizations()` 在平台优化阶段追加。加载范围由 `sensitive_prefix.is_sensitive_media_persona()` 判定：`variants/` 目录、画像 `sensitive` 标记或画像 `sensitive_media` 标记任一成立。Ling基础人设 `core_ling.json` 通过 `sensitive_media=True` 生效，因此她不会像分级前缀那样常驻成人前缀，却能发分类表情包。验证脚本：`tests/scripts/qq/verify_sensitive_meme_prompt.py`。
- 媒体能力注入（`[MEME]`、分类、`[IMG]`/`[BM]`、`[FACE]` 收藏表情）只看人设、所有端一致，不按 cid 前缀判断：端形态包含 QQ 的 `private_*`/`group_*`、安卓的 `web_role_*`/`web_*`、客户端共享的 `shared__persona__*` 与兜底 `default`，按前缀判断会漏端（Ye走 `web_role_*` 时整段能力说明注入不到）。`apply_qq_optimizations()` 只把 QQ 专属的气泡 `[DELAY]` 说明与长描写裁剪留在 QQ 源；标签由 core 统一解析剥离，平台不支持某类图仅表现为收不到该图。

  `[FACE:名字]` 是收藏表情通道：`clients/bots/qq/custom_face.py` 按 `config/yaml/qq_custom_faces.yaml` 的 summary 在 `fetch_custom_face_detail` 里匹配，拿 md5/epId/resId 拼 mface；只有 QQ 适配器真正发送，安卓/Web 端只剥离标签。角色清单由配置的 `roles` 决定（当前仅 TT 的 `wow`）。验证脚本：`tests/scripts/qq/verify_custom_face.py`、`tests/scripts/qq/verify_meme_llm_trigger.py`。
- Active Care 发送决策只使用角色名与稳定 scope 的轻量身份投影，完整人设只进入内容生成阶段；主人设运行时交互模式复用于主动消息门控。回归脚本为 `tests/scripts/active_care/verify_active_care_prompt_v2.py`。

**依赖服务**:

- ChatAgent: 聊天代理
- WeightedMemoryManager: 记忆管理
- EmotionManager: 情绪管理
- SchedulerService: 任务调度
- ActiveCareStorage: 主动关怀状态（通过 `get_last_thought()` 异步 API 或 `get_last_thought_sync()` 同步 API）
