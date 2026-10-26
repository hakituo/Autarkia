# 免疫系统与自愈（ImmuneSystem / AutoHeal）

> 本文同步自项目内部技术参考，仅描述公开可见的实现。
> 由 `scripts/doc_records/sync_tech_docs.py` 生成，请勿直接编辑；修改请改真源后重新生成。
> 文档入口：[技术参考目录](../README.md)

---

## 3.6 ImmuneSystemService（免疫系统服务）

**文件**: `core/services/immune/service.py`

**职责**: 系统自愈与资源保护，模拟生物免疫系统的自动检测、自动响应、自动修复机制

**核心架构**:

```python
class ImmuneSystemService:
    def __init__(self, *, settings, lifecycle, health_checker, performance_monitor):
        self._thresholds = _ThresholdConfig()   # 配置缓存
        self._stats = _ImmuneStats()            # 运行指标
        self._last_downgrade_level: int = 0     # 当前降级级别
        self._errors: Deque                      # 错误记录（最多5000条）

    async def _loop(self):                       # 每10秒自检循环
        await self._tick()

    async def _tick(self):                       # 每次循环执行两大策略
        await self._apply_resource_response()    # 资源应急响应
        await self._apply_service_self_heal()    # 服务自愈重启
```

**两大核心能力**:

| 能力 | 方法 | 说明 |
|------|------|------|
| 资源应急响应 | `_apply_resource_response()` | 监控 CPU/内存，双阈值策略（medium/emergency），智能避让活跃任务 |
| 服务自愈重启 | `_apply_service_self_heal()` | 检测不健康/未初始化服务，自动重启，限频保护 |

**配置项** (`ImmuneSettings`):

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| enabled | True | 是否启用 |
| interval | 10.0s | 自检间隔 |
| restart_window_seconds | 600s | 重启统计窗口 |
| max_restarts_per_window | 2 | 窗口内最大重启次数 |
| min_restart_interval_seconds | 30.0s | 两次重启最小间隔 |
| memory_medium_threshold | 90.0% | 内存中负载阈值 |
| memory_emergency_threshold | 96.0% | 内存紧急阈值 |
| cpu_medium_threshold | 95.0% | CPU中负载阈值 |
| cpu_emergency_threshold | 99.0% | CPU紧急阈值 |

**优化特性** (2026-04-27):

- **配置缓存**: `_ThresholdConfig` dataclass 在 `initialize()` 时一次性读取，消除每次 tick 重复 getattr
- **运行指标**: `_ImmuneStats` 追踪 tick 数、降级次数、重启次数等，通过 `get_stats()` 暴露
- **降级恢复**: 资源恢复后自动调用 `perform_downgrade(level=0)` 解除降级
- **错误暴增检测**: `_check_error_burst()` 检测短时间错误暴增，执行预防性清理
- **线程安全单例**: `get_immune_system_service()` 使用 `threading.Lock` 保护

**依赖关系**:

```
ImmuneSystemService
├── PerformanceMonitor  → 获取 CPU/内存指标
├── ResourceMonitor     → 执行降级和资源清理
├── HealthChecker       → 检测不健康服务
├── LifecycleManager    → 重启服务
├── TaskScheduler       → 检查系统是否繁忙
└── ErrorReporter       → 接收全局错误回调
```

## 3.7 AutoHealService（自愈服务）

**文件**: `core/services/auto_heal/`

**职责**: 运行时日志驱动的自动 bug 检测与修复。灵感来自 OpenAI Symphony，但更注重运行时真实信号（日志 error、业务指标异常）而非静态代码扫描。

**核心架构**:

```
日志 Error
  → 错误回调 → AnomalyDetector（聚类/去重/指纹计算）
  → 规则匹配（5种规则）→ AnomalyEvent
  → RootCauseAnalyzer（traceback → 源码定位 → LLM 分析）
  → PatchGenerator（LLM 生成修复代码 + unified diff）
  → PatchSandbox（语法检查 + import 验证 + ruff 检查）
  → 人工审批 / 自动应用
  → Workspace.write_source_file()（安全沙箱写入 + 自动备份）
  → 可一键回滚
```

