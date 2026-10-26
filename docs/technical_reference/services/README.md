# 服务层技术详解（索引）

> 本文同步自项目内部技术参考，仅描述公开可见的实现。
> 由 `scripts/doc_records/sync_tech_docs.py` 生成，请勿直接编辑；修改请改真源后重新生成。
> 文档入口：[技术参考目录](../README.md)

---

## 按服务查

| 服务 | 文件 | 入口 | 职责 |
| --- | --- | --- | --- |
| AvelineService（3.1） | [aveline.md](aveline.md) | `core/services/aveline/service.py` | 对话主编排：会话解析、Prompt 组装、生成与落库 |
| ActiveCareService（3.2） | [active-care.md](active-care.md) | `core/services/active_care/core/service.py` | 主动关怀：决策 → 内容规划 → 生成 → 投递 |
| WorkspaceService（3.3） | [others.md](others.md) | `core/services/workspace/service.py` | 工作空间统一记录执行层 |
| SchedulerService（3.4） | [others.md](others.md) | `core/services/scheduler/task/task_scheduler.py` | 全局任务调度 |
| MetaIntentService（3.5） | [others.md](others.md) | `core/services/metacognition/service.py` | 元认知：意图与自我反思（待定模块） |
| ImmuneSystemService（3.6） | [immune-self-healing.md](immune-self-healing.md) | `core/services/immune/service.py` | 生物免疫式自愈：检测 / 响应 / 修复 |
| AutoHealService（3.7） | [immune-self-healing.md](immune-self-healing.md) | `core/services/auto_heal/` | 日志驱动的自动 bug 检测与修复 |
| SelfImprovementService（3.8） | [self-improvement.md](self-improvement.md) | `core/services/self_improvement/` | 结构化学习、纠正追踪、核心记忆 |
| 其他平台服务（3.9） | [others.md](others.md) | `core/services/` | DataOps / Study / LifeSim / Journal / Daily / VTube 等汇总 |
| CharacterDailyService（3.10） | [character-daily.md](character-daily.md) | `core/services/character_daily/` | 角色日常：计划、活动状态机、ActivityInstance、Nightly 预生成 |
| People Profile（3.11） | [people-profile.md](people-profile.md) | `core/character/people/` | 人物档案：三层结构、多版本人设、夜间提取、按需注入 |
| 角色社交关系（3.12） | [people-profile.md](people-profile.md) | `core/character/people/` | 角色视角下的人际关系与互识边界 |
| DigitalWellbeingService | [digital-wellbeing.md](digital-wellbeing.md) | `core/services/digital_wellbeing/service.py` | 应用使用限额、会话状态机、超限关怀、Nightly 复盘 |
| 学习工具（背单词） | [study-tools.md](study-tools.md) | `core/tools/study/english/` | FSRS 调度、词书构建、AI 抽词、安卓复习会话 |
| 学习服务（专注番茄钟） | [study-tools.md](study-tools.md) | `core/services/study/focus_session_service.py` | 后端权威计时、监控策略、跨端同步、AI 只读聚合 |

---

## 与其他文档的分工

- 服务「是什么、边界在哪」→ `.trae/context/CAPABILITY_MAP.md`
- 服务「怎么初始化、依赖谁」→ `.trae/context/ARCHITECTURE.md`
- 服务「内部实现与数据流」→ 本目录对应文件
- 模块级操作指南（改代码前读）→ `.trae/skills/<模块>/SKILL.md`

---

## 维护约定

1. 新增/改造服务时，先在本表加一行，再在对应文件里写实现细节；不要在本索引里写实现细节。
2. 单个服务族文件超过 400 行就再按职责拆（如 `character-daily/nightly.md`），并在本表把文件指向拆分后的入口。
3. 只写「当前代码怎么跑」，不写版本变更史 —— 变更史进 `docs/updates/`。
4. 文件路径必须写成仓库相对路径，且能在仓库里直接命中；`tests/scripts/docs/verify_tech_doc_paths.py` 会校验。
