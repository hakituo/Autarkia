# 客户端层（QQ / Telegram / Web / Android）

> 本文同步自项目内部技术参考，仅描述公开可见的实现。
> 由 `scripts/doc_records/sync_tech_docs.py` 生成，请勿直接编辑；修改请改真源后重新生成。
> 文档入口：[技术参考目录](README.md)

---

## 8. 客户端层技术详解

## Android 聊天会话与历史保留（2026-09-13）

- `RoleScopedPreferences` 用既有 persona filename 绑定 session 别名，首次沿用原 role 映射，防止后端展示角色名变化导致聊天容器切换。已有分裂容器保留，恢复须核对设备数据，不能后台猜测合并。
- Room 长期保存历史，取消发送完成后的 200 条自动裁剪。`MessageTreeNode` 仅投影父链、时间、版本等索引；`observeMessageWindow` 读取当前路径指定窗口正文，聊天首屏 50 条，上滑扩展 50 条。索引仍为会话全量，正文和媒体按需读取。
- 普通发送上下文独立取当前选中分支最近 200 条，编辑和重新生成取目标所在分支前缀，与页面窗口解耦。
- 普通回复落库保留数据库中最新的 parentId/isActiveVariant；API 历史初始化在 Room 事务内复查空库；旧会话空结果也带来源 ID，禁止覆盖当前页面。
- 不改后端 role 契约，不清除或自动合并历史；Android Studio 编译和真机验收仍是必需验证。

## 8.1 QQ机器人适配器

**文件**: `clients/bots/qq/main.py` / `clients/bots/qq/config.py`

**双QQ独立角色架构**:

```
QQ用户 <--> NapCatQQ #1 (端口3001) <--> QQAdapter(Aveline) <--> Autarkia
QQ用户 <--> NapCatQQ #2 (端口3002) <--> QQAdapter(Ling)   <--> Autarkia
```

- 单进程双实例：`dual_qq_adapter.py` 在同一进程内运行两个 `QQAdapter`，各自连接不同 NapCatQQ
- 配置对象化：`QQAdapterConfig` 封装所有 per-instance 配置（现含 QQ 消息聚合窗口、后端二次合并跳过开关等字段），`QQAdapter` 和 `AutarkiaSession` 从 `self.cfg` / `self._cfg` 读取，不再依赖全局变量
- 日志前缀：`_PrefixLogAdapter` 自动添加 `[Aveline]` / `[Ling]` 前缀区分角色
- 向后兼容：原有 `qq_adapter.py` 单QQ入口不受影响
- 延迟优化：QQ 侧默认仅保留 `0.35s` 本地聚合窗口，并通过 `skip_merge_wait` 告知后端 WebSocket 跳过第二层消息合并等待，避免单条消息被双重缓冲

**启动方式**:
- 单QQ: `start_scripts\start_qq_bot.bat` → `qq_adapter.py`
- 双QQ: `start_scripts\start_dual_qq_bot.bat` → `dual_qq_adapter.py`

**配置文件**:
- 单QQ: `clients/bots/config/config.json`
- 双QQ: `clients/bots/multi_qq_config.json`（定义 aveline/ling 两个角色的独立配置）

**消息处理流水线**:

```
1. Preprocess (预处理)
   ├── 表情提取 (FaceInjector.extract)
   ├── 引用消息展开 (process_reply_in_message)
   ├── 图片理解 (Vision, process_images_in_message)
   └── 语音转写 (STT, process_audio_in_message)

2. Command (命令路由)
   └── CommandRouter.dispatch() -> Handler

3. Intent (意图路由) [可选]
   ├── Fast Path: 本地正则匹配
   └── Slow Path: LLM意图分类

4. Chat (对话处理)
   └── AutarkiaSession -> WebSocket -> Autarkia
```

**Handler架构**:

```python
class BaseHandler:
    def __init__(self, adapter):
        self.adapter = adapter
        self.logger = adapter.logger

    async def api_request(self, method, path, json_body=None, params=None):
        """委托给适配器的API请求方法"""

    async def send_text(self, session_id, content):
        """委托给适配器的发送方法"""

class CommandRouter:
    def _build_routes(self) -> List[CommandRoute]:
        return [
            CommandRoute({"状态", "status"}, False, self._status),
            CommandRoute({"切模型"}, True, self._switch_model),
            # ...
        ]
```

