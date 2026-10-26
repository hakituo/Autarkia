# 文件 IO 与数据存储

本分类由 `update_project_records.py` 自动维护，新记录追加到末尾。
如需时间倒序查看，请运行 `scripts/doc_records/split_question_reviewer.py` 重新整理。

---

### QR-20260720-ATOMIC-IO-TEMP-LEAK atomic_io.py 临时文件泄漏：进程崩溃时 .tmp_* 残留无自动清理机制 (2026-07-20)
*   **问题描述**: companion_data/aveline_data/memories/short_term 目录堆积 12 个 .tmp_* 临时文件，约 24MB 垃圾，时间跨度 2026-06-24 到 2026-07-19（近 1 个月）。safe_json_dump 的 except 块虽然有清理逻辑，但进程在写入过程中被强制终止时（Ctrl+C、任务管理器结束进程等），临时文件会残留且无机制自动清理。
*   **复现步骤**:
    1. 运行 inspect_short_term.py 列出 short_term 目录
    2. 发现 12 个 .tmp_* 临时文件残留，时间跨度近 1 个月
    3. 阅读 core/utils/atomic_io.py:116-168 的 safe_json_dump 实现
    4. 确认 except PermissionError 和 except Exception 块都有清理临时文件逻辑
    5. 但若进程在 open(temp_path, 'w') 之后、os.replace 之前被强制终止，临时文件会残留
    6. 且没有启动时清理或写入前清理的机制
*   **预期行为**:
    1. 进程崩溃后残留的临时文件应该在下一次写入时被自动清理
    2. 不应该误删其他线程正在写入的临时文件
    3. 不应该误删其他文件的临时文件
    4. 清理失败不应影响主写入流程
*   **实际行为**:
    1. 12 个 .tmp_* 临时文件堆积近 1 个月，约 24MB 垃圾
    2. 无自动清理机制，只能人工删除
*   **根因**:
    1. safe_json_dump 的 except 块只在异常路径清理临时文件
    2. 进程被强制终止时根本来不及进入 except 块
    3. 缺少启动时或写入前的陈旧临时文件清理机制
*   **修复方案**:
    1. 新增 _STALE_TEMP_FILE_TTL_SECONDS = 300 常量
    2. 新增 _cleanup_stale_temp_files(file_path) 函数，清理同前缀、修改时间超过 5 分钟的临时文件
    3. 在 safe_json_dump 和 async_safe_json_dump 的 _generate_temp_path 之前调用 _cleanup_stale_temp_files
    4. _cleanup_stale_temp_files 用 try/except 包裹，异常时静默失败不影响主流程
*   **验证**:
    1. `tests/scripts/memory/verify_atomic_io_cleanup.py 8 个测试全部 PASS`
    2. `覆盖场景：陈旧文件清理、近期文件保留、只清理同前缀、正常写入不受影响、async 版本、目录异常`

### QR-20260801-SOCIAL-EVENTS-PATH-BUG social_events.py 路径少算一级：社交事件被错误写入 core/companion_data/ 而非项目根 companion_data/ (2026-08-01)
*   **问题描述**: 用户发现 D:\AI\xiaoyou-core 下同时存在 companion_data/dual_role 与 core/companion_data/dual_role 两个目录，且 core/companion_data/dual_role/social_events/default.json 里有 4 条较新事件，正确路径下的 default.json 有 24 条历史事件。UPDATES.md/Question_Reviewer 全无迁移记录。
*   **复现步骤**:
    1. 执行 LS D:\AI\xiaoyou-core\core\companion_data 与 LS D:\AI\xiaoyou-core\companion_data，确认两个 dual_role 目录同时存在
    2. Read 两个 default.json，发现内容不同（脏路径 4 条较新事件，正确路径 24 条历史事件）
    3. Grep 'companion_data.*dual_role' 在 core/ 下找到 4 处引用，其中 social_events.py:21-23 用 project_root 拼 _social_events_dir
    4. Read social_events.py:590-592 发现 _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))，少算一级
    5. 对照 core/utils/common.py:30 get_project_root() 用 Path(__file__).resolve().parents[2]（common.py 在 core/utils/ 2 级深，parents[2] 正确到项目根），但 social_events.py 在 core/services/dual_role/ 3 级深，照搬 2 级就出错
    6. 对照 core/utils/data_paths.py:675-677 已有 get_dual_role_data_dir() 规范函数，social_events.py 完全没用，违反'不要重复造轮子'规则
