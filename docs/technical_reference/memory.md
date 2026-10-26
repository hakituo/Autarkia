# 记忆系统

> 本文同步自项目内部技术参考，仅描述公开可见的实现。
> 由 `scripts/doc_records/sync_tech_docs.py` 生成，请勿直接编辑；修改请改真源后重新生成。
> 文档入口：[技术参考目录](README.md)

---

## 5. 记忆系统技术详解

## 5.1 WeightedMemoryManager

**文件**: `memory/weighted_memory_manager.py`

**核心数据结构**:

```python
memory_record = {
    "id": str,
    "content": str,
    "memory_type": str,
    "category": str,
    "topics": List[str],
    "display_tags": List[str],
    "status": str,
    "weight": float,
    "source_ref": Dict[str, Any],
    "readable_title": str,
    "readable_summary": str,
    "last_hit_time": float,
    "metadata": Dict[str, Any],
}
```

**关键方法**:

```python
class WeightedMemoryManager:
    def __init__(self):
        self.weighted_memories: Dict[str, Memory] = {}
        self.keyword_index: Dict[str, Set[str]] = {}
        self.category_index: Dict[str, List[str]] = {}
        self.content_dedupe_index: Dict[str, str] = {}
        self.lock = threading.RLock()

    async def add_memory(
        self,
        content: str,
        category: str = "general",
        weight: float = 1.0,
        metadata: Optional[Dict] = None,
    ) -> str:
        """添加记忆"""

    async def search_memories(
        self,
        query: str,
        limit: int = 10,
        category: Optional[str] = None,
    ) -> List[Dict]:
        """搜索记忆"""

    async def update_weight(self, memory_id: str, delta: float) -> bool:
        """更新权重"""

    async def apply_decay(self) -> None:
        """应用权重衰减"""
```

## 5.2 权重计算

**文件**: `memory/core/weights.py`（写入期初值 + 查询期衰减）、`memory/core/recall_probability.py`（概率召回）

**初值**（`calculate_initial_weight`，正文内容不直接参与）：

```
weight = 1.0                                     # base_weight
       × 3.0  若 is_important                     # importance_multiplier
       + min(len(topics)   × 0.5, 5.0)            # topic_frequency_bonus
       + min(len(emotions) × 0.8, 3.0)            # emotion_relevance_bonus
```

**查询期衰减**（`apply_time_decay`，按天指数，不是半衰期公式）：

```
Wd = max(W × rate ** days_passed, 0.1)
```

`rate` 按类别覆盖：`learning 0.99` / `festival 0.98` / `work 0.90` /
`uncategorized 0.75` / `daily 0.70`；类别不在表里时取 `recency_decay_factor = 0.9`。
落盘时保留原始权重，衰减只在读取/排序时计算，重启不会累积衰减。

**概率召回**（`passes_recall_filter`，硬过滤之后才生效）：

```
decay   = max(0.05, (1 + hours_age / 24) ** -0.85)          # 幂律，不是 exp
logit   = weight / 5 + max(keyword, weighted) × 2 + (decay - 0.5) × 4 - 1.5
prob    = min(sigmoid(logit), 0.9)
```

`is_important`、`weight > 7`、`category/memory_type == preference` 直通，不参与随机。
访问强化的上限与上述直通条件目前不一致（`update_weight_by_access` 上限 20.0），
属于待评测项，不要在文档里合并成单一 heat 字段。

## 5.3 检索操作

**文件**: `memory/core/retrieval_ops.py`

**混合检索**:

```python
def hybrid_search_memories(
    manager: Any,
    query: str,
    limit: int = 10,
    keyword_weight: float = 0.4,
    vector_weight: float = 0.6,
) -> List[Dict]:
    """混合检索（关键词 + 向量）"""
    # 1. 关键词检索
    keyword_results = search_by_keywords(manager, query, limit * 2)

    # 2. 向量检索
    query_embedding = generate_embedding(query)
    vector_results = search_by_similarity(manager, query_embedding, limit * 2)

    # 3. 融合排序
    combined_scores = {}
    for i, result in enumerate(keyword_results):
        combined_scores[result["id"]] = keyword_weight * (1 / (i + 1))
    for i, result in enumerate(vector_results):
        combined_scores[result["id"]] = combined_scores.get(result["id"], 0) + vector_weight * result["similarity"]

    # 4. 返回Top-K
    sorted_results = sorted(combined_scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_results[:limit]
```