## 8.1.1 Telegram 主程序托管适配器

**文件**: `clients/bots/telegram/adapter.py`、`clients/bots/telegram/session.py`、`core/lifecycle/lifespan.py`

- **启动模型**：`main.py` 的 FastAPI lifespan 根据 `config/yaml/app.yaml` 的 `telegram.enabled` 在主事件循环中托管，无需另开 Adapter 终端；QQ 的独立进程模式不变。
- **配置边界**：开关、语音/视觉能力、后端地址和超时位于 `app.yaml`；Bot Token、Master 用户 ID、代理等本机值来自 `.env`。遗留 `TELEGRAM_ENABLED` 不覆盖 `app.yaml`。
- **就绪语义**：只有 Telegram polling 已成功启动后才设置 ready 并输出“Telegram 轮询已启动，正在监听消息”，托管任务提交不等于启动成功。
- **可靠性**：监督循环对异常退出退避重启；WebSocket 未确认发送在重连后重试；空闲会话按 `session_timeout_minutes` 回收；退出时统一关闭 polling、会话和 HTTP 客户端。
- **路由顺序**：图片、语音 handler 先于文本 handler，命令文本也进入统一消息入口，避免媒体被宽泛过滤器截获。
- **独立脚本**：`clients/bots/scripts/start_telegram.ps1` 仅用于调试，不得与主程序托管的 polling 同时运行。

## 8.2 Web前端

**文件**: `clients/frontend/aveline-web/`

**状态管理**:

```typescript
interface AvelineState {
    messages: Message[];
    lifeStatus: any;
    persona: any;
    emotion: EmotionType;
    emotionMix: Record<string, number>;
    stats: Stats;
    isTyping: boolean;
    studyMode: boolean;
    autoTtsEnabled: boolean;
    replyDisplayMode: 'text_and_tts' | 'tts_only';
}
```

**WebSocket连接管理**:

```typescript
export function useWebSocket(options: UseWebSocketOptions = {}) {
    const connect = useCallback(() => {
        const wsUrl = `${wsBaseUrl}/api/v1/ws?token=${token}&user_id=${userId}`;
        const ws = new WebSocket(wsUrl);

        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === 'ping') {
                ws.send(JSON.stringify({ type: 'pong', timestamp: data.timestamp }));
                return;
            }
            onMessage(data);
        };
    }, []);

    // 自动重连（指数退避 + 抖动）
    const scheduleReconnect = useCallback(() => {
        const delay = Math.min(30000, base * Math.pow(1.5, attempt) + jitter);
        setTimeout(connect, delay);
    }, []);
}
```

***

## 8.3 Android 客户端 (Jetpack Compose)

**文件**: `clients/frontend/aveline-android/android/app/src/main/java/com/aveline/ai/mobile/`

**技术栈**: Jetpack Compose + Material3 + Kotlin 1.9.22 + Hilt 2.51.1 + Room 2.6.1 + Retrofit2 + Navigation Compose

**架构**: MVVM + Clean Architecture (di/domain/data/presentation/services/utils)

**6单元主导航架构** (统一风格,职责清晰):

| 单元 | 职责 | 关键文件 |
|------|------|---------|
| Chat | 聊天对话(WebSocket流式) | ChatScreen + ChatViewModel(307行,薄壳协调者) + 子模块(ChatSessionController/ChatSessionObserver/ChatSendController门面/ChatIncomingMessageHandler/ChatFlushManager/ChatUploadHelper/ChatTtsController/ChatVoiceInputController/ChatPeerChatHandler/ChatTextProcessor) + 发送流水线 `send/`(SendRuntime/SendPreflight/AssistantReplyStreamer/AssistantBubbleChain/AssistantReplyFinalizer/ConversationPreviewWriter/ReplyOutcomeNotifier/ChatUiWriteGuard) |
| Companion | 已合并到 Chat 内的伙伴详情面板,不再占用侧边栏单元 | CompanionScreen(3-tab: Status/Persona/Memory) |
| Study | 学习管理 + Daily文件夹适配 | StudyScreenV2(6-tab) + StudyViewModel + StudyDailyViewModel(195行) |
| Life | 日常生活(健康/饮食/日程/饮水) | LifeScreen(4-tab) |
| Wellbeing | 数字健康(本地实时用量/每日额度/单次额度+间隔与冷却/即时拦截状态) | WellbeingScreen + WellbeingViewModel + services/wellbeing(SessionLimiter) + UsageLimitMonitor + AvelineAccessibilityService |
| Mall | 商城(分类/购买/食用) + 库存(送出) | MallScreen + ShopViewModel + InventoryScreen + InventoryViewModel |
| Settings | 应用设置(5-tab: 常规/权限/隐私/数据/高级) | SettingsScreenV2 + 5个Tab文件 |