*   **预期行为**:
    1. 社交事件数据应统一写入项目根目录的 companion_data/dual_role/social_events/，与文档（DECISION_TREE.md:516、TECHNICAL_REFERENCE.md:2458、README.md:150）一致
    2. core/ 目录下不应出现 companion_data 子目录
    3. 代码应复用 get_dual_role_data_dir() 规范函数而非手搓路径
*   **实际行为**:
    1. core/companion_data/dual_role/social_events/default.json 出现 4 条新事件（ts=1785502237 系列）
    2. 正确路径 companion_data/dual_role/social_events/default.json 保留 24 条历史事件但不再追加新事件
    3. 数据分裂：_persist_events 覆盖写 + 只留 24 条，导致正确路径数据被'冻结'在历史状态
*   **根因**:
    1. social_events.py 位于 core/services/dual_role/（3 级深），但代码用 ../..（2 级）计算 project_root，结果只到 core/ 而非项目根
    2. _social_events_dir 用错误的 project_root 拼 'companion_data/dual_role/social_events'，最终指向 core/companion_data/dual_role/social_events
    3. 未复用项目已有的 get_dual_role_data_dir() 规范函数
    4. _persist_events 覆盖写策略使正确路径文件不再被更新，掩盖了 bug（不会报错，只是数据被写到错的地方）
*   **修复方案**:
    1. social_events.py 顶部导入 from core.utils.data_paths import get_dual_role_data_dir
    2. _social_events_dir 改为 str(get_dual_role_data_dir() / 'social_events')，project_root 参数保留但不再用于路径计算
    3. get_social_event_engine() 单例工厂删除错误的 _project_root 计算，传空字符串占位
    4. 新增 tests/scripts/dual_role/merge_social_events_path_bug_fix.py 一次性脚本：备份 → 按 ts 去重合并 → 写回正确路径 → 删除 core/companion_data 脏目录
*   **验证**:
    1. `ruff check social_events.py 与 merge_social_events_path_bug_fix.py 全部通过`
    2. `运行 merge 脚本：正确 24 条 + 错误 4 条 → 去重 27 条 → 写入最近 24 条 → 脏目录已删除`
    3. `实例化 SocialEventEngine 检查 _social_events_dir 输出 D:\AI\xiaoyou-core\companion_data\dual_role\social_events（路径正确）`

### AOS-0805-04 冷启动 StateManager 同步恢复状态 & getFileInfo 主线程文件/IO 卡顿 (2026-08-05)
*   **问题描述**: StateManager.init{} 同步执行 restoreState() 读 SharedPreferences 文件，冷启动阻塞主线程；FileUploadManager.getFileInfo 为普通函数，调用路径在点击上传按钮事件中（主线程）触发 ContentResolver.query/openInputStream 等阻塞操作，长文件名/大图会出现 200ms+ ANR 风险。
*   **复现步骤**:
    1. 首次安装/清空数据后冷启动，systrace 查看主线程 StateManager restoreState 文件 IO
    2. 聊天页点击本地 30MB 以上视频文件上传
*   **预期行为**:
    1. 所有 SharedPreferences/文件/ContentResolver 操作都在后台线程
    2. getFileInfo 等文件操作为 suspend 函数且 withContext(Dispatchers.IO) 包裹
*   **实际行为**:
    1. StateManager.restoreState 在 init 块同步执行
    2. getFileInfo 是普通 fun，直接 new File/query/openFileDescriptor
