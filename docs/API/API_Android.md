# 前后端 API 端点对照审计（重构后）

> **数据源**：
> - 后端真实路由 = `routers/v1/` + `routers/admin/` + `routers/openai_compat.py`，统一挂载在 `api_v1_router(prefix="/api/v1")` 之下。
> - Android 声明 = `data/remote/api/AvelineApiService.kt`（Retrofit 注解里的路径）。
>
> **状态约定**：✅ 路径与方法完全匹配 ｜ ⚠️ Android 路径需改（后端已重构）｜ ❌ 后端无此端点 ｜ 🔵 Android 未调用（后端有但前端没用）
>
> **重构变更**：后端已完成路由统一，所有业务域按功能分组挂在 `/api/v1/*` 下。旧的扁平路径（如 `/api/v1/message`、`/api/v1/tts`、`/api/v1/study/*`）已迁移至对应的域前缀下。

---

## 一、路径重构总览

后端路由从扁平结构重构为**域分组结构**，Android 所有旧路径需同步更新：

| 旧路径模式 | 新路径模式 | 域 |
|---|---|---|
| `/api/v1/message` | `/api/v1/chat/message` | chat |
| `/api/v1/regenerate` | `/api/v1/chat/regenerate` | chat |
| `/api/v1/greeting` | `/api/v1/chat/greeting` | chat |
| `/api/v1/persona` | `/api/v1/chat/persona` | chat |
| `/api/v1/status/life` | `/api/v1/life/status` | life |
| `/api/v1/tts` | `/api/v1/media/tts` | media |
| `/api/v1/voices` | `/api/v1/media/voices` | media |
| `/api/v1/upload` | `/api/v1/media/upload` | media |
| `/api/v1/stt` | `/api/v1/media/stt` | media |
| `/api/v1/image/*` | `/api/v1/vision/image/*` | vision |
| `/api/v1/analyze_screen` | `/api/v1/vision/analyze-screen` | vision |
| `/api/v1/memory/*` | `/api/v1/memories/*` | memories |
| `/api/v1/study/*` | `/api/v1/vocab/*` | vocab |
| `/api/v1/daily-data/*` | `/api/v1/context/daily/*` | context |
| `/api/v1/intent/classify` | `/api/v1/context/intent/classify` | context |
| `/api/personas/*` | `/api/v1/personas/*` | personas |
| `/api/models/*` | `/api/v1/models/*` | models |
| `/api/plugins/*` | `/api/v1/plugins/*` | plugins |
| `/peer-chat/*` | `/api/v1/peer-chat/*` | peer-chat |

---

## 二、逐模块对照

### 1. 聊天核心 Chat

**源文件**：`routers/v1/chat.py`　　**前缀**：`/api/v1/chat`

| Android 旧声明 | 后端真实路径 | 状态 | Android 应改为 |
|---|---|---|---|
| `POST /api/v1/message` | `POST /api/v1/chat/message` | ⚠️ | `POST /api/v1/chat/message` |
| `POST /api/v1/regenerate` | `POST /api/v1/chat/regenerate` | ⚠️ | `POST /api/v1/chat/regenerate` |
| `GET /api/v1/greeting` | `GET /api/v1/chat/greeting` | ⚠️ | `GET /api/v1/chat/greeting` |
| `GET /api/v1/persona` | `GET /api/v1/chat/persona` | ⚠️ | `GET /api/v1/chat/persona` |

### 2. 会话管理 Sessions

**源文件**：`routers/v1/sessions.py`　　**前缀**：`/api/v1/sessions`

| Android 旧声明 | 后端真实路径 | 状态 |
|---|---|---|
| `GET /api/v1/sessions` | `GET /api/v1/sessions` | ✅ |
| `POST /api/v1/sessions` | `POST /api/v1/sessions` | ✅ |
| `GET /api/v1/sessions/{id}/history` | `GET /api/v1/sessions/{id}/history` | ✅ |
| `DELETE /api/v1/sessions/{id}` | `DELETE /api/v1/sessions/{id}` | ✅ |
| `PUT /api/v1/sessions/{id}` | `PUT /api/v1/sessions/{id}` | ✅ |
| — | `DELETE /api/v1/sessions/{id}/messages/{msg_id}` | 🔵 未调用 |