侧边栏由 Compose Foundation `AnchoredDraggableState` 统一驱动，主页直接拖拽与 Pager 第一页的边界剩余拖拽通过 `NestedScrollConnection` 写入同一实时偏移。慢拖使用 12% 位置阈值，轻甩使用 125dp/s 速度阈值；Route 接力仅在抽屉已产生实际位移时保存并使用 fling 速度，避免伴侣详情退出的同一手势串联打开侧栏。关闭态不组合全屏遮罩点击节点，避免阻断 NavHost 内容命中。`MainActivity` 不再使用全屏 `pointerInput`、Initial pass 抢占或透明边缘窗口。圈子前端 Route 和后端旧圈子服务均已移除，旧深链重定向到消息主页。数字健康通过 UsageEvents 计算精确区间用量，页面限额立即写本地。限额模型为四元组策略（每日额度 + 单次额度 + 会话间隔默认 2 分钟 + 冷却默认 5 分钟），由 `services/wellbeing/SessionLimiter` 会话状态机判定：无障碍服务跟踪前台并秒级轮询，是单次额度的主执行器；15 分钟 Worker 只兜底校验每日额度并清理过期会话。单次超限后进入冷却，冷却结束获得新的单次额度而每日额度不重置。

Android 端按窗口宽度自适应（`presentation/adaptive/AdaptiveLayout.kt`）：宽度 ≥600dp 且高度 ≥480dp 时使用 ChatGPT 平板页式的单一常驻侧栏 `ConversationSidebar`——品牌头、会话列表、底部模块入口、设置与连接状态都在同一个侧栏里，右侧是聊天 / 空状态 / 当前模块页；不再额外放图标导航栏，避免「图标栏 + 会话列表 + 聊天」三列挤压聊天区。侧栏宽度按窗口分 264 / 300 / 320dp 三档；点会话行把聊天页压在消息页之上，返回键回到未选角色的空态 `ConversationEmptyDetail`。窄窗口仍走 `PullableNavigationDrawer`。普通模块页在大屏上居中限宽 900dp。聊天页伴侣面板的手势阈值按聊天页实际占用宽度计算。

无障碍服务连接后会拉起 `AvelineForegroundServiceV2` 作为宿主保活。该 Service 只保留 Android 生命周期、Hilt 接线和子控制器编排；`services/foreground/` 将通知与启动协议、WebSocket 指令、上下文同步、Samsung Health 同步、无障碍监测、WakeLock 拆为独立组件。常驻通知使用 `ongoing + deleteIntent`：用户或系统划除后立即重新提交；拥有通知读取授权时，`AvelineNotificationService.onNotificationRemoved` 再覆盖厂商不触发 deleteIntent 的边缘情况。恢复前检查无障碍系统开关或常驻模式，二者均关闭时不拉起。此机制只能降低进程回收和通知消失概率，不能绕过系统重新授予无障碍权限。

聊天页内的伴侣详情由 `PullableDismissPanel` 包住完整 `Surface`，使用相同的 `AnchoredDraggableState + NestedScrollConnection` 接收第一个 Companion Tab 的边界剩余右滑并实时平移整个页面，退出位置阈值为 12%；旧的全屏 `pointerInput`、`Animatable + Channel` 和禁用 Pager 方案已删除。

Android 模型页优先恢复用户保存在 AppPreferences 的模型 id 和完整 path，未手动选择时才使用 `/api/v1/models.selected_model_id`；无法匹配时保持未选择，不回退列表第一项。HTTP 普通、SSE 和非流式回退请求统一显式携带保存的完整路由，避免角色默认模型覆盖选择。WebSocket 切换仍使用协议字段 `model`。人设版本按角色保存，列表和聊天入口均优先恢复该选择；后端确认切换成功后同步 pendingSwitch、面板、本地 session 和请求的 profile_filename。发送前等待人设切换完成，从目标会话读取历史，失败时停止发送并允许重试。

