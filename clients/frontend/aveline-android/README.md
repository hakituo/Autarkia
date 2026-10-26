# Aveline Android

Aveline AI 伴侣应用的 Android 原生客户端，基于 Kotlin + Jetpack Compose 构建，采用 MVVM + Clean Architecture 分层架构。

## 技术栈

| 类别 | 技术 | 版本 |
|------|------|------|
| 语言 | Kotlin | 1.9.22 |
| UI | Jetpack Compose + Material3 | BOM 2024.02.02 |
| 依赖注入 | Hilt (Dagger) | 2.48.1 |
| 本地数据库 | Room | 2.6.1 |
| 网络请求 | Retrofit + OkHttp | 2.9.0 / 4.12.0 |
| 序列化 | kotlinx-serialization | 1.6.0 |
| 图片加载 | Coil | 2.5.0 |
| 后台任务 | WorkManager | 2.9.0 |
| 推送 | Firebase Messaging | BOM 33.1.2 |
| 健康 | Health Connect | 1.1.0-alpha07 |
| 定位 | Play Services Location | 21.2.0 |
| 安全 | Android Security Crypto | 1.1.0-alpha06 |

构建配置：compileSdk 35 / minSdk 26 / targetSdk 35 / Java 17

模型与人设选择通过现有 `AppPreferences` 持久化。手动模型选择优先于后端默认模型，HTTP/SSE 请求使用保存的完整路由；人设版本按角色独立保存，切换成功后同步聊天会话和请求归属。退出重进或重启 App 会恢复选择。静态回归脚本：`tests/scripts/android_frontend/verify_chat_selection_persistence.py`；编译及设备上的退出重进、重启验收由 Android Studio 完成。

## 架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                    Presentation Layer                            │
│  Compose UI + ViewModel + Navigation + Theme + Components       │
├─────────────────────────────────────────────────────────────────┤
│                    Domain Layer                                  │
│  领域模型 (17个) + Repository接口 (11个)                         │
├─────────────────────────────────────────────────────────────────┤
│                    Data Layer                                    │
│  Remote (REST API + WebSocket + DTO)                            │
│  Local (Room + SharedPreferences + EncryptedPrefs)              │
│  Repository实现 (11个)                                           │
├─────────────────────────────────────────────────────────────────┤
│                    Service Layer                                 │
│  前台服务 / 手机操作执行 / 服务器发现 / TTS / 语音输入            │
│  文件上传 / 数据同步 / FCM推送 / 通知监听                        │
├─────────────────────────────────────────────────────────────────┤
│                    DI Layer (Hilt)                               │
│  AppModule / NetworkModule / DatabaseModule / RepositoryModule  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 子文档导航

细节已按主题拆到 `docs/`，本文只保留技术栈、架构总览与开发命令：

| 主题 | 文档 | 内容 |
| --- | --- | --- |
| 工程目录结构 | [docs/project-structure.md](docs/project-structure.md) | 包结构、模块划分与关键目录 |
| 核心特性 | [docs/features.md](docs/features.md) | WebSocket 实时通信、AI 生命模拟、情绪系统、手机操作执行 |
| 后端通道 | [docs/connectivity.md](docs/connectivity.md) | 局域网 → 组网 → 公网的切换口径、设置页展示、服务器零配置发现 |
| 健康数据 | [docs/health.md](docs/health.md) | Health Connect 集成、Samsung Health 读取层 |
| 平台分层 | [docs/platform.md](docs/platform.md) | 依赖注入、数据层设计、服务层架构 |
| UI 导航 | [docs/navigation.md](docs/navigation.md) | 导航图与路由约定 |

> 改代码前先在 `.trae/context/routing/android.md` 定位到具体文件。

## 开发

```bash
# 打开 Android Studio 项目
cd aveline-android/android

# 命令行构建
./gradlew assembleDebug

# 清理构建缓存
./gradlew clean
# 或使用项目提供的快速清理脚本
./fast-clean.bat        # Windows
```

仓库配置已使用阿里云镜像优先（settings.gradle.kts）。

## 测试

测试位于 `android/app/src/test/` 下，使用 JUnit + MockK + Kotest + coroutines-test：

- `presentation/chat/` - ChatViewModel 测试
- `presentation/components/` - BreathingBackground 测试
- `presentation/settings/` - ModelSelection 测试
- `presentation/theme/` - EmotionColorMapping 测试
- `services/` - FileUploadManager 测试
- `utils/` - InputValidator / SecurityManager 测试

```bash
./gradlew test
```