**子模块**:

| 模块 | 文件 | 职责 |
|------|------|------|
| 数据模型 | `models.py` | AnomalyEvent、ErrorFingerprint、Patch、RootCauseReport、5种默认异常规则 |
| 异常检测 | `anomaly_detector.py` | 错误聚类/去重/指纹计算，5种规则匹配 |
| 根因分析 | `root_cause_analyzer.py` | traceback 解析 → 源码定位 → LLM 分析 |
| 补丁生成 | `patch_generator.py` | LLM 生成修复代码 + unified diff |
| 补丁验证 | `patch_sandbox.py` | 语法检查 + import 验证 + ruff 检查 |
| 补丁管理 | `patch_manager.py` | 补丁的生成、验证、应用和回滚 |
| 报告生成 | `report_generator.py` | 生成、保存和管理自愈报告 |
| 自愈服务 | `heal_service.py` | 编排完整流程 + 7层安全机制 |

**7层安全机制**:

| 层级 | 机制 | 说明 |
|------|------|------|
| 1 | 受保护文件黑名单 | `main.py`、`lifecycle_manager.py`、`auto_heal/*`、`logger.py`、`integrated_config.py` 等核心文件永不修改 |
| 2 | 目录白名单 | 只能修改 `core/`、`config/`、`routers/`、`memory/` |
| 3 | 扩展名白名单 | 只能修改 `.py`、`.yaml`、`.yml`、`.json`、`.toml` |
| 4 | 每日补丁上限 | 每天最多 10 个补丁，每个文件每天最多 3 次 |
| 5 | 补丁体积限制 | 单个补丁最大 512KB |
| 6 | 三重备份+回滚 | 内存备份 + 文件备份 + 备份验证 + 失败自动恢复 + 一键回滚 API |
| 7 | 人工审批（默认） | 默认 `auto_apply=False`，补丁需人工审批才写入 |

**异常检测规则**:

| 规则名 | 类型 | 条件 | 自动修复 |
|--------|------|------|---------|
| `error_burst` | 错误暴增 | 5分钟内 >15 次错误 | ❌ |
| `repeated_same_error` | 重复异常 | 10分钟内同一错误 >5 次 | ✅ |
| `active_care_flood` | 业务指标异常 | 一天主动关怀 >50 条 | ✅ |
| `llm_timeout_cluster` | 错误聚集 | 10分钟内 LLM 超时 >5 次 | ✅ |
| `service_unhealthy` | 服务降级 | 有服务不健康 | ❌ |

**API 接口** (`/api/v1/auto-heal/`):

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/stats` | 获取统计信息 |
| GET | `/patches` | 获取所有补丁 |
| GET | `/patches/pending` | 获取待审批补丁 |
| GET | `/patches/{id}` | 获取补丁详情（含 diff） |
| POST | `/patches/{id}/apply` | 应用补丁 |
| POST | `/patches/{id}/rollback` | 回滚补丁 |
| POST | `/patches/{id}/reject` | 拒绝补丁 |
| POST | `/check` | 手动触发异常检查 |

**依赖关系**:

```
AutoHealService
├── AnomalyDetector     → 异常检测（订阅 log_sanitizer 错误回调）
├── RootCauseAnalyzer   → 根因分析（调用 AvelineService LLM）
├── PatchGenerator      → 补丁生成（调用 AvelineService LLM）
├── PatchSandbox        → 补丁验证（语法/import/ruff）
├── WorkspaceService    → 源码文件读写（安全沙箱）
├── EventBus            → 发布补丁就绪事件
└── LifecycleManager    → 服务生命周期（priority=7）
```

**与免疫系统的区别**:

| 维度 | 免疫系统 | 自愈服务 |
|------|---------|---------|
| 修复方式 | 重启服务、资源降级 | 修改源代码 |
| 触发信号 | 资源指标、健康检查 | 日志错误、业务指标 |
| 修复范围 | 运行时行为 | 代码层面 |
| 风险等级 | 低（可逆） | 中（需审批+备份） |
| 优先级 | 5 | 7 |