## 5.4 记忆存储与数据类

**文件**: `memory/core/storage.py`

**数据类架构**（v2.1.0 新增）：

```python
@dataclass
class MemoryContext:
    """管理器上下文，封装 add_memory_locked 所需的全部管理器状态和回调"""
    weighted_memories: Dict[str, Dict[str, Any]]
    short_term_memory: List[Dict[str, Any]]
    category_index: Dict[str, List[str]]
    important_prompts: List[Dict[str, Any]]
    sensitive_memories: List[Dict[str, Any]]
    topic_weights: Dict[str, float]
    emotion_memory_map: Dict[str, List[Dict[str, Any]]]
    weight_calculator: Any
    detect_topics_fn: Callable
    detect_emotion_fn: Callable
    # ... 其他回调和配置

@dataclass
class MemoryInput:
    """记忆输入参数，封装单条记忆的内容和元数据"""
    content: str = ""
    topics: Optional[List[str]] = None
    emotions: Optional[List[str]] = None
    is_important: bool = False
    source: str = "chat"
    category: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    scopes: Optional[List[str]] = None
    user_id: str = "default"
    is_sensitive_mode: bool = False
```

**辅助函数**（v2.1.0 从 add_memory_locked 提取）：

| 函数 | 职责 |
|------|------|
| `_filter_system_injection` | 过滤系统提示词注入 |
| `_resolve_legacy_kwargs` | 兼容旧版关键字参数 |
| `_add_memory_core` | 核心添加逻辑（使用 MemoryContext + MemoryInput） |
| `_normalize_for_dedupe` | 内容标准化用于去重 |
| `_is_low_value_for_weighted` | 判断是否为低价值记忆 |
| `_build_dedupe_key` | 构建去重索引 key |
| `_build_memory_record` | 构建记忆字典记录 |
| `_check_duplicate` | 去重检测（支持 content_dedupe_index 和 O(N) 回退） |
| `_handle_duplicate` | 处理重复记忆的合并更新 |
| `_extract_preferences_for_user` | 用户偏好提取 |
| `_index_new_memory` | 新记忆索引（分类、话题、情绪、重要提示词晋升） |

## 5.5 融合裁决评分体系

**文件**: `memory/core/analysis_ops.py`（薄壳门面；实现按职责拆到 `analysis_types.py` / `analysis_scoring.py` / `analysis_shadow.py` / `analysis_fusion.py` / `analysis_adjudication.py` / `analysis_pending.py` / `analysis_pending_runner.py`，对外符号仍从原路径再导出）

**评分配置**（v2.2.0 重构为 FusionConfig dataclass）：

```python
@dataclass(frozen=True)
class FusionConfig:
    """融合裁决配置，替代硬编码字典"""
    s_rule: float = 0.40
    s_ai: float = 0.20
    s_consistency: float = 0.30
    s_stability: float = 0.10

    consistency_topic: float = 0.55
    consistency_category: float = 0.20
    consistency_discourse: float = 0.25

    trigger_rule_signal: float = 0.40
    trigger_ai_signal: float = 0.35
    trigger_state_consistency: float = 0.15
    trigger_consistency: float = 0.10

    rule_topic_strength: float = 0.6
    rule_category_strength: float = 0.4

    trigger_allow_threshold: float = 0.72
```

**融合结果**（v2.2.0 重构为 FusionResult dataclass）：

```python
@dataclass
class FusionResult:
    """融合裁决结果，替代 _write_fusion_metadata 的 20+ 参数"""
    action: str = "reject"
    final_confidence: float = 0.0
    s_rule: float = 0.0
    s_ai: float = 0.0
    s_consistency: float = 0.0
    s_stability: float = 0.0
    trigger_final_confidence: float = 0.0
    trigger_decision: str = "deny"
    # ... 其他字段
```

**话语类型权重惩罚**：

