# Autarkia API Reference

> 自动生成于路由重构后。所有业务端点挂在 `/api/v1` 之下，OpenAI 兼容层独立挂在 `/v1`。
> 启动后访问 `http://127.0.0.1:8000/docs` 查看交互式 Swagger 文档。

---

## 目录

- [1. 聊天核心 /chat](#1-聊天核心-chat)
- [2. 会话管理 /sessions](#2-会话管理-sessions)
- [3. 系统健康 /health](#3-系统健康-health)
- [4. 生命与情绪 /life](#4-生命与情绪-life)
- [5. 用户状态 /user](#5-用户状态-user)
- [6. 人格系统 /personas](#6-人格系统-personas)
- [7. 模型管理 /models](#7-模型管理-models)
- [8. 插件系统 /plugins](#8-插件系统-plugins)
- [9. 双角色对话 /peer-chat](#9-双角色对话-peer-chat)
- [10. 食物系统 /food](#10-食物系统-food)
- [11. 视觉与图像 /vision](#11-视觉与图像-vision)
- [12. 系统与工具 /system](#12-系统与工具-system)
- [13. 记忆系统 /memories](#13-记忆系统-memories)
- [14. 上下文与日常 /context](#14-上下文与日常-context)
- [15. 媒体与语音 /media](#15-媒体与语音-media)
- [16. 背单词 /vocab](#16-背单词-vocab)
- [17. 教学画像 /tutor](#17-教学画像-tutor)
- [18. 日记与工作区 /diary](#18-日记与工作区-diary)
- [19. 每日任务 /tasks](#19-每日任务-tasks)
- [20. 工作区文件 /workspace](#20-工作区文件-workspace)
- [21. WebSocket /ws](#21-websocket-ws)
- [22. 自愈系统 /admin/auto-heal](#22-自愈系统-adminauto-heal)
- [23. 数据运维 /admin/data-ops](#23-数据运维-admindata-ops)
- [24. 远程操作 /admin/remote](#24-远程操作-adminremote)
- [25. OpenAI 兼容层 /v1](#25-openai-兼容层-v1)
- [26. Demo /demo](#26-demo-demo)

---

## 路由架构

```
app (FastAPI)
├── /api/v1                    ← 业务聚合（api_v1_router）
│   ├── /chat                  ← 聊天核心
│   ├── /sessions              ← 会话管理
│   ├── /health                ← 系统健康
│   ├── /life                  ← 生命与情绪
│   ├── /user                  ← 用户状态
│   ├── /personas              ← 人格系统
│   ├── /models                ← 模型管理
│   ├── /plugins               ← 插件系统
│   ├── /peer-chat             ← 双角色对话
│   ├── /food                  ← 食物系统
│   ├── /vision                ← 视觉与图像
│   ├── /system                ← 系统与工具
│   ├── /memories              ← 记忆系统
│   ├── /context               ← 上下文与日常
│   ├── /media                 ← 媒体与语音
│   ├── /vocab                 ← 背单词
│   ├── /tutor                 ← 教学画像
│   ├── /diary                 ← 日记与工作区
│   ├── /tasks                 ← 每日任务
│   ├── /workspace             ← 工作区文件
│   ├── /ws                    ← WebSocket
│   └── /admin
│       ├── /auto-heal         ← 自愈系统
│       ├── /data-ops          ← 数据运维
│       └── /remote            ← 远程操作
├── /v1                        ← OpenAI 兼容层（独立挂载）
│   └── /chat/completions
└── /demo                      ← 演示面板（独立挂载）
    ├── /ws/status
    └── /trigger_kvswap
```

---

## 1. 聊天核心 /chat

**源文件：** `routers/v1/chat.py`　　**标签：** 聊天核心

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/chat/persona` | 获取当前角色配置 |
| GET | `/api/v1/chat/greeting` | 生成主动问候 |
| POST | `/api/v1/chat/message` | 发送消息（核心对话） |
| POST | `/api/v1/chat/regenerate` | 重新生成最后一条 AI 回复 |

### POST /api/v1/chat/message

核心对话端点。接收用户消息，经过意图识别、记忆检索、LLM 推理后返回回复。

**参数：**
- `message` (Body, dict) — 消息内容，含 `content` 字段
- `conversation_id` (Query, optional) — 会话 ID
- `model` (Query, optional) — 指定模型
- `voice_id` (Query, optional) — 语音 ID
- `stream` (Query, bool, default=false) — 是否流式返回

---

## 2. 会话管理 /sessions

**源文件：** `routers/v1/sessions.py`　　**标签：** 会话管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/sessions` | 获取会话列表 |

---

## 3. 系统健康 /health

**源文件：** `routers/v1/health.py`　　**标签：** 系统健康

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/health` | 系统健康检查 |

---

## 4. 生命与情绪 /life

**源文件：** `routers/v1/life.py`（聚合；端点在 `life_status.py` / `life_sleep.py` / `life_activity.py`，共享模型与辅助在 `life_shared.py`）　　**标签：** 生命与情绪

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/life/status` | 获取 Aveline 生命状态 |
| POST | `/api/v1/life/emotion/detect` | 检测文本情绪 |

---

## 5. 用户状态 /user

**源文件：** `routers/v1/user.py`　　**标签：** 用户状态

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/user/status` | 获取聚合用户状态（侧边栏 / Dashboard） |

---

## 6. 人格系统 /personas

**源文件：** `routers/v1/personas.py`　　**标签：** 人格系统

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/personas` | 获取所有可用人格列表 |
| GET | `/api/v1/personas/active` | 获取当前激活人格（兼容旧前端） |
| GET | `/api/v1/personas/current` | 获取当前人格详情 |
| POST | `/api/v1/personas/switch` | 切换到指定人格 |

---

## 7. 模型管理 /models

**源文件：** `routers/v1/models.py`　　**标签：** 模型管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/models` | 获取所有可用模型列表 |
| POST | `/api/v1/models/switch` | 切换当前 LLM 模型 |

---

## 8. 插件系统 /plugins

**源文件：** `routers/v1/plugins.py`　　**标签：** 插件系统

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/plugins/variants/status` | 查询分级模式是否开启 |
| POST | `/api/v1/plugins/variants/toggle` | 开关分级模式 |

---

## 9. 双角色对话 /peer-chat

**源文件：** `routers/v1/peer_chat.py`　　**标签：** 双角色对话

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/peer-chat/history` | 获取双角色对话历史 |
| GET | `/api/v1/peer-chat/status` | 获取双角色对话状态 |
| POST | `/api/v1/peer-chat/trigger` | 手动触发一次双角色对话 |
| GET | `/api/v1/peer-chat/scripts` | 获取双角色对话剧本列表 |

---

## 10. 食物系统 /food

**源文件：** `routers/v1/food.py`　　**标签：** 食物系统

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/food/menu` | 获取食物菜单 |
| GET | `/api/v1/food/inventory` | 获取食物库存 |
| POST | `/api/v1/food/buy/{food_id}` | 购买食物 |
| POST | `/api/v1/food/eat/{food_id}` | 食用食物 |

---

## 11. 视觉与图像 /vision

**源文件：** `routers/v1/vision.py`　　**标签：** 视觉与图像

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/vision/image/models` | 获取可用图像模型列表 |
| POST | `/api/v1/vision/image/generate` | 生成图像 |
| POST | `/api/v1/vision/describe` | 描述图像内容 |
| POST | `/api/v1/vision/analyze-screen` | 分析屏幕内容 |

---

## 12. 系统与工具 /system

**源文件：** `routers/v1/system.py`　　**标签：** 系统与工具

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/system/preferences` | 更新用户偏好设置 |
| GET | `/api/v1/system/preferences` | 获取用户偏好设置 |
| POST | `/api/v1/system/mobile-push-token` | 注册移动端推送 token |
| GET | `/api/v1/system/resources` | 获取系统资源信息 |
| GET | `/api/v1/system/stats` | 获取系统运行统计 |
| GET | `/api/v1/system/active-care/status` | 获取主动关怀运行状态 |
| POST | `/api/v1/system/active-care/check` | 触发主动关怀检查 |
| POST | `/api/v1/system/active-care/force-send` | 强制发送主动关怀消息 |
| POST | `/api/v1/system/search/web` | 联网搜索 |
| POST | `/api/v1/system/generate` | 通用 LLM 直调（不经过人设） |

---

## 13. 记忆系统 /memories

**源文件：** `routers/v1/memories.py`　　**标签：** 记忆系统

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/memories` | 获取加权记忆列表（支持过滤） |
| DELETE | `/api/v1/memories/{memory_id}` | 删除指定加权记忆 |
| DELETE | `/api/v1/memories` | 批量清除加权记忆 |
| POST | `/api/v1/memories/clear` | 清除会话历史（兼容旧入口） |
| GET | `/api/v1/memories/stats` | 获取记忆分类统计 |
| GET | `/api/v1/memories/tags` | 获取记忆标签（话题权重） |

---

## 14. 上下文与日常 /context

**源文件：** `routers/v1/context.py`　　**标签：** 上下文与日常

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/context/sync` | 同步设备上下文（综合） |
| POST | `/api/v1/context/device` | 上传设备上下文（单条） |
| POST | `/api/v1/context/daily/record/drink` | 记录喝水 |
| POST | `/api/v1/context/daily/record/body-metrics` | 记录体重 |
| POST | `/api/v1/context/daily/record/study` | 记录学习（进入低打扰） |
| POST | `/api/v1/context/daily/study/finish` | 结束学习（恢复打扰级别） |
| GET | `/api/v1/context/daily/portrait/today` | 获取今日用户画像 |
| GET | `/api/v1/context/daily/recent` | 获取最近的日常数据文件 |
| GET | `/api/v1/context/daily/list` | 列出日常数据目录 |
| GET | `/api/v1/context/daily/read` | 读取日常数据文件 |
| POST | `/api/v1/context/intent/classify` | 识别用户意图 |

---

## 15. 媒体与语音 /media

**源文件：** `routers/v1/media.py`（聚合；语音端点在 `media_voice.py`，上传在 `media_upload.py`，TTS 生成核心已下沉 `core/voice/tts_generation.py`）　　**标签：** 媒体与语音

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/media/stt` | 语音转文字 |
| GET | `/api/v1/media/voice/reference-audio` | 获取参考音频列表 |
| GET | `/api/v1/media/voices` | 获取可用语音列表 |
| POST | `/api/v1/media/tts` | 文字转语音 |
| POST | `/api/v1/media/upload` | 上传文件（图片 / 音频 / 文档） |

---

## 16. 背单词 /vocab

**源文件：** `routers/v1/vocab.py`　　**标签：** 背单词

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/vocab/daily` | 获取每日词汇列表 |
| GET | `/api/v1/vocab/subjects` | 获取学科列表 |
| GET | `/api/v1/vocab/files` | 获取学习文件列表 |
| GET | `/api/v1/vocab/mode` | 获取学习模式状态 |
| GET | `/api/v1/vocab/summary` | 获取学习日摘要 |
| GET | `/api/v1/vocab/dictionary/search` | 搜索词典 |
| GET | `/api/v1/vocab/dictionary/list` | 获取词典分页列表 |
| GET | `/api/v1/vocab/dictionary/stats` | 获取词典统计 |
| GET | `/api/v1/vocab/curve` | 获取记忆保持曲线 |
| GET | `/api/v1/vocab/mistakes` | 获取高错词列表 |
| GET | `/api/v1/vocab/tools` | 获取可用学习工具列表 |
| POST | `/api/v1/vocab/tools/{category}/{tool_id}/run` | 执行指定学习工具 |
| POST | `/api/v1/vocab/review` | 提交单词复习结果 |
| POST | `/api/v1/vocab/vocabulary/add` | 添加单词到学习队列 |
| POST | `/api/v1/vocab/vocabulary/switch` | 切换当前词典/句库 |

---

## 17. 教学画像 /tutor

**源文件：** `routers/v1/tutor.py`　　**标签：** 教学画像

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/tutor/state` | 获取结构化学生画像 |
| GET | `/api/v1/tutor/today` | 获取今日学习状态（详细） |
| GET | `/api/v1/tutor/briefing` | 获取每日教学简报 |
| GET | `/api/v1/tutor/plan` | 获取今日学习计划 |
| GET | `/api/v1/tutor/weaknesses` | 获取薄弱点报告 |

---

## 18. 日记与工作区 /diary

**源文件：** `routers/v1/diary.py`　　**标签：** 日记与工作区

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/diary` | 获取日记 |
| GET | `/api/v1/diary/summary` | 获取日记摘要 |
| POST | `/api/v1/diary/summary` | 生成日记摘要 |
| GET | `/api/v1/diary/snapshot` | 获取每日工作区快照 |
| GET | `/api/v1/diary/scheduled` | 获取待发送的定时消息 |
| DELETE | `/api/v1/diary/scheduled/{msg_id}` | 删除/取消定时消息 |
| GET | `/api/v1/diary/bionic-delay/profile` | 获取仿生延迟画像 |

---

## 19. 每日任务 /tasks

**源文件：** `routers/v1/tasks.py`　　**标签：** 每日任务

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/tasks/panel` | 获取每日任务面板 |
| POST | `/api/v1/tasks/generate` | 从学习进度生成每日任务 |
| POST | `/api/v1/tasks` | 创建或更新任务 |
| PATCH | `/api/v1/tasks/{task_id}/status` | 更新任务状态 |
| DELETE | `/api/v1/tasks/{task_id}` | 删除任务 |

---

## 20. 工作区文件 /workspace

**源文件：** `routers/v1/workspace.py`　　**标签：** 工作区文件

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/workspace/study/root` | 获取 Study 根目录路径 |
| GET | `/api/v1/workspace/study/list` | 列出 Study 目录内容 |
| GET | `/api/v1/workspace/study/read` | 读取 Study 文件文本 |
| POST | `/api/v1/workspace/study/write` | 写入 Study 文件文本 |
| POST | `/api/v1/workspace/study/record` | 记录学习进度 |
| GET | `/api/v1/workspace/study/overview` | 获取学习联动概览 |
| GET | `/api/v1/workspace/study/panel` | 获取学习面板聚合数据 |
| POST | `/api/v1/workspace/study/action` | 执行 Study 数据工具动作 |

---

## 21. WebSocket /ws

**源文件：** `routers/websocket.py`　　**标签：** WebSocket

| 方法 | 路径 | 说明 |
|------|------|------|
| WS | `/api/v1/ws` | WebSocket 端点（主） |
| WS | `/api/v1/ws/` | WebSocket 端点（带斜杠兼容） |

---

## 22. 自愈系统 /admin/auto-heal

**源文件：** `routers/admin/auto_heal.py`　　**标签：** 自愈系统

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/admin/auto-heal/stats` | 获取自愈系统统计数据 |
| GET | `/api/v1/admin/auto-heal/patches/pending` | 获取待处理补丁列表 |
| GET | `/api/v1/admin/auto-heal/patches` | 获取全部补丁列表 |
| GET | `/api/v1/admin/auto-heal/patches/{patch_id}` | 获取指定补丁详情 |
| POST | `/api/v1/admin/auto-heal/patches/{patch_id}/apply` | 应用指定补丁 |
| POST | `/api/v1/admin/auto-heal/patches/{patch_id}/rollback` | 回滚指定补丁 |
| POST | `/api/v1/admin/auto-heal/patches/{patch_id}/reject` | 驳回指定补丁 |

---

## 23. 数据运维 /admin/data-ops

**源文件：** `routers/admin/data_ops.py`　　**标签：** 数据运维

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/admin/data-ops/summary/daily` | 触发每日摘要生成 |
| POST | `/api/v1/admin/data-ops/summary/weekly` | 触发每周报告生成 |
| POST | `/api/v1/admin/data-ops/summary/human/daily` | 触发可读日摘要生成 |
| POST | `/api/v1/admin/data-ops/summary/human/weekly` | 触发可读周报生成 |
| POST | `/api/v1/admin/data-ops/planner/tasks` | 触发任务规划 |
| POST | `/api/v1/admin/data-ops/memory/rule/analysis` | 触发记忆规则分析 |
| GET | `/api/v1/admin/data-ops/memory/rule/metrics` | 获取记忆规则分析指标 |
| POST | `/api/v1/admin/data-ops/memory/ai-shadow/analysis` | 触发 AI 影子记忆分析 |
| GET | `/api/v1/admin/data-ops/memory/ai-shadow/metrics` | 获取 AI 影子分析指标 |
| POST | `/api/v1/admin/data-ops/memory/fusion/adjudicate` | 触发记忆融合裁决 |
| GET | `/api/v1/admin/data-ops/memory/fusion/metrics` | 获取记忆融合裁决指标 |
| POST | `/api/v1/admin/data-ops/memory/denoise/summary` | 生成记忆降噪摘要 |
| POST | `/api/v1/admin/data-ops/memory/denoise/tasks/{task_id}/run` | 执行记忆降噪任务 |
| GET | `/api/v1/admin/data-ops/memory/denoise/tasks/{task_id}` | 获取记忆降噪任务状态 |
| POST | `/api/v1/admin/data-ops/tasks/{task_id}/run` | 执行 DataOps 任务 |

---

## 24. 远程操作 /admin/remote

**源文件：** `routers/admin/remote_ops.py`　　**标签：** 远程操作

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/admin/remote/file/action` | 执行远程文件操作 |
| POST | `/api/v1/admin/remote/approve` | 批准远程动作 |
| POST | `/api/v1/admin/remote/reject` | 拒绝远程动作 |

---

## 25. OpenAI 兼容层 /v1

**源文件：** `routers/openai_compat.py`　　**标签：** OpenAI兼容

独立挂在顶层，不经过 `/api/v1` 前缀，保持标准 OpenAI SDK 路径。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v1/chat/completions` | OpenAI 兼容的对话补全接口 |

### POST /v1/chat/completions

与 OpenAI Chat Completions API 一致的接口，方便第三方工具/SDK 直接接入。

**请求体：**
```json
{
  "model": "deepseek-chat",
  "messages": [{"role": "user", "content": "你好"}],
  "stream": false,
  "max_tokens": 1024,
  "temperature": 0.7
}
```

支持的可选参数：`max_tokens`、`temperature`、`top_p`、`repetition_penalty`、`frequency_penalty`、`presence_penalty`、`stop`。

---

## 26. Demo /demo

**源文件：** `routers/demo.py`　　**标签：** demo

独立挂在顶层，不经过 `/api/v1` 前缀。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/demo` | Demo 面板页面 |
| POST | `/demo/logs` | 供演示脚本提交日志 |
| POST | `/demo/trigger_kvswap` | 手动触发 KVSwap 压力测试 |
| WS | `/demo/ws/status` | 资源状态实时推送 WebSocket |

---

## 端点统计

| 分类 | 端点数 |
|------|--------|
| 业务域（v1） | 84 |
| 运维域（admin） | 25 |
| OpenAI 兼容 | 1 |
| Demo | 4 |
| **合计** | **114** |

---

*本文档由路由扫描自动生成，如有出入以 Swagger 文档 (`/docs`) 为准。*