### 3. 生命与情绪 Life

**源文件**：`routers/v1/life.py`（聚合；端点在 `life_status.py` / `life_sleep.py` / `life_activity.py`）　　**前缀**：`/api/v1/life`

| Android 旧声明 | 后端真实路径 | 状态 | Android 应改为 |
|---|---|---|---|
| `GET /api/v1/status/life` | `GET /api/v1/life/status` | ⚠️ | `GET /api/v1/life/status` |
| — | `POST /api/v1/life/emotion/detect` | 🔵 未调用 |

### 4. 人格 Persona

**源文件**：`routers/v1/personas.py`　　**前缀**：`/api/v1/personas`

| Android 旧声明 | 后端真实路径 | 状态 | Android 应改为 |
|---|---|---|---|
| `GET /api/personas` | `GET /api/v1/personas` | ⚠️ | `GET /api/v1/personas` |
| `GET /api/personas/active` | `GET /api/v1/personas/active` | ⚠️ | `GET /api/v1/personas/active` |
| `POST /api/personas/switch` | `POST /api/v1/personas/switch` | ⚠️ | `POST /api/v1/personas/switch` |
| `POST /api/personas` (create) | — | ❌ 后端无 | 建议 Android 删此方法 |
| `PUT /api/personas/{id}` (update) | — | ❌ 后端无 | 建议 Android 删此方法 |
| `DELETE /api/personas/{id}` (delete) | — | ❌ 后端无 | 建议 Android 删此方法 |
| — | `GET /api/v1/personas/current` | 🔵 未调用 |

### 5. 模型 Models

**源文件**：`routers/v1/models.py`　　**前缀**：`/api/v1/models`

| Android 旧声明 | 后端真实路径 | 状态 | Android 应改为 |
|---|---|---|---|
| `GET /api/models` | `GET /api/v1/models` | ⚠️ | `GET /api/v1/models` |
| — | `POST /api/v1/models/switch` | 🔵 未调用（Android 走 WebSocket 切模型） |

### 6. 记忆 Memories

**源文件**：`routers/v1/memories.py`　　**前缀**：`/api/v1/memories`　　**注意**：旧 `/memory` 已改为 `/memories`

| Android 旧声明 | 后端真实路径 | 状态 | Android 应改为 |
|---|---|---|---|
| `GET /api/v1/memory/weighted` | `GET /api/v1/memories` | ⚠️ | `GET /api/v1/memories` |
| `GET /api/v1/memory/{id}` | — | ❌ 后端无单条获取 | 建议后端补或 Android 用列表过滤 |
| `GET /api/v1/memory/search?q=` | — | ❌ 后端无搜索端点 | `/memories` 支持 `category`/`emotion` 查询参数 |
| `DELETE /api/v1/memory/{id}` | `DELETE /api/v1/memories/{memory_id}` | ⚠️ | `DELETE /api/v1/memories/{memory_id}` |
| `PATCH /api/v1/memory/{id}/important` | — | ❌ 后端无标记重要 | 建议后端补 |
| `GET /api/v1/memory/stats` | `GET /api/v1/memories/stats` | ⚠️ | `GET /api/v1/memories/stats` |
| `GET /api/v1/memory/tags` | `GET /api/v1/memories/tags` | ⚠️ | `GET /api/v1/memories/tags` |
| — | `DELETE /api/v1/memories` (批量清除) | 🔵 未调用 |
| — | `POST /api/v1/memories/clear` (清会话历史) | 🔵 未调用 |

### 7. 背单词 / 学习 Vocab

**源文件**：`routers/v1/vocab.py`　　**前缀**：`/api/v1/vocab`　　**注意**：旧 `/study` 已合并至 `/vocab`