| 话语类型 | 权重惩罚 |
|---------|---------|
| INSTRUCTION/QUESTION/REPORTED_SPEECH | -0.4 |
| HYPOTHETICAL/FUTURE_PLAN | -0.25 |
| RETROSPECTIVE_SELF_REPORT | -0.1 |
| `BLOCKED_DISCOURSE_LABELS` | 阻断触发的话语标签 | frozenset: RETROSPECTIVE_SELF_REPORT, FUTURE_PLAN 等 |
| `RISK_CATEGORIES` | 高风险分类 | frozenset: preference, sensitive, state |
| `RISK_MEMORY_TYPES` | 高风险记忆类型 | frozenset: preference, sensitive, state, profile |

**评分流程**:
```
1. _compute_rule_score → 规则评分（话题强度 + 分类强度）
2. _compute_consistency_score → 一致性评分（话题/分类/话语 Jaccard 相似度）
3. _compute_stability_score → 稳定性评分（历史分析结果一致性）
4. _compute_final_confidence → 加权融合（FUSION_WEIGHTS）
5. _compute_trigger_decision → 触发决策（阈值 0.72）
6. _assess_risk_level → 风险评估（调整 override/supplement 阈值）
7. _apply_fusion_action → 执行裁决（override/supplement/reject/rollback）
```

## 5.5 性能优化特性

| 特性 | 文件 | 说明 |
|------|------|------|
| 话题缓存 | `retrieval_ops.py` | `get_top_topics` 30秒 TTL 缓存，实例级缓存（`manager._top_topics_cache`），写操作自动失效；`_cleanup_top_topics_cache` 防止内存泄漏（上限64条） |
| 查询嵌入缓存 | `retrieval_ops.py` | 使用 `hashlib.sha256` 确定性哈希做缓存 key（跨进程一致） |
| 关键词数量限制 | `utils.py` | `extract_keywords` 限制最多30个关键词，仅生成 2-gram |
| 统一评分函数 | `scoring_utils.py` | `compute_hybrid_score_with_result` 统一所有模块的评分逻辑（v2.2.0） |
| 统一锁策略 | `mutation_ops.py`, `retrieval_ops.py`, `vector_ops.py`, `cache_ops.py` | `_get_read_lock()` / `_get_write_lock()` 辅助函数，优先使用读写锁，回退到互斥锁（v2.2.0） |
| 读写锁写者优先 | `concurrency_optimized.py` | `ReadWriteLock` 新增 `_waiting_writers` 计数器，防止写者饥饿（v2.2.0） |
| 增量主题缓存 | `retrieval_ops_optimized.py` | `TopicWeightCache` 增量更新 + `needs_rebuild()` 定期重建保证时间衰减一致性（v2.2.0） |
| 蒸馏时间衰减 | `distillation.py` | 分段 recency_factor：≤1h→3.0, 1h~1d→1.5, >1d→0.5 |
| 统一停用词 | `utils.py` | `_UNIFIED_STOPWORDS` 合并 `text_segmenter.STOPWORDS` 和额外停用词，消除重复定义 |
| 线程安全单例 | `weighted_memory_manager.py` | 模块级 `_instances` + `_instances_lock`，消除函数属性竞态 |
| 安全快照 | `retrieval_ops.py` | `search_memories` 锁内 `.copy()` 快照，消除 TOCTOU 竞态 |
| 权重持久化 | `io_ops.py` | 加载时保留原始权重，时间衰减仅在查询时动态计算，避免重启累积衰减 |
| 并发安全缓存 | `concurrency_optimized.py` | `ConcurrentCache`（原 `LockFreeCache`），读无锁 + 写加锁（v2.2.0 重命名） |
| 线程安全计数器 | `concurrency_optimized.py` | `ThreadSafeCounter`（原 `AtomicCounter`），加锁计数器（v2.2.0 重命名） |
| 共享锁工具 | `lock_utils.py` | `get_read_lock()` / `get_write_lock()` 上下文管理器，13个子模块统一使用（v2.3.0） |
| 统一缓存管理器 | `unified_cache_manager.py` | `UnifiedCacheManager` 整合嵌入/查询/记忆L1-L2/主题缓存，统一统计和清理接口（v2.3.0） |
| 异步持久化 | `async_persistence.py` | `async_safe_json_dump` / `async_safe_json_load`，aiofiles + 回退到 asyncio.to_thread（v2.3.0） |
| 批量操作 | `batch_ops.py` | `batch_delete_memories` / `batch_update_weights` / `batch_search_memories`，单次锁获取（v2.3.0） |

