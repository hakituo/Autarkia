# SelfImprovementService（自我改进）

> 本文同步自项目内部技术参考，仅描述公开可见的实现。
> 由 `scripts/doc_records/sync_tech_docs.py` 生成，请勿直接编辑；修改请改真源后重新生成。
> 文档入口：[技术参考目录](../README.md)

---

## 3.8 SelfImprovementService（自我改进系统）

**文件**: `core/services/self_improvement/`

**职责**: 结构化学习、纠正追踪、核心记忆管理。整合 SKILL.md (self-improvement) + SKILL1.md (memory-manager) + 现有系统的优点，构建统一的自我改进能力。

**核心架构**:

```
用户纠正/错误/学习
  → CorrectionTracker（6种信号检测）→ 记录到 .learnings/corrections.md
  → LearningLogger（结构化日志）→ .learnings/LEARNINGS.md | ERRORS.md | FEATURE_REQUESTS.md
  → CoreMemory（轻量核心记忆）→ MEMORY.md（≤5KB，6分区）
  → LearningPromoter（模式检测）→ 重复≥3次/2条相似纠正 → 晋升为永久规则
  → DailyLogger（每日日志）→ memory/YYYY-MM-DD.md
  → DriftGuard（漂移防护）→ 验证记忆准确性
```

**子模块**:

| 模块 | 文件 | 职责 |
|------|------|------|
| 主服务 | `service.py` | 统一入口，协调所有子模块 |
| 学习日志 | `learning_logger.py` | 结构化学习/错误/功能请求日志（.learnings/，ID 追踪，模式去重） |
| 纠正追踪 | `correction_tracker.py` | 6种纠正信号检测 + 纠正晋升（2条相似→永久规则） |
| 核心记忆 | `core_memory.py` | MEMORY.md 管理（6分区，自动瘦身，NOT-to-save，归档） |
| 学习晋升 | `learning_promoter.py` | 重复模式检测 + 纠正晋升 → auto_promoted.md |
| 每日日志 | `daily_logger.py` | memory/YYYY-MM-DD.md 格式日志 + 自动归档 |
| 漂移防护 | `drift_guard.py` | 验证文件路径/函数名/配置值准确性 |
| 数据模型 | `models.py` | LearningEntry/ErrorEntry/FeatureRequestEntry/CorrectionEntry |

**MEMORY.md 分区结构**:

| 分区 | 图标 | 保留策略 | 上限 |
|------|------|---------|------|
| 用户偏好 | 🔒 | 永久保留 | 无限制 |
| 角色定位 | 💼 | 永久保留 | 无限制 |
| 业务经验 | 📝 | 长期保留 | ≤15条 |
| 活跃任务 | 📋 | 完成后删 | 10条 |
| 纠正记录 | 🔄 | 晋升后删 | ≤10条 |
| 对话摘要 | 💬 | 7天精简 | 20条 |

**纠正信号检测**:

| 信号 | 示例 | 优先级 |
|------|------|--------|
| 放弃 | "算了我来" | 最高 |
| 直接否定 | "不对"、"错了" | 高 |
| 不同答案 | "应该是"、"其实是" | 中高 |
| 质疑 | "你确定？" | 中 |
| 温和引导 | "换个角度" | 低 |
| 示范 | 直接展示正确做法 | 最低 |

**晋升规则**:

| 条件 | 晋升目标 |
|------|---------|
| 学习条目重复≥3次 | auto_promoted.md |
| 2条相似纠正 | auto_promoted.md |
| 最佳实践类学习 | prompt 组件 |
| 知识缺口类学习 | MEMORY.md 永久区 |

**配置项** (`SelfImprovementSettings`):

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `enabled` | True | 是否启用 |
| `correction_detection` | True | 通用纠正检测 |
| `learning_log` | True | 结构化学习日志 |
| `core_memory` | True | MEMORY.md 管理 |
| `auto_slim` | True | 自动瘦身 |
| `drift_guard` | True | 漂移防护 |
| `daily_log` | True | 每日日志 |
| `promotion` | True | 学习晋升 |
| `memory_max_size_kb` | 5 | MEMORY.md 最大 KB |
| `prompt_injection` | True | prompt 注入 |

**与现有系统的关系**:

| 关联系统 | 集成方式 |
|---------|---------|
| WeightedMemoryManager | MEMORY.md 是轻量摘要，底层仍用加权记忆 |
| AutoHealService | 自愈补丁应用后通知自我改进系统记录学习 |
| correction.py | 生活类纠正保留，通用纠正扩展到 CorrectionTracker |
| JournalService | 每日日志与日记系统联动 |
| PromptAssembler | 自我改进指令注入到 prompt |

月度角色变化仅存于角色数据目录 `monthly/YYYY/MM/summary.json` 的 `persona_evolution` 字段，`read_monthly_summary` 继续返回其内容。独立 `core/character/configs/evolution/` 副本及 PersonaManager 对应读写接口已移除；月度总结生成后仍调用 `distill_memory` 生成 `extra` 画像。离线验证：`tests/scripts/journal/verify_monthly_evolution_single_source.py`。

**依赖关系**:

```
SelfImprovementService
├── LearningLogger      → 结构化学习/错误/功能请求日志
├── CorrectionTracker   → 通用纠正检测与记录
├── CoreMemory          → MEMORY.md 核心记忆管理
├── LearningPromoter    → 学习晋升与模式检测
├── DailyLogger         → 每日日志生成
├── DriftGuard          → 记忆漂移防护
└── PromptAssembler     → 自我改进指令注入
```
