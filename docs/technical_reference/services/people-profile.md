# 人物档案与角色社交关系（People Profile）

> 本文同步自项目内部技术参考，仅描述公开可见的实现。
> 由 `scripts/doc_records/sync_tech_docs.py` 生成，请勿直接编辑；修改请改真源后重新生成。
> 文档入口：[技术参考目录](../README.md)

---

## 3.11 People Profile System（人物档案系统）

**核心文件**:

```
core/character/people/
├── models.py                  # 档案数据模型（PersonProfile/KnownFact/ProfileType/ProfileTarget）
├── manager.py                 # PeopleProfileManager 单例（加载/缓存/查询/保存）
├── extractor.py               # PeopleProfileExtractor 薄门面（增量总流程 + LLM 重试）
├── conversation_source.py     # 增量状态、原始聊天读取与轮次分批
├── signal_gate.py             # 蒸馏人物信号汇总与候选批次门控
├── external_profile_service.py # 外部 PERSON 提取、去重与持久化
├── role_update_service.py     # Aveline/Ling ROLE 演化提取
└── __init__.py                # 模块入口
```

**三层档案结构**:

| 层级 | 字段 | 用途 | 示例 |
|------|------|------|------|
| 核心层 | `core_fields` | 结构化核心字段 | `{"birth_date": "2008-05-12", "tall": "167cm"}` |
| 摘要层 | `description` | 一段话总结（注入用） | "Master是你的创造者，你是他的顶级架构师..." |
| 详细层 | `detailed` | 细颗粒度事实（工具查询用） | `{"known_facts": [{"key": "学校", "value": "XX高中"}]}` |

**三类档案**:

| 类型 | `ProfileType` | 存储位置 | 说明 |
|------|---------------|----------|------|
| 角色人设 | `ROLE` | `aveline_data/persona_data/profiles/` | Aveline_Qi / Aveline_Ling 等多版本人设 |
| 用户自身 | `SELF` | `user_data/person_profile.json` | Master的基本信息 |
| 人际关系 | `PERSON` | `user_data/people_profiles/` | Master视角下的其他人物 |

**多版本人设机制**:

同一角色面对不同人时有不同态度：
- `Aveline_Qi` → 对Master：傲娇女友
- `Aveline_Ling` → 对Ling：室友/姐姐
- `Ling_Qi` → 对Master：聊天氛围轻松
- `Ling_Aveline` → 对 Aveline：双角色系统

**注入策略（分三档）**:

| 档位 | 注入内容 | 触发时机 |
|------|----------|----------|
| 角色人设（厚） | `core_fields` + `description` | 常驻注入 |
| 用户自身（厚） | `core_fields` + `description` | 常驻注入 |
| 提及人物（薄） | 仅 `description` | 消息中提到该人物时按需注入 |

**运行时注入链路**:

```
用户消息 → build_mentioned_people_injection(message_text)
         → manager.find_mentioned_people(message_text) [alias 匹配]
         → person.get_injection_summary(thick=False) [薄注入]
         → 追加到 assembler.injection_blocks
```

**夜间提取流程**:

```
Scope Phase: task_runner.distill_memories_async()
    → resolve_distillation_perspective(manager) [按记忆归属定第一人称角色视角]
        ├── 会话 ID 写了角色（__scope__ / __persona__）→ 直接取该角色人设
        ├── 没写 → 严格注册 scope → 记忆落盘目录 <scope>_data → storage_scope（末级兜底，有意保留）
        ├── 认到名字但人设库无此角色（历史 scope）→ 中立，不借别人的口吻
        └── 解析不到（user / dual_role / 隔离 scope）→ 原中立模板
    → is_distillation_role_allowed(config, role_id) [白名单，当前只有 aveline]
        └── 不在名单（其他角色 / legacy 历史 scope）→ 0 次请求直接跳过
    → collect_candidates() [v3 F4：无 24h 窗口，按 (timestamp, id) 最旧优先 + 条数/字符预算]
        ├── 作业账本 <memories>/nightly/<user>_distill_jobs.json：leased / failed（退避重试）/ skipped
        ├── 正文为空 / 被污染的每日总结 → 显式 skipped，不写空梗概
        └── 按产物结算：记忆已 is_distilled 才算 done；预算外条目退回 pending 下一晚继续
    → 蒸馏同时输出【人物线索】/【角色演化】
    → filter_profile_signals [确定性剔除对话双方本人，再按条目落盘]
    → WeightedMemory.distillation_metadata [按条目落盘]
Global Phase: PeopleProfileExtractor.extract_and_update(memory_managers=...)
    → _get_new_messages() [读取全局原始聊天增量，先过世界线闸门（与在线读路径同一谓词）]
    → _group_into_batches() [先按 (角色目录, 会话) 分区，批次永不跨会话]
    → _collect_distillation_gate() [汇总所有 scope 的蒸馏线索，带 event_id / message_id / conversation_id]
    → _select_candidate_batches() [来源 ID 命中优先；±600 秒时间窗只留给无来源旧线索且不跨会话；零 API 本地保守规则]
        ├── 无线索 → 推进水位，LLM 0 次
        └── 命中 → _call_llm() [只详细分析候选批次]
        → _parse_response() [解析 JSON]
        → _update_existing_profile() / _create_new_profile() [更新/创建档案，事实写 KnownFact.source_refs 回指批次会话与原始事件]
```

