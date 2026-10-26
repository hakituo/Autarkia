# UI 导航

> Android 端子文档 · 上级入口：[README.md](../README.md)
> 只写当前实现；改代码前先看 `.trae/context/routing/android.md` 定位文件。

---

## UI 导航

```
AvelineApp (ModalNavigationDrawer + BreathingBackground + NavHost)
├── ConversationListScreen (默认路由, aveline://conversations)
├── ChatScreen             (aveline://chat)
├── StudyScreenV2          (aveline://study)
├── LifeScreen             (aveline://life)
├── MallScreen             (aveline://food / aveline://mall)
│   └── InventoryScreen    (inventory)
├── WellbeingScreen        (aveline://wellbeing)
└── SettingsScreenV2       (aveline://settings)
```

主页面支持 DeepLink（`aveline://` 协议），可从外部直接跳转。旧版 `circle` 深链已退役并兼容重定向到消息主页。

侧边栏由 Compose Foundation `AnchoredDraggableState` 驱动，主页直接拖拽和 `HorizontalPager` 第一页的边界剩余拖拽共用同一份实时偏移；侧栏与遮罩随手指连续移动，松手后按距离和速度吸附展开或收回。抽屉只有产生实际位移后才接受本次 fling，避免伴侣详情等内层页面退出时把同一甩动继续传成侧栏打开。`MainActivity` 不再使用全屏 `pointerInput` 或透明边缘窗口抢占触摸事件；关闭态也不会创建遮罩点击层，主页内容可直接命中。

聊天页内的伴侣详情采用相同的锚点拖拽与 `NestedScroll` 接力：聊天页左滑进入和详情页右滑退出都直接驱动同一份面板实时偏移，页面随手指连续移动，松手后才按距离与速度吸附展开或收回。内层 Pager 采用逐层手势：从人设等页面右滑只切换到前一个 Tab，必须先松手并稳定停在“状态”，下一次新右滑才允许外层详情面板退出到聊天页。

学习、生活、伴侣详情与设置 Route 的顶部 Tab 共用纯文字选中态：不绘制蓝色下划线、胶囊底色或边框，仅用文字亮度与字重区分，并强制单行显示，避免窄屏标签竖排。

聊天 AI 消息使用整行 Markdown 富文本排版，支持标题、列表、多层引用、代码块、GFM 表格以及 `$...$` / `$$...$$` LaTeX 数学公式。超宽表格、代码块和块级公式可在消息内部横向滚动；内层内容已消费横向拖动时，聊天页不会把同一次手势解释为打开伴侣详情。

聊天消息使用持久化对话树而非覆盖式重新生成：`messages.parentId` 表示父消息，同一父消息和角色下的记录按 `variantIndex` 组成版本组，`isActiveVariant` 决定当前显示分支。点击 AI 消息可重新生成，点击用户消息可编辑并从该位置创建新分支；存在多个版本时显示 `当前 / 总数` 及左右切换按钮。Android 每次生成都会把当前选中路径作为 `history_override` 传给聊天接口，确保切换旧版本后继续对话时，模型使用的是可见分支而非服务端线性历史。

聊天记录长期保存在 Room，发送和回复完成不再按 200 条自动删除。聊天页复用上滑加载交互，首屏读取最近 50 条正文，每次向上扩展 50 条；路径选择只读取不含正文与媒体的轻量索引，正文按窗口 ID 分批查询。普通发送独立读取当前分支最近 200 条作为上下文，编辑和重新生成读取目标消息所在分支前缀；页面窗口大小不会改变上下文来源。索引目前仍按会话全量读取，长会话的索引开销与节点数成正比。

角色会话首次复用旧 `role -> sessionId` 映射，再绑定稳定的 persona filename 别名；后端 role 名称变化时优先恢复该别名，列表预览、主动消息和发送使用同一映射。已经分裂的两个容器不自动合并。后台回复更新仅拥有内容更新权，保留当前父链与版本选择；历史 API 只在返回时本地仍为空的事务中初始化。已有根或多个断链入口不再按时间自动改写根。回归用例为 `RoleSessionIdentityTest`、`ChatHistoryPersistenceTest`；本次待 Android Studio 编译与设备验收。

主动消息（Active Care）的归属解析是三源兜底：payload 的 `profile_filename` → 本地会话反查（`persona_session:*`，锚定后端真正投递的那个会话）→ 该角色当前选中的人设；`conversation_id` 同时支持 QQ / shared 侧的 `__persona__` 后缀与 App 自己的 `web_role_<slug>` 会话 id。三者都拿不到才走「仅提醒不归档」。此前只认「payload 带 filename」和「cid 带 `__persona__`」两条路，而后端单 persona 模式下两者都不给、target 又恰好是 App 会话 id，于是整条消息被丢弃 —— 表现为「有通知，点进去却没有这条消息」。回归用例为 `WebSocketCommandCoordinatorRoleTest`、`PersonaSessionIndexTest`。

伴侣详情和设置页优先恢复手机明确保存的模型选择，尚未选择时才显示后端 `/api/v1/models` 返回的默认模型；列表项的 `path` 用于实际调用。HTTP/SSE 与非流式回退均携带保存的完整路由，WebSocket 的 `model` 字段也使用实际路由。角色默认模型或页面重建不会覆盖手动选择，接口无法匹配时保持“未选择”。

商城商品采用 Repository 单例内存快照缓存，按“全部/各类目”分别保存已加载分页、余额和更新时间。商城 Route 或 ViewModel 重建时同步恢复快照，10 分钟内不重复请求；缓存过期时保留当前商品、仅在后台更新。切换类目会取消旧类目的加载与翻页任务，避免过期响应覆盖当前页面；切到没有缓存的类目先清空列表，不让新 Tab 短暂显示上一类目商品。库存是独立目的地（`inventory`），由 `InventoryViewModel` 单独加载礼物库存，返回商城时列表与滚动位置保留。
