# DigitalWellbeingService（数字健康）

> 本文同步自项目内部技术参考，仅描述公开可见的实现。
> 由 `scripts/doc_records/sync_tech_docs.py` 生成，请勿直接编辑；修改请改真源后重新生成。
> 文档入口：[技术参考目录](../README.md)

---

## 3.11 DigitalWellbeingService（数字健康服务）

**文件**: `core/services/digital_wellbeing/service.py` | 路由: `routers/v1/context_device.py`

**定位**: 应用使用时长限额管理与复盘。Android 端通过 DataSyncWorker 上报当日应用前台时长，后端落盘 `app_usage.jsonl`，支持限额设定/超限判断/active care 关怀/nightly 自动复盘。

**核心功能**:
- **限额存取**: `get_limits()` / `save_limits()` / `set_single_limit()` — 按日期落盘 `digital_wellbeing/limits_{date}.json`，支持 user/auto 两种来源（auto=nightly 自动生成）
- **限额模型（2026-09-05 重构）**: 每个应用一条四元组策略 `AppLimitPolicy` — `daily_limit_ms`（每日总额度）+ `session_limit_ms`（单次连续额度）+ `session_gap_ms`（离开多久算新的一次，默认 2 分钟）+ `cooldown_ms`（单次超时后休息多久，默认 5 分钟）；两类限制同时生效并取更严格的那个。`session_cap_ms` 为旧字段，读取时自动兼容
- **超限判断**: `get_exceeded_apps()` — 对比当日限额与实时用量，返回超限列表（含 ratio 进度比）
- **Nightly 复盘**: `build_limit_suggestion()` — 基于昨日用量（>2h 的应用取 80% 向上取整到 15min）生成明日限额建议
- **Active Care 关怀**: `maybe_notify_exceeded_via_active_care()` — 超限时通过 active care 发提醒，带 6h 冷却 + 30min 最近活跃窗口

**数据流**:
```
Android UsageStatsManager (当日累计前台时长)
  ├→ UsageEvents 区间累加 → WellbeingScreen 本地实时进度
  ├→ SessionLimiter (会话状态机: 每日额度 + 单次额度 + gap + cooldown)
  │   ├→ AvelineAccessibilityService 实时执行 (前台跟踪 + 10s 轮询, 临近上限精确到秒)
  │   │   └→ 超额后返回桌面，再用 Shizuku / 后台进程结束作为执行通道 (UsageLimitEnforcer)
  │   └→ UsageLimitMonitor (15 分钟 Worker, 仅兜底校验每日额度 + 清理过期会话)
  └→ DataSyncWorker (每 15 分钟, getAppUsageSince(midnight))
      → POST /api/v1/context/sync → app_usage.jsonl
        ├→ read_today_app_usage (按 server_timestamp 最新聚合)
        │   └→ GET /wellbeing/app-limits → WellbeingScreen
        └→ maybe_notify_exceeded_via_active_care (带 last_used 活跃检查)
            └→ Active Care 关怀消息
```

**单次会话语义（2026-09-05）**:
- 旧版 `sessionCapMs + sessionCapStarts` 是"从配置下发那一刻起累计"的一次性 cap，不是真正的单次使用
- 新版由 Android 端 `SessionLimiter` 维护会话状态机（`appSessionStates` 持久化，跨进程恢复）：本次用量 = 当日累计 − 会话开始时基线；离开 < `session_gap_ms` 仍算同一次，≥ 则下次打开建立新会话
- 单次超限 → 强退 + 进入冷却（`cooldown_ms` 内再打开立即拦截）；冷却结束获得新的单次额度，但每日额度不重置；每日额度耗尽 → 当天（次日 00:00）都不能用
- 无障碍服务是单次额度的主执行器，15 分钟 Worker 不判定单次（拿不到前台信息），只做每日额度兜底与过期会话清理
- sync_context 新增 `app_policies`（完整四元组）下发；`app_limits` / `session_caps` 保留作旧客户端兼容

**关键修复 (2026-08-10)**:
- DataSyncWorker 从 `getAppUsage(hours=24)` 改为 `getAppUsageSince(todayMidnight)`，切断昨天数据污染
- `read_today_app_usage` 聚合从最大值改为最新时间戳
- `maybe_notify_exceeded` 增加最近活跃窗口，last_used >30min 跳过
- UsageLimitMonitor 会话 cap 从全局起点改为各自独立

**前端执行修复 (2026-08-17)**:
- Wellbeing 页面拉取/保存限额后立即写入本地缓存，不再等待下一轮 DataSyncWorker 才生效
- 使用 UsageEvents 累加精确裁切任意起点，避免会话限额混入设置前的 daily bucket
- 无障碍服务监听受限应用进入前台，超额时立即返回桌面；周期 Worker 继续作为无障碍未启用时的兜底
- 页面显示“使用情况访问 / 即时限制”是否就绪，并提供直达系统授权入口

**无障碍宿主保活 (2026-08-18)**:
- `AvelineAccessibilityService` 连接后无条件拉起 `AvelineForegroundServiceV2`，由前台进程降低无障碍宿主被系统回收的概率
- `AvelineForegroundServiceV2` 是不超过 300 行的生命周期薄壳；`services/foreground/` 分别承载通知与 Intent 协议、WebSocket 指令、上下文同步、Samsung Health 同步、无障碍监测和 WakeLock，避免 Service God Class
- 守护通知保持 `ongoing`，并通过 `deleteIntent` 在被划除后立即重新提交；已授权通知读取时，`AvelineNotificationService.onNotificationRemoved` 提供厂商系统兜底
- 恢复前必须确认无障碍仍在系统启用列表或常驻模式仍开启；用户主动关闭两者后不再拉起
- 通知自恢复不能绕过 Android 的无障碍授权：若系统关闭授权，只能提示用户回设置页重新开启

**相关文件**:
- 后端: `core/services/digital_wellbeing/service.py`, `core/tools/device/set_app_limit.py`
- 路由: `routers/v1/context_device.py` (`/context/sync`, `/wellbeing/app-limits`, `/wellbeing/app-limit`)
- 安卓: `services/wellbeing/`（`AppLimitPolicy.kt` / `SessionLimiter.kt` / `UsageLimitEnforcer.kt`）, `UsageLimitMonitor.kt`, `DataSyncWorker.kt`, `AvelineAccessibilityService.kt`, `AvelineForegroundServiceV2.kt`, `services/foreground/`, `ContextRepositoryImpl.kt`, `WellbeingViewModel.kt`, `WellbeingScreen.kt`
- 验证: `tests/scripts/android_frontend/verify_wellbeing_session_limiter.py`

**配置常量**:
- `_DEFAULT_SOFT_THRESHOLD_MS = 2h` — nightly 自动设限的最低用量阈值
- `_ENFORCE_GRACE_RATIO = 1.0` — 超限触发倍数
- `_CARE_COOLDOWN_SECONDS = 6h` — 同应用关怀消息冷却
- `_RECENT_ACTIVE_MINUTES = 30` — 最近活跃窗口
- `_EXCLUDED_PREFIXES` — 自动排除 com.aveline.ai 等系统/自身包