*   **根因**:
    1. restoreState 早期写在 init 块，未注意冷启动性能影响
    2. getFileInfo 沿用 Java 风格代码，未做 suspend 化改造，上传路径也未严格 IO 调度
*   **修复方案**:
    1. StateManager.init：restoreState 包到 ioExecutor.execute { restoreState() } 后台单线程池
    2. FileUploadManager.getFileInfo 加 suspend 修饰 + withContext(Dispatchers.IO) 包文件/query
    3. ChatUploadHelper.uploadFile、uploadBytesResult 同步改 launch + 挂起调用；ChatViewModel.sendMessage 文件信息获取也走 suspend
    4. ShareUtils.shareImage / shareTextAndImage 写图片文件到 cacheDir 的部分包 withContext(Dispatchers.IO) 并改为 suspend fun，所有调用点包 lifecycleScope.launch
*   **验证**:
    1. `:app:compileDebugKotlin exit 0`
    2. `Android Studio profiler 冷启动 main thread 无 restoreState 长片段；上传 30MB 文件点击无掉帧`

### DW-20260809-01 数字健康：Aveline 自身包名被限额 (2026-08-09)
*   **问题描述**: Aveline 被数字健康自动设了每日限额，因其包名 com.aveline.ai.debug 无法匹配精确排除项 com.aveline.ai。
*   **复现步骤**:
    1. 观察 8-09 limits 文件，发现 com.aveline.ai.debug 条目存在
*   **预期行为**:
    1. 自身及系统应用应按前缀排除，不参与限额生成与强退
*   **实际行为**:
    1. 全新前缀匹配 _is_excluded 后已排除；旧限额文件残留自身条目需手工清理

### DW-20260809-02 数字健康：QQ 被自动设限及超限后仍可继续使用 (2026-08-09)
*   **问题描述**: QQ 被 nightly 自动设了每日限额；且超限后重新打开应用仍能继续使用，未被持续拦截。
*   **复现步骤**:
    1. 凌晨 nightly 对当日用量超 2 小时的应用设限，QQ 命中
    2. 应用超限强退一次后重新打开，当天不再被拦截
*   **预期行为**:
    1. QQ 等用户指定应用不参与限额生成与强退
    2. 超限应用在每次检查周期都被强退，形成持续打断
*   **实际行为**:
    1. 新增 _USER_NO_LIMIT_PREFIXES 排除 QQ，并清理旧限额条目
    2. UsageLimitMonitor 去除 stoppedSet 去重，改为每周期无条件强退超限应用

### LOG-20260817-MODULE-BROADCAST 模块独立日志被全局 QueueListener 广播污染 (2026-08-17)
*   **问题描述**: 每天的模块日志包含大量其他模块记录，单文件达到上万行，难以检索。
*   **复现步骤**:
    1. 启动服务并让多个模块产生日志。
    2. 比较 active_care_schedule.log 与其他模块日志。
    3. 观察无关 logger 记录是否同时出现在每个模块文件。
*   **预期行为**:
    1. 主日志保留全量记录，模块日志只包含登记到该文件的 logger。
*   **实际行为**:
    1. 所有模块文件 handler 都挂在同一个 QueueListener 上且没有过滤器。
*   **根因**:
    1. 模块文件 handler 未按 LogRecord.name 过滤。
*   **修复方案**:
    1. 为每个模块文件维护线程安全的 logger 名称白名单过滤器。
    2. 同一文件由多个 logger 共用时动态扩充白名单。
*   **验证**:
    1. `venv_core\Scripts\python.exe tests\scripts\active_care\verify_active_care_context_and_cleanup.py`

### QR-20260818-SECTIONED-LOGGING 聚合日志过长且关键事件难定位 (2026-08-18)
*   **问题描述**: 所有模块集中写入 xiaoyou_main.log，重要警告、消息收发和健康事件被大量心跳与调度细节淹没。
*   **预期行为**:
    1. 默认先看重要摘要，需要详情时按功能板块进入，仍可追溯完整时序