| Android 旧声明 | 后端真实路径 | 状态 | Android 应改为 |
|---|---|---|---|
| `GET /api/v1/study/daily` | `GET /api/v1/vocab/daily` | ⚠️ | `GET /api/v1/vocab/daily` |
| `GET /api/v1/study/files` | `GET /api/v1/vocab/files` | ⚠️ | `GET /api/v1/vocab/files` |
| `GET /api/v1/study/mode` | `GET /api/v1/vocab/mode` | ⚠️ | `GET /api/v1/vocab/mode` |
| `POST /api/v1/study/review` | `POST /api/v1/vocab/review` | ⚠️ | `POST /api/v1/vocab/review` |
| `GET /api/v1/study/mistakes` | `GET /api/v1/vocab/mistakes` | ⚠️ | `GET /api/v1/vocab/mistakes` |
| `GET /api/v1/study/dict/stats` | `GET /api/v1/vocab/dictionary/stats` | ⚠️ | `GET /api/v1/vocab/dictionary/stats` |
| `GET /api/v1/study/memory/curve` | `GET /api/v1/vocab/curve` | ⚠️ | `GET /api/v1/vocab/curve` |
| `POST /api/v1/study/upload` | — | ❌ 后端无 | 文件上传走 `POST /api/v1/media/upload` |
| `DELETE /api/v1/study/files/{id}` | — | ❌ 后端无 | — |
| `POST /api/v1/study/mode` | — | ❌ 后端无 | — |
| `POST /api/v1/study/files/active` | — | ❌ 后端无 | — |
| `POST /api/v1/study/session/start` | — | ❌ 后端无 | — |
| `POST /api/v1/study/session/end` | — | ❌ 后端无 | — |
| `GET /api/v1/study/session/stats` | — | ❌ 后端无 | — |
| — | `GET /api/v1/vocab/subjects` | 🔵 未调用 |
| — | `GET /api/v1/vocab/summary` | 🔵 未调用 |
| — | `GET /api/v1/vocab/dictionary/search` | 🔵 未调用 |
| — | `GET /api/v1/vocab/dictionary/list` | 🔵 未调用 |
| — | `GET /api/v1/vocab/tools` | 🔵 未调用 |
| — | `POST /api/v1/vocab/tools/{cat}/{id}/run` | 🔵 未调用 |
| — | `POST /api/v1/vocab/vocabulary/add` | 🔵 未调用 |
| — | `POST /api/v1/vocab/vocabulary/switch` | 🔵 未调用 |

### 8. 食物系统 Food ✅ 对齐

**源文件**：`routers/v1/food.py`　　**前缀**：`/api/v1/food`

| Android 旧声明 | 后端真实路径 | 状态 |
|---|---|---|
| `GET /api/v1/food/menu` | `GET /api/v1/food/menu` | ✅ |
| `GET /api/v1/food/inventory` | `GET /api/v1/food/inventory` | ✅ |
| `POST /api/v1/food/buy/{food_id}` | `POST /api/v1/food/buy/{food_id}` | ✅ |
| `POST /api/v1/food/eat/{food_id}` | `POST /api/v1/food/eat/{food_id}` | ✅ |
| `GET /api/v1/shop/items` | — | ❌ 旧 shop 已废弃 |
| `POST /api/v1/shop/purchase` | — | ❌ 旧 shop 已废弃 |

### 9. 媒体与语音 Media

**源文件**：`routers/v1/media.py`（聚合；语音端点在 `media_voice.py`，上传在 `media_upload.py`）　　**前缀**：`/api/v1/media`

| Android 旧声明 | 后端真实路径 | 状态 | Android 应改为 |
|---|---|---|---|
| `POST /api/v1/tts` | `POST /api/v1/media/tts` | ⚠️ | `POST /api/v1/media/tts` |
| `GET /api/v1/voices` | `GET /api/v1/media/voices` | ⚠️ | `GET /api/v1/media/voices` |
| `POST /api/v1/upload` | `POST /api/v1/media/upload` | ⚠️ | `POST /api/v1/media/upload` |
| — | `POST /api/v1/media/stt` | 🔵 未调用（语音转文字走本地） |
| — | `GET /api/v1/media/voice/reference-audio` | 🔵 未调用 |

### 10. 视觉与图像 Vision