## 5.6 模块依赖关系

```
storage.py ──imports──→ record_ops.py (merge_tags)
mutation_ops.py ──imports──→ retrieval_ops.py (invalidate_top_topics_cache)
weighted_memory_manager.py ──delegates──→ weighted_manager/{initialization,lifecycle,writing,queries,preferences,support}.py ──→ memory/core/*
```

## 5.7 聊天记录的渠道标注（2026-09-27）

**问题**：同一个 `conversation_id` 里混着多端产生的记录（QQ 导出后导入的历史、QQ bot
实时对话、App 实时对话、Obsidian），它们共用一份 chat_history 与同一个加权记忆池，
但来源信息只写不读，模型分不清「这条是 QQ 上说的」还是「刚刚在 App 里说的」。

**判定**：`core/utils/data/chat_channel.py::resolve_event_channel()` 三级判据，
按可靠性排序、缺一不可：

1. `platform`（顶层或 `metadata` 内）非空 —— 最权威，导入器与 QQ bot 实时链路都写；
2. `imported` / `source_kind` 非空 —— pairs 导入器只写 `imported` 不写 platform；
3. `readable_title` 车道名含 QQ（形如「Ling / QQ对话」）—— 兜底覆盖 QQ bot 早期
   写入的无 platform 记录；存量 11.7 万条事件里 `readable_title` 100% 非空。

三条都不命中即 `app`（Android / HTTP 路径写的是空串 platform）。

**当前渠道**：`set_current_platform()` 用 ContextVar 携带本轮请求的渠道，由
`ChatAgent.stream_chat()` 在生成前设置（所有流式回复的唯一入口，platform 已由 WS
连接或 HTTP 路径带入）；非流式与后台任务回落 `app`。与 `message_branch.py` 同一套路，
避免把 platform 逐层透传穿过 `stream_chat → context → assembler → 工具执行`。

**标注规则**：只标**与当前渠道不同**的记录，与当前渠道一致时不标（App 上看 App
历史零噪音）。后缀形如「（来自QQ）」，重复 sanitize 先剥再补，保证幂等。

| 位置 | 落点 |
| --- | --- |
| 注入上下文的历史 | `context_budget/history_fetch.py::sanitize_history_messages(current_platform=…)`；从 ChatHistoryStore 回填时带出 `readable_title` / `imported` / `source_kind` 供判据使用 |
| 检索工具结果 | `core/tools/search_chat_history_tool.py::_format_results` / `_format_peer_results` |
| 告诉模型「当前渠道」 | `persona_system/prompt/assembler.py`：紧贴「当前时间」注入「当前渠道：App / QQ」，且只在历史里真的出现跨渠道记录时补一句解释后缀含义 |

**已知缺口**：主动消息（`active_care`）落库时不写 `platform`，落在「主线对话」车道的
主动消息只能按 App 处理；如实际投递到 QQ 会漏标，需从投递连接把 platform 补进落库 metadata。

## 5.8 v3 世界线读写闸门（2026-10-25）

**模块**：`memory/topology/` 只做纯计算与受控持久化，不依赖 WeightedMemoryManager。

| 文件 | 职责 |
| --- | --- |
| `events.py` | 规范化事件字段：`event_id` / `idempotency_key` / `turn_id` / `client_node_id`、双时间、`topology_status`、`content_eligible` |
| `tree.py` | 确定性建树：同一事件集与到达顺序无关，`canonical_hash` 可复核；child-before-parent 进 pending |
| `linear.py` | QQ / Telegram 等线性来源由服务端附着 `srv:<event_id>` 父链，不让每条消息各自成根 |
| `anchors.py` | 逐 tree 游标 `anchors_by_tree`；请求显式路径优先，快照只作缓存，`anchor_events.jsonl` 留审计 |
| `read_context.py` | 五段硬过滤：namespace → perspective → continuity → anchor 路径 → as-of；`namespace_shared` 只豁免派生 note 自身 |
| `read_gate.py` | 生产读路径闸门：默认 **compat**，缺失型原因放行并计数；有明确 anchor 时兄弟线仍隐藏；拓扑故障退回放行 |