*   **实际行为**:
    1. 只有聚合日志和少数模块手工独立日志，没有统一入口
*   **根因**:
    1. QueueListener 缺少全局板块路由和重要事件过滤器
*   **修复方案**:
    1. 新增重要摘要、七板块唯一路由、每日导航和子目录跨天支持
*   **验证**:
    1. `verify_sectioned_logging 及既有 Active Care/Nightly 独立日志回归通过`

### QR-20260825-VOCAB-DUAL-SOURCE 词汇工具声称读取 daily 却重复返回 unfamiliar 高计数词 (2026-08-25)
*   **问题描述**: 聊天先从 unfamiliar 抽到固定高计数词；用户要求查看另一个 daily 来源后，回复仍声称另一个来源也是同一批词。
*   **复现步骤**:
    1. 发送今天还没有背单词并触发 word_quiz
    2. 指出结果来自 unfamiliar，要求查看另一个 daily 来源
    3. 观察工具调用后的回复仍复述上一轮长期生词本词条
*   **预期行为**:
    1. 未指定日期的 daily 复习自然读取昨天的非空日志
    2. 工具结果明确标注来源，模型不能把两类词表混为一谈
    3. App 已有错题次数可参与 AI 的 unfamiliar 优先抽词
*   **实际行为**:
    1. 第一轮缺省走 unfamiliar/high_count，反复命中计数最高的固定词条
    2. 第二轮 daily 缺省读取当天空文件，模型没有依据却复用了前一轮结果
    3. App progress.history 与 unfamiliar_word.txt 计数彼此隔离
*   **根因**:
    1. 工具缺省来源和抽样策略不符合每日复习语义
    2. daily 的默认日期窗口错误地指向当天而不是昨天
    3. 缺少跨 App 复习进度与 AI 长期难词本的合并视图
*   **修复方案**:
    1. 默认读取昨天 daily，并添加 source=both 与结构化来源元数据
    2. 构建 unfamiliar 文件计数和 App 历史错误次数的只读合并池，后续 App 评分同步更新文件计数
    3. 新增隔离验证脚本覆盖默认日期、双来源分区、错误来源校验和计数去重
*   **验证**:
    1. `四个词汇验证脚本全部通过，Ruff 通过`
    2. `真实数据只读调用显示 daily 命中 2026/08/24，unfamiliar 返回 linked_with_app_mistakes=true`

### QR-20260827-PERSONA-SCOPE-DUPLICATE-DIRS Persona 中文别名与英文 scope 重复创建数据目录 (2026-08-27)
*   **问题描述**: 同一 persona 同时出现中文别名数据目录与英文 scope 数据目录，删除中文目录后后台记忆保存会再次创建。
*   **复现步骤**:
    1. 使用中文文件名 persona 建立 shared__persona__ 会话
    2. 等待记忆管理器初始化或定时保存
    3. 检查 companion_data 下的中文别名目录和英文 scope 目录
    4. 删除中文别名目录并保持旧进程运行，等待下一次保存
*   **预期行为**:
    1. 一个 persona 只有一个稳定英文 scope 数据目录
    2. 中文文件名与英文名只作为别名解析，不参与目录命名
    3. 新增角色只需配置 meta.scope，不修改 Python 白名单
*   **实际行为**:
    1. 不同入口分别使用中文 slug 和英文 role scope，形成两套目录
    2. 旧进程的自动保存继续按中文 slug 重建被删除目录
*   **根因**:
    1. data_paths 与 scope_registry 各自维护角色解析逻辑
    2. normalize_data_scope 接受未注册中文 slug 作为动态 scope
*   **修复方案**:
    1. 以 persona meta.scope 和 scope_registry 作为唯一持久化解析标准
    2. 所有 data_paths 兼容入口委托统一注册表
    3. 新增安全目录合并工具和未来新角色回归验证
