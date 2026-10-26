# 工程目录结构

> Android 端子文档 · 上级入口：[README.md](../README.md)
> 只写当前实现；改代码前先看 `.trae/context/routing/android.md` 定位文件。

---

## 项目结构

```
android/app/src/main/java/com/aveline/ai/
├── AvelineApplication.kt              # @HiltAndroidApp 入口，初始化CrashHandler/通知渠道/性能监控
├── HealthManager.kt                   # Health Connect 数据读取管理器
│
└── mobile/
    ├── di/                            # 依赖注入模块
    │   ├── AppModule.kt               #   Context / Resources / LocationProvider
    │   ├── NetworkModule.kt           #   Json / 拦截器 / OkHttpClient / Retrofit / ApiService / WebSocket
    │   ├── DatabaseModule.kt          #   Room数据库 / 5个DAO
    │   └── RepositoryModule.kt        #   11个 @Binds 绑定
    │
    ├── domain/                        # 领域层（纯Kotlin，无框架依赖）
    │   ├── models/                    #   领域模型
    │   │   ├── Message.kt             #     聊天消息
    │   │   ├── Session.kt             #     会话
    │   │   ├── Emotion.kt             #     情绪状态（含预定义常量）
    │   │   ├── LifeStatus.kt          #     AI生命状态（健康/饥饿/幸福/能量）
    │   │   ├── Memory.kt              #     记忆（含类型/重要性/排序/过滤）
    │   │   ├── Persona.kt             #     人格（含5个预设模板）
    │   │   ├── HealthData.kt          #     健康数据（步数/心率/血氧/睡眠等）
    │   │   ├── DeviceContext.kt        #     设备上下文（电池/网络/亮度/音量等）
    │   │   ├── PhoneAction.kt         #     手机操作指令（sealed class, 13种操作）
    │   │   ├── ShopItem.kt            #     商店物品
    │   │   ├── StudyFile.kt           #     学习文件
    │   │   ├── PluginSettings.kt      #     插件设置
    │   │   ├── FoodModels.kt          #     食物模型
    │   │   ├── IntentModels.kt        #     意图分类模型
    │   │   ├── NotificationModels.kt  #     通知模型
    │   │   └── SystemModels.kt        #     系统模型
    │   │
    │   └── repository/                #   Repository接口
    │       ├── ChatRepository.kt
    │       ├── SessionRepository.kt
    │       ├── StatusRepository.kt
    │       ├── HealthRepository.kt
    │       ├── ContextRepository.kt
    │       ├── MemoryRepository.kt
    │       ├── StudyRepository.kt
    │       ├── PersonaRepository.kt
    │       ├── PluginsRepository.kt
    │       ├── ShopRepository.kt
    │       └── ToolsRepository.kt
    │
    ├── data/                          # 数据层
    │   ├── remote/
    │   │   ├── api/
    │   │   │   ├── AvelineApiService.kt    # Retrofit接口，50+ REST端点
    │   │   │   ├── WebSocketManager.kt     # WebSocket连接/重连/心跳，指数退避策略
    │   │   │   └── WebSocketMessage.kt     # 消息类型（sealed class, 15+种）
    │   │   └── dto/                        # 网络传输对象 (18个)
    │   │       ├── MessageRequest.kt / MessageResponse.kt
    │   │       ├── SessionResponse.kt
    │   │       ├── LifeStatusResponse.kt
    │   │       ├── ContextSyncRequest.kt
    │   │       ├── MemoryDto.kt
    │   │       ├── PersonaDto.kt
    │   │       ├── ModelDto.kt
    │   │       ├── TTSRequest.kt / VoicesResponse.kt
    │   │       ├── UploadResponse.kt
    │   │       ├── ImageDtos.kt / VisionDtos.kt
    │   │       ├── FoodDtos.kt / ShopDto.kt
    │   │       ├── StudyFileDto.kt
    │   │       ├── IntentDtos.kt / NotificationDtos.kt / SystemDtos.kt
    │   │       └── MarkImportantRequest.kt
    │   │
    │   ├── local/
    │   │   ├── database/                   # Room数据库
    │   │   │   ├── AvelineDatabase.kt      #   数据库定义 (v1, 5个Entity)
    │   │   │   ├── dao/                    #   MessageDao / SessionDao / MemoryDao
    │   │   │   └── entity/                 #   MessageEntity / SessionEntity / MemoryEntity
    │   │   ├── db/                         # 扩展数据库组件
    │   │   │   ├── dao/                    #   HealthDataDao / NotificationDao
    │   │   │   └── entity/                 #   HealthDataEntity / NotificationEntity
    │   │   └── preferences/
    │   │       └── AppPreferences.kt       # SharedPreferences封装 (17+配置项)
    │   │                                    #   accessToken使用EncryptedSharedPreferences (AES256)
    │   │
    │   └── repository/                    # Repository实现 (11个)
    │       ├── ChatRepositoryImpl.kt
    │       ├── SessionRepositoryImpl.kt
    │       ├── StatusRepositoryImpl.kt
    │       ├── HealthRepositoryImpl.kt
    │       ├── ContextRepositoryImpl.kt
    │       ├── MemoryRepositoryImpl.kt
    │       ├── StudyRepositoryImpl.kt
    │       ├── PersonaRepositoryImpl.kt
    │       ├── PluginsRepositoryImpl.kt
    │       ├── ShopRepositoryImpl.kt
    │       └── ToolsRepositoryImpl.kt
    │
    ├── presentation/                  # UI层
    │   ├── MainActivity.kt            #   @AndroidEntryPoint 主入口
    │   ├── MainViewModel.kt           #   @HiltViewModel 主ViewModel
    │   ├── navigation/
    │   │   └── NavGraph.kt            #   主页面路由与 DeepLink (aveline://)
    │   │
    │   ├── adaptive/                  #   窗口自适应（平板常驻侧栏 / 内容限宽）
    │   │   └── AdaptiveLayout.kt       #     宽度档位与侧栏宽度
    │   ├── chat/                      #   聊天（核心页面）
    │   │   ├── ChatScreen.kt          #     纯组装层：收集状态 + 拼装下面各子组件
    │   │   ├── ChatTopBar.kt          #     顶栏（返回 + 头像 + 昵称）
    │   │   ├── ChatMessageList.kt     #     消息列表 / 时间分隔 / 旁白 / 空状态
    │   │   ├── ChatPeerChatArea.kt    #     双角色对话折叠区
    │   │   ├── ChatInputBars.kt       #     底部输入栏 + 待发送图片/视频条 + 上传进度
    │   │   ├── ChatCompanionPanel.kt  #     伴侣详情全屏覆盖面板
    │   │   ├── ChatCompanionPanelGesture.kt  # 左滑打开伴侣面板的手势 Modifier
    │   │   ├── ChatEditMessageDialog.kt      # 编辑已发消息的对话框
    │   │   ├── ChatMediaPickers.kt    #     图片/视频/文件/录音权限选择入口
    │   │   ├── ChatPersonaTitle.kt    #     顶栏 persona 展示信息解析（标题/头像）
    │   │   ├── ChatViewModel.kt       #     薄壳协调者：组装各 Chat*Controller/Handler
    │   │   ├── ChatSessionController.kt      # 角色(persona)/会话(session)切换
    │   │   ├── ChatSessionObserver.kt        # 会话与消息流观察、WS 事件分发
    │   │   ├── ChatSendController.kt         # 发消息主流程（HTTP SSE 流式）
    │   │   ├── ChatIncomingMessageHandler.kt # WS 消息落库 + 会话列表预览
    │   │   ├── ChatFlushManager.kt    #     流式响应批量刷新
    │   │   ├── ChatUploadHelper.kt    #     文件/图片上传与图片视觉识别
    │   │   ├── ChatTtsController.kt   #     TTS 播报（跟随当前对话角色）
    │   │   ├── ChatVoiceInputController.kt   # 语音输入
    │   │   ├── ChatPeerChatHandler.kt #     双角色对话
    │   │   ├── ChatTextProcessor.kt   #     消息文本处理
    │   │   ├── ChatPreviewBuilder.kt  #     会话列表预览文本
    │   │   ├── ImageMessageText.kt    #     图片消息文本渲染
    │   │   └── VideoMessageText.kt    #     视频消息文本渲染
    │   │   ├── ChatUiState.kt         #     聊天页 UI 状态
    │   │   └── ChatAvatarStorageHolder.kt    # 顶栏头像数据持有者
    │   ├── status/                    #   AI生命状态展示
    │   ├── health/                    #   每日数据（健康+上下文+饮水+学习）
    │   ├── memory/                    #   记忆搜索/过滤/排序/标记重要
    │   ├── study/                     #   学习文件/学习模式/词汇复习
    │   ├── persona/                   #   人格切换
    │   ├── shop/                      #   商店
    │   ├── plugins/                   #   模型/情绪/学习模式/敏感词设置
    │   ├── tools/                     #   图像生成/视觉/食物/通知/系统
    │   └── settings/                  #   后端URL/Token/模型/语音/常驻模式等
    │
    │   ├── components/                #   共享UI组件
    │   │   ├── BreathingBackground.kt #     呼吸灯背景（情绪颜色联动）
    │   │   ├── DrawerContent.kt       #     侧边抽屉导航
    │   │   ├── InputArea.kt           #     消息输入区域
    │   │   ├── MessageBubble.kt       #     消息气泡
    │   │   ├── SessionDialogs.kt      #     会话操作对话框
    │   │   ├── TTSComponents.kt       #     TTS播放控制
    │   │   ├── TypingIndicator.kt     #     打字指示器
    │   │   ├── VoiceInputComponents.kt#     语音输入
    │   │   ├── ModuleHeader.kt        #     模块标题
    │   │   └── TimeSeparator.kt       #     时间分隔线
    │   │
    │   ├── theme/                     #   主题系统
    │   │   ├── Color.kt               #     颜色常量
    │   │   ├── EmotionColorMapping.kt #     情绪→颜色映射
    │   │   ├── Theme.kt               #     AvelineTheme (暗色主题)
    │   │   └── Typography.kt          #     字体排版
    │   │
    │   └── utils/
    │       └── EmotionResolver.kt     #     情绪解析工具
    │
    ├── services/                      # 服务层
    │   ├── AvelineForegroundServiceV2.kt   # 前台服务薄壳：生命周期与子控制器编排
    │   ├── foreground/                     # 前台保活子系统
    │   │   ├── ForegroundServiceContract.kt       # 启停/通知恢复 Intent 协议
    │   │   ├── ForegroundNotificationController.kt# 通知渠道、创建与发布
    │   │   ├── WebSocketCommandCoordinator.kt     # 消息监听与设备指令
    │   │   ├── ContextSyncController.kt            # 五分钟上下文同步
    │   │   ├── SamsungHealthSyncController.kt      # 三档健康同步
    │   │   ├── AccessibilityMonitor.kt             # 无障碍断线监测
    │   │   └── ResidentPowerController.kt          # WakeLock 生命周期
    │   ├── PhoneActionExecutor.kt          # @Singleton：执行13种手机操作指令
    │   ├── TTSEngine.kt                    # TTS语音合成引擎
    │   ├── VoiceInputManager.kt            # 语音输入管理器
    │   ├── FileUploadManager.kt            # 文件上传管理器
    │   ├── AvelineNotificationManager.kt   # 通知渠道管理
    │   ├── AvelineNotificationService.kt   # NotificationListenerService
    │   ├── AvelineFirebaseMessagingService.kt # FCM推送
    │   ├── BootCompletedReceiver.kt        # 开机自启
    │   ├── discovery/
    │   │   └── ServerDiscoveryManager.kt   # @Singleton：UDP广播+网段扫描，零配置发现
    │   └── worker/
    │       ├── DataSyncManager.kt          # @Singleton：WorkManager周期同步(15min)
    │       └── DataSyncWorker.kt           # 实际同步Worker
    │
    └── utils/                         # 工具类
        ├── CrashHandler.kt            #   全局未捕获异常处理
        ├── ErrorHandler.kt            #   统一错误处理
        ├── PerformanceMonitor.kt      #   性能监控
        ├── SecurityManager.kt         #   安全管理（XSS防护等）
        ├── InputValidator.kt          #   输入校验
        ├── RetryUtils.kt             #   重试工具（指数退避）
        ├── LanguageManager.kt         #   国际化管理
        ├── HapticFeedbackManager.kt   #   触觉反馈
        ├── AccessibilityManager.kt    #   无障碍功能
        ├── CoilImageLoader.kt         #   Coil图片加载配置
        ├── DataExportManager.kt       #   数据导出
        ├── DeepLinkHandler.kt         #   DeepLink处理
        ├── ShareUtils.kt             #   分享工具
        └── StateManager.kt           #   状态管理
```