**生产接线**（同一查询不能从旁路拿到被回滚的兄弟线）：

- `core/tools/search_chat_history_tool.py`：回滚边界过滤 + `filter_raw_events`，索引版与文件扫描版、peer 搜索都走；
- `core/tools/search_memory_tool.py`：`include_chat_history` 分支与前者共用同一套过滤；
- `memory/core/history_ops.py`：`get_event_history` / `get_conversation_records`；
- `context_budget/history_fetch.py`：短期记忆回填空缺时的原始事件读取。

**模式口径**：`strict` 只对 `complete` 树启用；历史事件几乎全是 `topology=unknown`，
因此生产默认 `compat`。放行原因码为 `compat_pass:<legacy_unknown|tree_unresolvable|anchor_missing|topology_incomplete>`，
隐藏原因码为 `not_on_anchor_path`（有 anchor 时的兄弟线）与 `namespace_mismatch` / `perspective_mismatch` / `as_of_excluded`。

**D8 迁移**：`scripts/maintenance/backfill_event_refs.py`（默认 dry-run，`--apply` 带备份目录）。
只补 `metadata.event_ref`，不改 content / timestamp / id / summary；同 role 同 turn 多候选判 ambiguous 跳过，
多条记忆共享同一事件是合法 provenance。2026-10-25 实跑：404 条全部补齐，`linked_turn_only` 归零，
`legacy_only` 15,948 不变，拓扑计数守恒。

**数据目录口径**：审计与迁移一律按磁盘事实映射 scope（`discover_scope_data_dirs`），
不走 `get_role_data_dir()` —— 未注册角色名会被归一化成 `user`，导致 `user_data` 的记录被重复计入多个 scope。

## 5.9 v3 离线实验（C6/C7，2026-10-25）

**目的**：在不动生产存储与权重的前提下，比较三种提取粒度与两个 MiniMax 模型。

- 代码：`scripts/experiments/weighted_memory/`（cases / extraction / retrieval / metrics / llm_client / run_c6 / run_c7 / compare_models）。
- 数据：`tests/fixtures/memory_topology/extraction_e2e_cases.json`（合成 10 案例 / 90 消息 / 20 问题 / 25 金标事实）。
- 模型：默认 MiniMax Plan（`MINIMAX_PLAN_API_KEY` / `MiniMax-M3.1-Flash`）；M3 用 `--model MiniMax-M3`，服务端 `reasoning_split=True` 分离推理。
- 控制：temperature=0、同一 system prompt、同一输入证据与 token 预算；检索统一 BM25+jieba；分支过滤与消融同条件。
- 缓存：`output/evaluation/llm_cache_*.jsonl`，键含 provider/base_url/model/prompt，重跑不计费。

结果（端到端 20 题，两模型各自最优臂均为 C）：

| 模型 | 端到端 | 知识更新 | 跨线 | 金标覆盖 | tokens（C 臂） | 平均延迟 |
| --- | --- | --- | --- | --- | --- | --- |
| MiniMax-M3.1-Flash | 19/20 | 3/3 | 0 | 24/25 | 13,548 | 5.08s |
| MiniMax-M3 | 19/20 | 3/3 | 0 | 23/25 | 12,677 | 5.60s |

结论：F3 候选形态取 C（raw turns 保留可检索 + segment 原子 fact 扩展）；模型默认 Flash
（同正确率、覆盖更高、延迟更低）。A 逐条摘要最差（13/20 / 14/20）；B 的 Recall@5 最高
（0.868 / 0.763）但回答正确率低于 C（17/20 / 15/20）。限制：合成集小、关键词代理评分、
BM25 未覆盖 embedding，结论仍需真实标注集复核。