*   **验证**:
    1. `当前角色中英文 slug 路由与 memory user_id 验证 31 项全部通过`
    2. `迁移工具无损与冲突保留验证通过`
    3. `实际目录迁移 22 个文件且无冲突`

### QR-20260830-VOCAB-DAILY-BACKLOG 漏背一天后 daily 词汇积压被空文件截断 (2026-08-30)
*   **问题描述**: 前一份 daily 文件有手动记录，中间一天未背词且 daily 文件为空时，App 下次复习不会继续读取更早的非空积压。
*   **复现步骤**:
    1. 在 daily/2026/08/28.txt 写入待复习词
    2. 保持 daily/2026/08/29.txt 为空，表示 29 日未学习
    3. 30 日调用 GET /api/v1/vocab/daily 或打开 Android 背单词页
*   **预期行为**:
    1. 空的 29 日日志不截断积压
    2. 30 日默认复习队列继续包含 28 日未处理词
    3. 复习后认识的词从旧日期移除，仍不会的词流转到今天
*   **实际行为**:
    1. get_daily_words 只读取严格的昨天 29.txt，因文件为空而返回不含 28 日手动词的队列
*   **根因**:
    1. 默认日期策略使用 today-1，没有按非空待处理日志向前回退
*   **修复方案**:
    1. 默认复习日期改为今天前最近非空 daily
    2. App 取词与 AI word_quiz 共用同一默认日期决策
    3. 新增漏背继承回归验证
*   **验证**:
    1. `四个词汇相关验证脚本通过，Ruff 与 py_compile 通过`
    2. `真实 28.txt 的 20 个词全部出现在修复后队列`

### QR-20260830-VOCAB-DAILY-CHAIN-REPLAY daily 继承源背空后继续链式回溯旧词表 (2026-08-30)
*   **问题描述**: 用户完成当天继承的 daily 词表后，App 立即又推送一批完全不同的词，待复习数量越背越多。
*   **复现步骤**:
    1. 30 日默认继承并背完 28 日的全部词
    2. 28.txt 被复习流转清空后，Android 结算页再次刷新 GET /vocab/daily
    3. 观察默认源从 28 日跳到 12 日、11 日
*   **预期行为**:
    1. 当天只继承一个确定的非空来源
    2. 来源背空后当天 daily 待复习应结束
    3. 后端重启后也不应继续向更早文件回溯
*   **实际行为**:
    1. 28 日背空后先读取 12 日，随后又读取 11 日，当前队列一度变为 32 个旧词
*   **根因**:
    1. 缺少当日继承源锁定，每次刷新都从历史非空文件重新选一份
*   **修复方案**:
    1. 持久化锁定 review_date/source_date
    2. 源背空后停止回溯，并覆盖进程重启场景
    3. 当前日期锁定回正到 28 日
*   **验证**:
    1. `回归验证确认 28 日背空后不读取 27 日，重启后仍锁定 28 日`
    2. `真实数据队列已回到 0，不再出现 11 日旧词`

### QR-20260831-VOCAB-DURABLE-DAILY-BATCH 历史 daily 手动记录没有进入 FSRS 且临时回退造成队列链式增长 (2026-08-31)
*   **问题描述**: 早期 daily 文件中的大量手动记录从未被推送；改成读取最近非空文件后，当前来源背空又会继续翻更早文件，造成一次会话内不断出现不同旧词。
*   **复现步骤**:
    1. 核对 2026/08/05、08/10、08/11 等历史 daily 文件
    2. 按单词匹配 output/user_data/vocab_progress.json 的 history
    3. 复现同日选中来源背空后再次调用 get_daily_words
*   **预期行为**:
    1. 漏背或回填的历史记录最终能够逐日进入复习
    2. 已有进度的词不被重置为新词
    3. 同一天完成固定批次后不继续自动追加下一批
*   **实际行为**:
    1. 真实数据仍有 82 个历史词没有任何复习记录
    2. 精确昨天策略会永久漏掉窗口外文件，最近非空策略会在同日链式回放
