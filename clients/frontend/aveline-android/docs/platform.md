# 依赖注入、数据层与服务层

> Android 端子文档 · 上级入口：[README.md](../README.md)
> 只写当前实现；改代码前先看 `.trae/context/routing/android.md` 定位文件。

---

## 依赖注入

4 个 Hilt 模块全部安装在 `SingletonComponent`：

```
AppModule          → Context, Resources, FusedLocationProviderClient
NetworkModule      → Json, 拦截器(鉴权/日志/动态域名), OkHttpClient, Retrofit, ApiService, WebSocketManager
DatabaseModule     → AvelineDatabase, 5个DAO
RepositoryModule   → 11个 @Binds 绑定（接口 → 实现）
```

网络模块亮点：
- **动态域名拦截器**：baseUrl 仅占位，真实地址由 `AppPreferences.effectiveBackendUrl`
  动态替换（该值由 `EndpointResolver` 在局域网/组网/公网之间裁决，不是用户手填的单一地址）
- **鉴权拦截器**：自动添加 Bearer Token 和 x-internal-token
- **条件日志**：Debug 模式 BODY 级别，Release 模式 NONE

## 数据层设计

### 网络请求

```
Retrofit (AvelineApiService)  ──50+ REST端点──>  后端 /api/v1/*
WebSocketManager              ──实时双向通信──>  后端 /api/v1/ws
```

API 端点覆盖：消息、会话、状态、上下文同步、TTS、文件上传、记忆、学习、人格、模型、食物、商店、图像生成、视觉描述、通知、系统、每日数据、意图分类、插件。

上下文同步中的应用用量使用本地当天零点至今的统计窗口。`DataSyncWorker` 随请求上报 `usage_window_start` 与 `usage_source=android_today_since_midnight_v1`；后端只有在窗口起点可验证时才允许该批数据触发数字健康 Active Care，旧客户端数据仅保存和展示，不触发超限关怀。

### 本地存储

```
Room Database (aveline_database, v1)
├── MessageEntity      → MessageDao
├── SessionEntity      → SessionDao
├── MemoryEntity       → MemoryDao
├── NotificationEntity → NotificationDao
└── HealthDataEntity   → HealthDataDao

SharedPreferences (aveline_preferences)
└── 17+ 配置项

EncryptedSharedPreferences (aveline_encrypted_preferences)
└── accessToken (AES256 加密)
```

## 服务层架构

```
┌──────────────────────────────────────────────────────────┐
│       AvelineForegroundServiceV2（生命周期薄壳）          │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ Notification │  │ Context/Health│  │ WebSocket     │  │
│  │ + A11y/Power │  │ Controllers   │  │ Coordinator   │  │
│  └──────────────┘  └──────────────┘  └──────┬────────┘  │
└──────────────────────────────────────────────┼───────────┘
                                               │
               ┌───────────────────────────────┼──────────────────────┐
               │                               │                      │
         ┌─────▼──────┐              ┌────────▼────────┐    ┌────────▼──────┐
         │ 通知展示    │              │ PhoneAction     │    │ RitualEvent   │
         │             │              │ Executor        │    │ /Reaction     │
         └─────────────┘              │ (13种手机操作)   │    │ 通知展示      │
                                      └────────┬────────┘    └──────────────┘
                                               │
                                      ┌────────▼────────┐
                                      │ WebSocket 发送  │
                                      │ 操作结果回传    │
                                      └─────────────────┘
```