手动调用且不传 `memory_managers` 时保留全量提取行为；nightly 必须传全量 manager，确保人物档案作为 global 共享数据每天只跑一次。详细提取仍使用 `memory_models.distillation`，稳定 system prompt 与动态 user prompt 分离以复用 Prompt Cache。

`extractor.py` 不直接扫描 JSONL、解析业务 JSON 或创建 `KnownFact`，这些实现分别委托给上述兄弟模块。`memory/nightly/task_runner.py` 同样只保留桥接/阶段路由，蒸馏执行与 codec、全局业务编排位于独立文件。

**工具查询入口**:

```python
# core/tools/person_profile_tool.py
class QueryPersonProfileTool(BaseTool):
    name = "query_person_profile"
    # 调用 manager.query_profile_details(name)
    # 返回完整档案（core_fields + description + known_facts）
```

**预期效果**:

| 维度 | 改造前 | 改造后 |
|------|--------|--------|
| 人设更新 | 硬编码不更新 | 夜间 LLM 批量提取，动态演化 |
| 人物背景 | 无 | 提及时自动注入，工具可查详情 |
| 多版本 | 无 | Aveline_Qi / Aveline_Ling 分版本 |

## 3.12 Character Social Relationships（角色视角社交关系）

与 3.11 的「用户人际关系」分开：`people_profiles/` 存Master视角的人物；角色自己的室友/朋友/实验室关系存 `{scope}_data/social/relationships.json`，避免把两套关系写混。

**文件**:

| 文件 | 职责 |
|------|------|
| `core/character/people/relationship/models.py` | `RelationshipEntry`（关系、亲密度、当前状态、最近事件）与 kind/closeness 推断 |
| `core/character/people/relationship/seeding.py` | 从 `knowledge/people/*.json` 生成静态关系基线 |
| `core/character/people/relationship/store.py` | 运行态读写、LLM 更新合并、Prompt 投影 |
| `core/character/people/relationship/config.py` | `character_runtime.yaml#character_social` 开关与角色白名单 |
| `core/character/people/character_relationship_service.py` | 复用对话分批 + LLM JSON 流程，按 scope 增量提取关系更新 |
| `core/agents/.../prompt/character_relationship_prompts.py` | 角色关系提取 system/user Prompt |

**流程**:

```text
NightlyGlobalTaskService._run_character_relationships()
  → CharacterRelationshipExtractor.extract_all()
  → PeopleConversationSource.load_scope_messages(scope)   # {scope}_data/chat_history
  → group_into_batches()                                  # 复用人物提取的分批
  → PeopleProfileExtractor.call_llm()                     # 复用模型路由/空流重试
  → parse_response() → relationship_updates
  → CharacterRelationshipStore.apply_updates()            # 当前状态 + 最近事件
  → {scope}_data/social/relationships.json
```

聊天侧由 `layered_context.py` 读取 `render_character_relationship_payload(scope)`，在 `[SOCIAL RELATIONSHIPS]` 区块注入前 3 个室友的 `relationship` / `current_state` / `last_interaction`；其他人物仍由 `knowledge/people` 关键词检索。静态人物卡是基线，运行态只覆盖 `current_state` 和 `recent_events`，不会反写人设文件。

当前启用角色为 `ye`（`character_runtime.yaml` 的 `character_social.relationship_roles`）；新增角色只需把 scope 加进白名单并提供 `knowledge/people/*.json`。`max_batches_per_run` 限制每晚 LLM 批次数，`min_confidence` 过滤低置信度更新。