Android 商城由单例 `ShopRepositoryImpl` 按类目缓存分页快照，`ShopViewModel` 重建后同步恢复商品、分页和余额。缓存新鲜期为 10 分钟；过期时保留旧列表后台更新，切到没有缓存的类目则先清空列表，避免新 Tab 下短暂显示上一类目商品。商品列表与礼物库存是两个目的地：商城页只负责商品与购买 / 食用底部面板，库存页由 `InventoryViewModel` 独立加载，每行一个「送出」。

Android 背单词的长期进度由后端 FSRS 与 daily 错词文件持久化；后端按日持久化历史补漏候选及其与 FSRS 合并后的最终固定队列，只有从未进入进度或 daily 记录晚于最后复习的词才参与补漏，同日完成后未入选词不会补位。App 评分为 `1=Again, 2=Hard, 3=Good, 4=Easy`；FSRS v2 关闭与每日固定队列冲突的分钟级学习/重学步骤，Again/Hard 由 daily 次日优先承接，Good/Easy 进入长期天级间隔。本轮三次强化属于客户端会话状态。`StudyVocabSessionStore` 使用应用私有 SharedPreferences 保存动态卡片队列、当前索引、Again 重排次数和本轮结果；v3 快照会拒绝修复前的旧错误队列，但不影响已上传的 FSRS 评分。`StudyViewModel` 冷启动优先恢复有效快照，复习与背新词入口分别续接对应模式，完整结算后再清理，避免 App 重启丢失剩余强化轮次。

**统一组件**:
- `ModuleHeader` - 统一页头(标题+副标题+操作按钮容器),副标题用TextSecondary
- `ModuleHeaderActionContainer` - 统一操作按钮背景(14dp圆角+半透明黑)
- `SectionCard` - 统一分区卡片(16dp圆角+CardBackground+CardBorder+可折叠+图标+副标题)
- `MetricRow` - 统一指标行(标签:值对齐)

**Study/Daily API适配** (后端→客户端全链路):
- 后端: `routers/v1/study_daily.py`（聚合入口；子域 `study_daily_content/notes/plan/shared.py`）：7 个 GET（calendar / date/{date} / notes / notes/{filename} / library / library/note / latest-progress）+ 4 个计划项 POST（`plan/item/status|add|update|remove`，写回计划真源 plan.json 后派生 plan.md）
- API层: `StudyDailyApiService` 接口(从AvelineApiService拆出,AvelineApiService继承之)
- Model层: `StudyDailyModels.kt` (CalendarDay/DailyContent/DailyNote/DailyNoteContent/LatestProgress/PlanItem)
- Repository层: `StudyRepository` + `StudyRepositoryImpl` (snake_case→camelCase映射)
- ViewModel层: `StudyDailyViewModel` (独立文件,init自动加载当月日历和最新进度)
- View层: 4个Tab(Plan/Diary/Notes/Overview)优先使用后端数据,placeholder保留为后备

**API服务拆分** (避免单文件超500行):
- `AvelineApiService` (468行) - 主API接口,继承StudyDailyApiService
- `StudyDailyApiService` (53行) - Study/Daily专用接口

***

## 8.4 多QQ独立角色架构 (N-Role Independent Roles)

> **3.7.0 升级**：从硬编码双角色（aveline/ling）改造为动态 N 角色系统，支持 3-4+ 个角色两两互聊。

N 个角色从"同账号前台/后台切换"升级为"多QQ独立运行"：
在 `stream_generate_response` 中：

