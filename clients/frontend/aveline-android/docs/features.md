# 核心特性（WS / 生命模拟 / 情绪 / 手机操作）

> Android 端子文档 · 上级入口：[README.md](../README.md)
> 只写当前实现；改代码前先看 `.trae/context/routing/android.md` 定位文件。

---

## 核心特性

### WebSocket 实时通信

通过 `WebSocketManager` 维持与后端的长连接，支持 15+ 种消息类型：

| 消息类型 | 说明 |
|----------|------|
| `TextMessage` | 普通文本消息 |
| `ResponseChunk` | 流式响应片段（智能分段：正文 vs 括号内"内心独白"） |
| `ResponseReset` | AI 开始调用工具：只清空当前正在生成的临时消息，不影响历史消息（`ChatFlushManager.onResponseReset()`） |
| `ResponseDone` | 响应完成 |
| `EmotionUpdate` | 情绪状态推送 |
| `LifeStatusUpdate` | AI生命状态广播 |
| `PhoneActionCommand` | 手机操作指令 |
| `RitualEvent` | 仪式事件 |
| `SpontaneousReaction` | 自发反应 |
| `ImageResult` | 图像生成结果 |
| `VideoResult` | 视频/动图生成结果（气泡内用 ExoPlayer 渲染） |
| `Notification` | 通知推送 |
| `ConnectionEstablished` | 连接建立 |
| `ReconnectSync` | 重连同步 |

**真流式响应时序**（HTTP SSE `/v1/chat` 与 WebSocket 共用）：

```
普通文本 → ResponseChunk 逐块显示
AI 开始调用工具 → ResponseReset（清空当前生成中的临时消息，历史不动）
工具执行完成 → ResponseChunk 继续逐块显示（最终回答）
全部完成 → ResponseDone（消息完成，后端此刻才写入数据库）
```

连接管理采用指数退避重连策略，前台服务常驻模式下保持连接。

### AI 生命模拟

AI 拥有四维生命状态（`LifeStatus`）：

- **健康** (health) - AI身体状况
- **饥饿** (hunger) - AI饱食度
- **幸福** (happiness) - AI幸福度
- **能量** (energy) - AI精力值

状态通过 WebSocket 实时推送，UI 层通过伴侣详情的状态页展示。`GET /api/v1/life/status` 同时返回当前活动、基础回复策略、睡眠摘要与当前角色当天的 `DailyPlan`。其中 `activity_chat_eligible` 只表示该活动是否适合角色间 Peer Chat，用户消息的真实基础行为以 `reply_policy.mode` 为准：轻活动延迟回复，学习与睡眠暂不回复。状态页据此显示明确的回复方式及“唤醒 / 打断 / 跳过活动”，并直接复用后端现有生命与日程控制接口。

伴侣详情在“状态”和“模型”之间提供独立“日程”页，按当前聊天角色展示当天完整时间线、正在进行项、完成状态及时间是否可调整。打开详情和进入日程页都会强制刷新当前 persona scope，避免旧状态缓存已有当前活动却缺少新增的 `daily_plan` 字段；接口暂未同步时只显示同步提示及当前活动，不再误报角色没有生成日程。

### 情绪系统

- `Emotion` 模型定义 primary + intensity + colors
- 预定义情绪常量：NEUTRAL / HAPPY / CALM / EXCITED / SAD
- `EmotionColorMapping` 将情绪映射为颜色方案
- `BreathingBackground` 呼吸灯动画随情绪颜色联动

### 手机操作执行

`PhoneActionExecutor` 执行 AI 下发的 13 种手机操作指令：

| 操作 | 说明 |
|------|------|
| `CreateCalendarEvent` | 创建日历事件 |
| `SetAlarm` | 设置闹钟 |
| `SetTimer` | 设置定时器 |
| `OpenApp` | 打开应用 |
| `MakePhoneCall` | 拨打电话 |
| `SendSms` | 发送短信 |
| `OpenNavigation` | 打开导航 |
| `SetDndMode` | 勿扰模式 |
| `MediaControl` | 媒体控制 |
| `OpenSettings` | 打开设置 |
| `ShareContent` | 分享内容 |
| `SetVolume` | 调节音量 |
| `GetLocation` | 获取位置 |

### 后端通道：局域网 → 组网 → 公网