**源文件**：`routers/v1/vision.py`　　**前缀**：`/api/v1/vision`

| Android 旧声明 | 后端真实路径 | 状态 | Android 应改为 |
|---|---|---|---|
| `GET /api/v1/image/models` | `GET /api/v1/vision/image/models` | ⚠️ | `GET /api/v1/vision/image/models` |
| `POST /api/v1/image/generate` | `POST /api/v1/vision/image/generate` | ⚠️ | `POST /api/v1/vision/image/generate` |
| `POST /api/v1/vision/describe` | `POST /api/v1/vision/describe` | ✅ | — |
| `POST /api/v1/analyze_screen` | `POST /api/v1/vision/analyze-screen` | ⚠️ | `POST /api/v1/vision/analyze-screen` |

### 11. 插件 Plugins

**源文件**：`routers/v1/plugins.py`　　**前缀**：`/api/v1/plugins`

| Android 旧声明 | 后端真实路径 | 状态 | Android 应改为 |
|---|---|---|---|
| `GET /api/plugins/variants/status` | `GET /api/v1/plugins/variants/status` | ⚠️ | `GET /api/v1/plugins/variants/status` |
| `POST /api/plugins/variants/toggle` | `POST /api/v1/plugins/variants/toggle` | ⚠️ | `POST /api/v1/plugins/variants/toggle` |

### 12. 双角色对话 Peer Chat ✅ 已修

**源文件**：`routers/v1/peer_chat.py`　　**前缀**：`/api/v1/peer-chat`　　**原问题已修**：前缀已统一至 `/api/v1`

| Android 旧声明 | 后端真实路径 | 状态 |
|---|---|---|
| `GET /api/v1/peer-chat/history` | `GET /api/v1/peer-chat/history` | ✅ |
| `POST /api/v1/peer-chat/trigger` | `POST /api/v1/peer-chat/trigger` | ✅ |
| `GET /api/v1/peer-chat/status` | `GET /api/v1/peer-chat/status` | ✅ |
| — | `GET /api/v1/peer-chat/scripts` | 🔵 未调用 |

### 13. 上下文与日常 Context

**源文件**：`routers/v1/context.py`　　**前缀**：`/api/v1/context`　　**注意**：旧 `/daily-data` 和 `/intent` 已合并至此

| Android 旧声明 | 后端真实路径 | 状态 | Android 应改为 |
|---|---|---|---|
| `POST /api/v1/context/sync` | `POST /api/v1/context/sync` | ✅ | — |
| `GET /api/v1/daily-data/portrait/today` | `GET /api/v1/context/daily/portrait/today` | ⚠️ | `GET /api/v1/context/daily/portrait/today` |
| `GET /api/v1/daily-data/recent` | `GET /api/v1/context/daily/recent` | ⚠️ | `GET /api/v1/context/daily/recent` |
| `POST /api/v1/daily-data/record/drink` | `POST /api/v1/context/daily/record/drink` | ⚠️ | `POST /api/v1/context/daily/record/drink` |
| `POST /api/v1/daily-data/record/study` | `POST /api/v1/context/daily/record/study` | ⚠️ | `POST /api/v1/context/daily/record/study` |
| `POST /api/v1/daily-data/study/finish` | `POST /api/v1/context/daily/study/finish` | ⚠️ | `POST /api/v1/context/daily/study/finish` |
| `POST /api/v1/intent/classify` | `POST /api/v1/context/intent/classify` | ⚠️ | `POST /api/v1/context/intent/classify` |
| `GET /api/v1/notifications` | — | ❌ 后端无 | — |
| — | `POST /api/v1/context/daily/record/body-metrics` | 🔵 未调用 |
| — | `GET /api/v1/context/daily/list` | 🔵 未调用 |
| — | `GET /api/v1/context/daily/read` | 🔵 未调用 |
| — | `POST /api/v1/context/device` | 🔵 未调用 |

### 14. 系统与工具 System ✅ 对齐

**源文件**：`routers/v1/system.py`　　**前缀**：`/api/v1/system`