1. 所有角色（aveline/ling/...）分别运行在独立的 QQ 号上，各自直接对用户对话，不再需要前台/后台切换。
2. 后台建议注入已移除（原 `DualRoleCoordinator` 的建议注入从未实际接入主链路）。
3. 旧后台圈子已删除；角色间自动互聊统一由 Peer Chat 调度，不再重复写入圈子存储或自动抬高 `social_events` 关系热度。
4. 多QQ适配器（`dual_qq_adapter.py`）在单进程内运行 N 个 `QQAdapter` 实例，各自连接不同 NapCatQQ。
5. 配置对象化：`QQAdapterConfig` 封装所有 per-instance 配置，`QQAdapter` 和 `AutarkiaSession` 从 `self.cfg` / `self._cfg` 读取。
6. 仿生系统仍采用单引擎多角色状态池：`LifeSimulationService` 维护 `actor_life_states/actor_relationships`。
7. QQ 人设上下文隔离：消息链路透传 `profile_filename`，按 `{session_id}__persona__{persona}` 构造 `conversation_id`。
8. 角色关系评估保留：`dual_role/social_events.py` 按 `dual_role` 配置计算关系状态。
9. **数据隔离（统一 scope）**：每个角色在 persona JSON 的 `meta.scope` 声明稳定英文 snake_case 标识，并唯一存放在 `companion_data/{scope}_data/`。`core/utils/data/scope_registry.py` 自动扫描配置，把中文文件名、显示名、英文名和历史别名解析回同一个 scope；`core/utils/data/data_paths.py` 及旧兼容导入均委托该注册表，不再各自维护角色白名单。新增角色只需声明 `meta.scope`，无需修改 Python 映射；未知 persona 会进入稳定隔离 scope 并告警，不会直接创建中文目录。`scripts/migrate/merge_persona_scope_dirs.py` 用于预览或安全合并历史别名目录，冲突文件不覆盖。
10. Peer Chat 成功后只写普通日记摘要和 `peer_{role_id}` 原始会话记录；不再产生圈子专属日记副本或逐句社交事件。
11. `SocialEventEngine` 统计用户自述与 Samsung Health 产生的可共享生活事件；事件保存 `source`、`learned_by`、`certainty`，历史 `background_circle` 继续兼容读取但不参与关系热度和证据计算。
12. 历史圈子数据保留在磁盘作为归档，运行时代码不再读取或继续生成。
13. Active Care 支持按会话人设路由，主动关怀运行状态存储到 `companion_data/active_care/{persona_scope}` 实现角色隔离。
14. 历史分层规则收敛：`history/` 作为原始记忆层，`companion_data/` 作为可读业务层。
15. 睡眠语义分层：聊天中的晚安/清醒陈述只切换低打扰；即时入口按 `reason/label` 严格区分学习专注与晚安，只有 `goodnight/sleep` 可供 nightly 判睡；`WAKEUP_NOW` 必须由明确的当前起床陈述确认，不能由零样本 BERT 单独改状态。Samsung Health 时间戳才写正式睡眠区间，主睡眠更新当天起床，午睡记为 `nap` 且不覆盖主睡眠。
16. 睡醒、饮食等共享生活事件只作为 Peer Chat 可选题材；跨角色使用时必须保留最先知情角色与数据来源，可以选择自然转告，也可以不触发互聊。

### N 角色权威源（personas.py）

`core/services/dual_role/personas.py` 是角色定义的唯一权威源，所有模块一律 import，禁止在各模块内重新硬编码角色名/性格/关系描述。

**N 角色 API**：
- `get_all_role_ids()` — 返回所有已注册角色的 role_id 列表（按定义顺序）
- `get_peer_role_ids(role_id)` — 返回除自己外所有 peer 列表（N 角色两两互聊用）
- `get_peer_role_id(role_id)` — 向后兼容接口，N>2 时返回第一个 peer 并 warning，新代码应改用 `get_peer_role_ids()`
- `get_persona(role_id)` / `get_persona_by_name(name)` — 按role_id或任意写法名字查画像
- `get_peer_profiles()` — 返回 `PeerChatManager.PEER_PROFILES` 兼容格式（动态生成）

**新增角色只需 3 步**：
1. 在 `personas.py` 加 `PersonaProfile` 定义并注册到 `PERSONAS` 字典
2. 配 `core_{role_id}.json` 人设文件
3. 在 `clients/bots/multi_qq_config.json` 加角色配置 + 设置 `AUTARKIA_QQ_BOT_NUMBER_{ROLE_ID_UPPER}` env var

### N 角色 QQ 号 env var 命名规范

`dual_qq_adapter.py` 和 `config/settings_adapters.py` 支持通用 env var 命名规范：

| Env Var | 角色 | 向后兼容 |
|---------|------|---------|
| `AUTARKIA_QQ_BOT_NUMBER` | aveline | ✅ 旧名保留 |
| `AUTARKIA_QQ_BOT_NUMBER_LING` | ling | ✅ 旧名保留 |
| `AUTARKIA_QQ_BOT_NUMBER_{ROLE_ID_UPPER}` | 任意新角色 | 🆕 通用规范（如 `AUTARKIA_QQ_BOT_NUMBER_XIAOLU`） |

