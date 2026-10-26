# 四层改造与 Prompt 联动

> Active Care 子文档 · 上级入口：[README.md](../README.md)
> 只写当前实现；变更史进 `docs/updates/`。

---

### 2026-09-04 四层改造：决策 / 生成 / 频控 / 发送

一句话概括：**把 Active Care 从"定时让 LLM 写一条消息"改成"定时让 LLM 判断有没有必要说一句话"**。
解决三个问题：不该发时硬发、发得太频繁、每条写得太满。

**决策层（要不要发）**：send/defer 双出口。
- 值得联系 → `send_active_care(text)`；不值得 → `defer_active_care(reason, retry_after_minutes)`。
- `reason` 只进日志，永远不进用户消息链路；支持工具调用的模型走 function calling，
  不支持的模型走 JSON `action` 字段，统一归一化到 `decision/action_protocol.py`。
- 决策 prompt 新增约束："大多数检查轮次不发送是正常结果"、"禁止把'先不发了/等他回复'
  等决策过程写成消息"。LLM 空响应兜底改为默认 defer（不再 conversation_incomplete 强制补发）。

**生成层（写多短）**：短 poke 约束。
- 主动消息默认一句话、6~20 汉字，禁止"话说/对了/刚好/刚看到"等无意义转场和
  "我在做X→想到你→再问Y"铺垫三段式，附正反例（prompt 见 `active_care_prompts.py` 的
  `PROACTIVE_SHORT_POKE_RULES`）。允许直接问，不鼓励用假生活铺垫弱化"查岗感"。

**频控层（多久一次）**：`cadence/` 多层频控，决策前预检（省 LLM 调用）+ 决策后带话题复检。
- 全局冷却 40min、提问冷却 75min、同题材冷却 3h（topic_group 把吃饭/外卖归入 meal，
  防换措辞绕过冷却）、未回复抑制（最多悬 1 条普通提问，用户回消息自动解除）、
  每日好奇提问软上限 3 条。
- 硬事件类 intent（真实提醒/通知/数字健康/早安晚安等）全部豁免——"特殊新事件允许突破"。

**发送层（硬 Gate）**：`postprocess/send_validator.py` + 管线 `PokeStyleGuardStep`。
- 拦截内部控制标记（`[GOODNIGHT_GUARD]` 等）/决策过程表述/prompt 泄漏 → 直接 DROP；
  超长或铺垫结构 → 先压缩一次，仍不合规 → DROP。

状态追踪：发送时持久化 `last_proactive_at/type/topic/topic_group/replied`，
用户回复时置 `last_proactive_replied=True`（`user_response_handler`）。
验证入口：`tests/unit/test_active_care_poke_gate.py`。

### Prompt V2 与主人设联动

Active Care 不再单独拼一份旧人设，而是通过
`PersonaPromptLayers` / `get_persona_prompt_layers()` 与主对话共享人物投影：

1. system 保留主人设静态层、主动关怀固定约束、风格约束和 voice guide，形成稳定缓存前缀。
2. dynamic prompt 依次放入人物动态层、场景事实、最近历史和本轮触发任务；语气样例与日期事件也属于每轮动态内容。
3. 叶使用 Persona 2.0 的 overlay/runtime/knowledge/memory 动态层；其他角色继续回退原有人设模板。
4. “是否发送”决策只读取角色名与稳定 scope 的轻量身份投影，完整人设只用于生成消息。
5. 主人设运行时交互模式同时参与主动消息门控，防止角色当前上下文被无关主动话题打断。

任务型少样本由角色自己的 Prompt 配置持有：Aveline/Ling使用各自 `core_*.json`
的 `active_care` 段，Ye使用 Persona 2.0 的 `ye/voice_ye.json`。组装器按稳定
scope 和当前任务类型只选择本轮示例；示例只提供关系动作、语气和节奏，不提供当前
事实，也不会回退到其他角色。`good_morning_proactive` 不再把旧主动消息原文作为
最近历史或去重锚点，避免低质量问候在后续日期形成自我强化。数字健康硬事件
（`usage_limit_exceeded`）不做发送前文案纠偏：模型输出原样发送。原先的
「拼应用名前缀 / 防声称强退」兜底会产出「哔哩哔哩：B站快两小时了」这类系统通知式
文案，与角色口吻冲突，已连同其别名配置 `config/digital_wellbeing_app_aliases.json`
一并删除；禁声称强退的约束改由 prompt 承担。

验证入口：`tests/scripts/active_care/verify_active_care_prompt_v2.py`、
`tests/scripts/active_care/verify_role_specific_wakeup_examples.py`；后者可加 `--live`
执行不发送、不写聊天历史的生产模型生成对比。

### 4.1 QQConnectionResolver (QQ 连接解析器)

**文件**: `core/qq_connection_resolver.py`

统一解析 Active Care 可投递的 QQ 连接，按以下顺序兜底：

1. NapCat `QQAdapter` 活跃实例注册表
2. QQ 官方机器人 `QQOfficialAdapter` 活跃实例注册表
3. `clients/bots/multi_qq_config.json` 多 QQ 跨进程配置
4. WebSocket 连接扫描（单 QQ 兼容）

该模块让 `executor.py` 不再直接耦合不同客户端适配器的发现细节。QQ
目标解析必须同时保留两类 ID：`shared__persona__{role}` 用于历史与人格上下文，
`private_{master_qq_id}` 用于 WebSocket 广播和离线队列。双 QQ 实时广播与离线
重放再按 `client_id=qq_{role_id}_{session_id}` 选择目标角色，不能由其他角色连接
代收后忽略。

### 4.2 ActiveCareResponseGenerator (响应生成器)

**文件**: `core/response_generator.py`

集中处理 Active Care 主动消息生成：

1. 解析 Active Care 内容模型路径
2. 读取生成温度与 max tokens 配置
3. 调用 LLM 并处理 45 秒主模型超时
4. 对 fallback 模型执行重试
5. 剥离 `<arg_key>` / reasoning 输出并拦截提示词泄漏

该模块让 `executor.py` 不再直接管理模型调用、reasoning 泄漏与 fallback 细节。

### 4.3 ActiveCareHardwareIntentResolver (硬件意图策略)

**文件**: `core/hardware_intent.py`

集中维护主动关怀类型到震动、灯效、优先级的映射。执行器保留
`determine_hardware_intent()` 兼容入口，但实际策略由该模块负责。