| Android 旧声明 | 后端真实路径 | 状态 |
|---|---|---|
| `GET /api/v1/system/preferences` | `GET /api/v1/system/preferences` | ✅ |
| `POST /api/v1/system/preferences` | `POST /api/v1/system/preferences` | ✅ |
| `POST /api/v1/system/mobile-push-token` | `POST /api/v1/system/mobile-push-token` | ✅ |
| `GET /api/v1/system/resources` | `GET /api/v1/system/resources` | ✅ |
| `GET /api/v1/system/stats` | `GET /api/v1/system/stats` | ✅ |
| — | `GET /api/v1/system/active-care/status` | 🔵 未调用 |
| — | `POST /api/v1/system/active-care/check` | 🔵 未调用 |
| — | `POST /api/v1/system/active-care/force-send` | 🔵 未调用 |
| — | `POST /api/v1/system/search/web` | 🔵 未调用 |
| — | `POST /api/v1/system/generate` | 🔵 未调用 |

### 15. 健康检查 Health ✅ 对齐

**源文件**：`routers/v1/health.py`　　**前缀**：`/api/v1/health`

| Android 旧声明 | 后端真实路径 | 状态 |
|---|---|---|
| `GET /health` | `GET /api/v1/health` | ⚠️ 确认 OkHttp baseUrl 带 `/api/v1` |

### 16. 用户状态 User

**源文件**：`routers/v1/user.py`　　**前缀**：`/api/v1/user`

| Android 旧声明 | 后端真实路径 | 状态 |
|---|---|---|
| — | `GET /api/v1/user/status` | 🔵 未调用 |

### 17. 工作区 Workspace

**源文件**：`routers/v1/workspace.py`　　**前缀**：`/api/v1/workspace`

| Android 旧声明 | 后端真实路径 | 状态 |
|---|---|---|
| `GET /api/v1/workspace/study/panel` | `GET /api/v1/workspace/study/panel` | ✅ |
| `POST /api/v1/workspace/study/record` | `POST /api/v1/workspace/study/record` | ✅ |
| — | `GET /api/v1/workspace/study/root` | 🔵 未调用 |
| — | `GET /api/v1/workspace/study/list` | 🔵 未调用 |
| — | `GET /api/v1/workspace/study/read` | 🔵 未调用 |
| — | `POST /api/v1/workspace/study/write` | 🔵 未调用 |
| — | `GET /api/v1/workspace/study/overview` | 🔵 未调用 |
| — | `POST /api/v1/workspace/study/action` | 🔵 未调用 |

### 18. 教学画像 Tutor 🔵 全新模块

**源文件**：`routers/v1/tutor.py`　　**前缀**：`/api/v1/tutor`　　**Android 完全未接入**

| 后端真实路径 | 说明 |
|---|---|
| `GET /api/v1/tutor/state` | 获取结构化学生画像 |
| `GET /api/v1/tutor/today` | 获取今日学习状态（详细） |
| `GET /api/v1/tutor/briefing` | 获取每日教学简报 |
| `GET /api/v1/tutor/plan` | 获取今日学习计划 |
| `GET /api/v1/tutor/weaknesses` | 获取薄弱点报告 |

### 19. 日记与工作区 Diary 🔵 全新模块

**源文件**：`routers/v1/diary.py`　　**前缀**：`/api/v1/diary`　　**Android 完全未接入**

| 后端真实路径 | 说明 |
|---|---|
| `GET /api/v1/diary` | 获取日记 |
| `GET /api/v1/diary/summary` | 获取日记摘要 |
| `POST /api/v1/diary/summary` | 生成日记摘要 |
| `GET /api/v1/diary/snapshot` | 获取每日工作区快照 |
| `GET /api/v1/diary/scheduled` | 获取待发送的定时消息 |
| `DELETE /api/v1/diary/scheduled/{msg_id}` | 删除/取消定时消息 |
| `GET /api/v1/diary/bionic-delay/profile` | 获取仿生延迟画像 |

### 20. 每日任务 Tasks 🔵 全新模块

**源文件**：`routers/v1/tasks.py`　　**前缀**：`/api/v1/tasks`　　**Android 完全未接入**