适配器启动时扫描 `os.environ` 自动收集所有 `AUTARKIA_QQ_BOT_NUMBER_*` env var，按 role_id（去掉前缀转小写）归位。`peer_qq_id` 自动填充改为取第一个其他角色的 QQ 号（N 角色真正的多 peer 解析在 peer_chat_scheduler 里从 config 动态读）。

## 8.5 N 角色互聊 Peer Script 架构

> **3.7.0 升级**：从双角色互聊升级为 N 角色两两互聊，peer_chat_scheduler 遍历 `get_peer_role_ids()` 动态选 peer。

N 角色互聊（Peer Chat）允许任意两个角色自动生成对话剧本并分发到各自的QQ。

### 消息标识
Peer Script 消息通过 `extra_payload` 元数据标识，不使用内容前缀：
```python
extra_payload = {
    "target_qq_id": "目标QQ号",       # 消息发送到哪个QQ
    "is_peer_script": True,            # 兼容标记
    "message_type": "peer_script"      # 统一消息类型标识
}
```

### 分发流程
```
Active Care ProactiveChecker 决策触发
    │
    ▼
peer_chat_scheduler._check_and_trigger_for_role(role_id)
    ├── get_peer_role_ids(role_id)  # 获取所有 peer（N 角色两两互聊）
    ├── 遍历 peer 列表，选第一个非睡眠且有 qq_id 的 peer
    │
    ▼
executor.generate_peer_script()
    ├── 读取 dual_qq_config.json（一次读取，复用配置）
    ├── 获取主人聊天记录 + 历史互聊记录
    ├── LLM 生成剧本 JSON（DeepSeek）
    ├── 解析剧本（PeerChatManager.parse_script）
    └── 逐条分发（通过 WebSocket 广播）
         ├── role_id 说的话  → target_cid=role_cid, target_qq=peer_role_qq_id
         ├── peer 说的话     → target_cid=peer_cid, target_qq=role_qq_id
         └── 提及主人        → target_cid=role_cid, target_qq=master_qq_id
              │
              ▼
         QQ Adapter Session 收到 proactive_message
              ├── 检测 is_peer_script / message_type == "peer_script"
              ├── 直接 adapter.send_to_napcat(peer_{target_qq_id}, content)
              └── continue 跳过（不触发AI回复）
```

### 关键文件
| 文件 | 职责 |
|------|------|
| `core/services/dual_role/personas.py` | 角色定义唯一权威源，N 角色 API（get_all_role_ids/get_peer_role_ids） |
| `core/utils/data/scope_registry.py` | 扫描 persona `meta.scope`，统一文件名、显示名、英文名和历史别名到稳定 scope |
| `core/utils/data/data_paths.py` | 数据目录门面；所有 scope 解析委托统一注册表，并保留旧导入兼容 |
| `core/services/active_care/core/executor.py` | 剧本生成与分发 |
| `core/services/active_care/core/proactive_checker.py` | Peer Chat 触发决策 |
| `core/services/active_care/peer_chat/peer_chat_scheduler.py` | N 角色 peer 调度（遍历 get_peer_role_ids 选可用 peer） |
| `clients/bots/qq/peer_chat.py` | PeerChatManager 角色配置（从 personas 动态加载）、解析、延迟 |
| `clients/bots/qq/session/session.py` | 剧本消息接收与转发 |
| `clients/bots/multi_qq_adapter.py` | 多QQ适配器入口，扫描 AUTARKIA_QQ_BOT_NUMBER_* env var |
| `core/tools/message_peer_tool.py` | LLM 工具：主动给 peer 发消息（动态角色名映射） |
| `core/agents/chat_agent_components/persona_system/prompt/qq_peer_context.py` | 剧本生成prompt |

### 角色配置
角色配置动态从 `core/services/dual_role/personas.py` 加载（`PeerChatManager.PEER_PROFILES` 通过 `get_peer_profiles()` 动态生成），包含性格、说话风格、关系描述。`clients/bots/multi_qq_config.json` 配置QQ号、profile_filename 等运行时参数，新增角色只需在该文件加一项配置即可。