*   **根因**:
    1. daily 文本没有持久化的待处理批次/游标
    2. daily 入队与 FSRS 调度边界混在按日期文件回退逻辑中
    3. 解析器未排除注释行
*   **修复方案**:
    1. 建立按日持久化的固定历史补漏批次
    2. 使用记录日期与最后复习日期判断是否待处理，并与 FSRS 到期词去重合并
    3. 配置每日上限和补漏保留名额，过滤 # 注释
*   **验证**:
    1. `专用历史补漏回归、既有词汇优化、daily 日志、双来源、Active Care 状态守卫验证全部通过`
    2. `真实数据临时预览为 82 个待补漏、当天固定 20 个`

### QR-20260901-CHAT-HISTORY-DYNAMIC-SCOPE 新注册角色聊天历史落盘正确但 scope 元数据回退到旧角色 (2026-09-01)
*   **问题描述**: 新角色会话通过 data_paths 正确落到独立角色目录，但 ChatHistoryStore payload 的 storage_scope 仍由旧会话标签映射给出，导致目录与事件元数据不一致。
*   **复现步骤**:
    1. 构造使用新 persona slug 的 shared conversation_id
    2. 比较 get_chat_history_dir_for_conversation 的目标目录与 append_event 返回的 storage_scope
    3. 读取落盘 JSONL 检查 storage_scope
*   **预期行为**:
    1. 目录、事件元数据和 conversation_id 注册表解析结果使用同一个动态角色 scope
*   **实际行为**:
    1. 目录为新角色独立目录，但修复前事件元数据回退为 aveline
*   **根因**:
    1. ChatHistoryStore 依赖只特判旧角色的 conversation_labels.storage_scope，没有使用动态 scope 注册表作为持久化真源
*   **修复方案**:
    1. append、list 和事件内容根目录优选统一改用 conversation_id 的注册表解析结果
    2. 提供按稳定 message_id 定向修复既有导入事件元数据的入口
*   **验证**:
    1. `临时 ChatHistoryStore 对 shared__persona__ye_qq_master append_event 返回 ye`
    2. `634 条正式导入事件的 storage_scope 集合仅为 ye`

### VOCAB-20260913-01 背完单词刷新后今日队列不减少 (2026-09-13)
*   **问题描述**: 安卓端把当天单词全部背完后刷新，今日单词列表仍是满的，进度像没记录一样。
*   **复现步骤**:
    1. 后端在缺 fsrs 库的环境（venv_cpu）中启动。
    2. 正常完成一轮每日复习（/vocab/review 逐词提交评分）。
    3. 重新拉取 /vocab/daily。
*   **预期行为**:
    1. 今天已评分的词立刻从今日队列移除，队列清空后今日词汇任务判定为完成。
*   **实际行为**:
    1. 队列一个不少（实测 136 个已背词全部残留），今日复习状态 remaining_words 恒大于 0。
*   **根因**:
    1. fsrs 缺失导致 apply_progress 回退 SM-2，只更新 next_review，不更新 fsrs_due / fsrs_last_review。
    2. get_daily_words 只看 fsrs_last_review 判断「今天是否背过」，陈旧的 fsrs_* 让已背词被判为未背且已到期。
    3. fsrs_card_from_progress 不检查落盘状态是否被 history 追过，装回 fsrs 后仍信任落后状态（305 词中 135 词落后）。
*   **修复方案**:
    1. 新增 fsrs_scheduler.latest_review_timestamp，用 history 末次事件兜底；get_daily_words 改用该口径判定「今天已复习过」。
    2. 新增 fsrs_scheduler.state_lags_behind_history，落后时 fsrs_card_from_progress 按 history 全量重建卡片。
    3. venv_cpu 补装 fsrs==6.3.2，恢复 FSRS 调度。
*   **验证**:
    1. `tests/scripts/study/verify_vocab_daily_queue_reviewed_today.py`
    2. `tests/scripts/study/verify_vocab_fsrs_state_selfheal.py`