| 后端真实路径 | 说明 |
|---|---|
| `GET /api/v1/tasks/panel` | 获取每日任务面板 |
| `POST /api/v1/tasks/generate` | 从学习进度生成每日任务 |
| `POST /api/v1/tasks` | 创建或更新任务 |
| `PATCH /api/v1/tasks/{task_id}/status` | 更新任务状态 |
| `DELETE /api/v1/tasks/{task_id}` | 删除任务 |

---

## 三、运维域（admin）— Android 无需接入

| 域 | 前缀 | 端点数 | 说明 |
|---|---|---|---|
| 自愈系统 | `/api/v1/admin/auto-heal` | 7 | 补丁管理（应用/回滚/驳回） |
| 数据运维 | `/api/v1/admin/data-ops` | 15 | 摘要/规划/记忆规则/AI影子/融合/降噪 |
| 远程操作 | `/api/v1/admin/remote` | 3 | 远程文件操作/审批 |

---

## 四、独立挂载端点

| 域 | 前缀 | 端点 | 说明 |
|---|---|---|---|
| OpenAI 兼容 | `/v1` | `POST /v1/chat/completions` | 标准 OpenAI SDK 路径，Android 未接入 |
| Demo | `/demo` | `GET /demo` / `POST /demo/logs` / `WS /demo/ws/status` | 演示面板 |

---

## 五、WebSocket ✅ 对齐

| Android | 后端真实 | 状态 |
|---|---|---|
| `ws://.../api/v1/ws?token=&user_id=` | `WS /api/v1/ws` | ✅ |

---

## 六、修复优先级

### P0（路径错位必 404）

Android Retrofit 注解需批量更新以下路径：

| 优先 | 涉及模块 | 动作 |
|---|---|---|
| 1 | chat（4 个端点） | `/api/v1/message` → `/api/v1/chat/message` 等 |
| 2 | media（3 个端点） | `/api/v1/tts` → `/api/v1/media/tts` 等 |
| 3 | vision（3 个端点） | `/api/v1/image/*` → `/api/v1/vision/image/*` |
| 4 | memories（4 个端点） | `/api/v1/memory/*` → `/api/v1/memories/*` |
| 5 | vocab（7 个端点） | `/api/v1/study/*` → `/api/v1/vocab/*` |
| 6 | context（6 个端点） | `/api/v1/daily-data/*` → `/api/v1/context/daily/*` |
| 7 | persona（3 个端点） | `/api/personas` → `/api/v1/personas` |
| 8 | models（1 个端点） | `/api/models` → `/api/v1/models` |
| 9 | plugins（2 个端点） | `/api/plugins/*` → `/api/v1/plugins/*` |
| 10 | life（1 个端点） | `/api/v1/status/life` → `/api/v1/life/status` |

### P1（后端需补端点）

| 端点 | 优先级 | 说明 |
|---|---|---|
| `GET /memories/{id}` | 高 | 单条记忆获取 |
| `GET /memories/search` | 中 | 记忆搜索（或扩展列表过滤） |
| `PATCH /memories/{id}/important` | 低 | 标记重要 |

### P2（Android 死代码清理）

| 项目 | 说明 |
|---|---|
| persona create/update/delete | 后端无此能力，建议 Android 删 |
| `/api/v1/shop/*` | 旧 shop 已废弃，建议 Android 删 |
| `/api/v1/notifications` | 后端无此端点，建议 Android 删 |
| study session/start, session/end | 后端无此端点 |

---

## 七、统计

| 维度 | 数量 |
|---|---|
| 后端总端点数（去 WebSocket） | 114 |
| Android 声明端点数 | ~65 |
| ✅ 路径完全对齐 | ~20 |
| ⚠️ Android 需改路径（后端已重构） | ~33 |
| ❌ 后端无此端点 | ~10 |
| 🔵 后端有但 Android 未用 | ~68 |
| 🆕 新增模块 Android 可接入 | tutor(5) + diary(7) + tasks(5) = 17 |

---

*文档更新于路由重构后。Android 端需批量更新 Retrofit 注解路径以对齐新后端结构。*
