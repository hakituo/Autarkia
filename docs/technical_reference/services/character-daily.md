# CharacterDailyService（角色日常）

> 本文同步自项目内部技术参考，仅描述公开可见的实现。
> 由 `scripts/doc_records/sync_tech_docs.py` 生成，请勿直接编辑；修改请改真源后重新生成。
> 文档入口：[技术参考目录](../README.md)

---

## 3.10 CharacterDailyService（角色日常服务）

**文件**: `core/services/character_daily/`

**职责**: 角色日常活动管理，为全部已配置模板角色提供独立的日常生活节奏。每个角色每天生成活动计划（学习、做饭、看书、散步等），按计划推进自己的生活，并在 Nightly 为次日预生成稳定的活动实例事实。Peer Chat 从固定定时器变为自然触发，但其 persona/账号配对边界独立于计划角色发现。

角色运行时由 `core/character/runtime_roles.py` 统一声明，分两套口径：

- **角色日程**：`get_scheduled_role_ids()` / `is_scheduled_role()` / `filter_scheduled_roles()`，以 persona 注册表里有真实人设入口文件的角色为准（与 `GET /api/v1/personas` 同源）。隐藏角色不生成计划与 ActivityInstance；可见角色也不会因此获得主动发消息资格。
- **自主行为**：`get_autonomous_role_ids()` / `is_autonomous_role()` / `filter_autonomous_roles()`，读取 `character_runtime.yaml` 的 `autonomous_roles`，只管主动消息（早安/晚安/主动关怀）与日记。

“是否存在日程模板”不等于“有日程”，也不等于“有自主行为”：模板只是素材，还要通过 `filter_scheduled_roles()`；主动早安/晚安等路径额外通过 `is_autonomous_role()` 判断。

**活动解析补充**:
- `current_activity` 优先取当前命中的 `slot.activity`
- 睡觉结束后的短空档仅保留几分钟 `waking_up`
- 其他无 slot 的时间空档回落到 `idle`，避免角色在计划空白段长时间卡在上一项活动，误伤 `peer chat` 和被动回复判定
- 当 `current_activity` 发生变化时同步保存 `daily_state.json`，避免磁盘里长期残留过时的瞬时态

**模块架构**:

```python
class CharacterDailyEngine:
    def __init__(self):
        self._generator: DailyPlanGenerator  # 每日计划生成器
        self._state: DailyStateStore         # 状态持久化
        self._gate: PeerChatGate             # Peer Chat 门控
        self._running: bool = False

    async def start(self) -> None:
        """启动主循环（独立 async loop）"""

    async def stop(self) -> None:
        """停止主循环"""

    async def _tick(self) -> None:
        """每 2 分钟 ±20% jitter 执行一次"""
        # 1. 新的一天？生成今日计划
        # 2. 更新每个角色的当前活动
        # 3. 检查是否触发 peer chat

    def get_current_activity(self, role_id: str) -> ActivityType:
        """获取角色当前活动"""

    def get_activity_context_text(self, role_id: str) -> str:
        """获取自然语言描述（如 'Ling现在在发呆'）"""

    def get_peer_chat_summary(self) -> str:
        """获取今日 peer chat 摘要"""
```

**子模块架构**:

| 模块 | 文件 | 职责 |
|------|------|------|
| 角色日程资格 | `core/character/runtime_roles.py` | `is_scheduled_role()` / `get_scheduled_role_ids()` / `filter_scheduled_roles()`，按 persona 注册表的可见角色推导 |
| 自主角色资格 | `core/character/runtime_roles.py` | `is_autonomous_role()` / `get_autonomous_role_ids()` / `filter_autonomous_roles()`，读取 `character_runtime.yaml` |
| 活动模型 | `activity_model.py` | ActivityType 枚举（20+种）、ActivitySlot、DailyPlan 数据类 |
| 每日计划 | `daily_plan.py` | DailyPlanGenerator：按日期选择完整 workday/rest_day 骨架并复用共享确定性排程；未迁移角色保留旧兼容路径 |
| 日型解析 | `day_type_schedule.py` | 解析 `character_day_types.yaml` 的完整 `workday` / `rest_day`（wake/sleep/time_blocks） |
| 学期课程表 | `course_timetable/` | 解析 `character_course_timetable.yaml`；按学期周次 + 星期命中课程，转成 fixed 排程约束（`config.py` / `models.py` / `planner.py`） |
| 活动实例 | `activity_instance.py` | ActivityInstanceResolver / ActivityInstanceStore：稳定哈希解析、first-write wins、原子写入、只读消费 |
| Nightly 预生成 | `nightly.py` | `prepare_activity_instances_for_date()`：为次日日程角色预生成 ActivityInstance，单角色失败隔离 |
| LLM 计划生成 | `llm_plan_generator.py` | 历史兼容模块；主引擎不再导入 |
| 计划展示 | `plan_view.py` | 角色计划格式化，供工具调用返回自然语言摘要/完整时间线 |
| 被动回复策略 | `reply_policy.py` | 用户发消息时根据角色活动/睡眠状态 + 回复窗口期决定延后处理/强制唤醒/强制打断 |
| 已读不回 | `read_no_reply/` | 启用角色（当前仅 tt）空闲时可"看了不回"：silent 低信息量消息 / revisit 回头补回；含 config/policy/store/hints/revisit 子模块 |
| 回复提示模板 | `reply_hints.py` | 集中管理所有"被吵醒/被打断/起床后/忙完后"提示模板和 builder（从 reply_policy.py 拆出，避免超 500 行） |
| ReplyPolicy 辅助函数 | `reply_policy_support.py` | 手动打断窗口读取、回归决策提示、窗口延长、轻活动延迟分档 |
| 活动配置 | `config.py` | 加载 `character_daily.yaml` / `character_day_types.yaml` + `app.yaml`，并同步日型起睡时间到 SleepProfile |
| Peer Chat 门控 | `peer_chat_gate.py` | 5 层门控 + 异步聊天 + 紧急打断路径 |
| 手动打断窗口 | `interrupt_window.py` | `/打断` 后的临时聊天窗口管理（激活/延长/跳过/过期） |
| 统一回归消息 | `activity_return/` | `/打断` 后回去做事 + 半夜睡回去的告别消息，事件驱动调度（含 instruction/state/scheduler/core） |
| 状态持久化 | `state.py` | JSON + 原子写入 + 节流保存 |

**ActivityInstance（活动实例）**:

DailyPlan 只回答“某个时间段做什么”；ActivityInstance 把该槽位解析成当天稳定的生活事实（目的/同行方式/地点/交通方式/可选细节）。要点：

- 候选池来自 `config/yaml/character_activity_instances.yaml`，按 `role/date/slot/activity/field` 构造稳定 SHA-256 选择，同一天同一时段不会因重读/重启而随机换地点、换同行方式。
- 只为日程角色生成（`is_scheduled_role()`），按 role/date/slot **first-write wins** 落盘，Nightly 重跑不覆盖当天已说过的事实。
- 原子写入（临时文件完成后替换），默认保留最近 14 天。
- 持久化位置：`companion_data/character_daily/activity_instances.json`。
- 消费者只读：主对话通过 `components/character_daily_context.py`、Active Care 通过 `prompt/prompt_context_builders.py::build_role_activity_context_text()`（内部复用前者）调用 `ActivityInstanceStore.get_for_slot(..., resolve_if_missing=False)`；两条路径都只读，不生成、不改写实例。
- 时间线投影：`character_daily/activity_timeline.py` 从同一份 DailyPlan 取最近已结束与未开始的槽位（各 2 条、时间正序）渲染为 `recent_activities` / `upcoming_activities`，与当前活动一起注入；只读计划事实，不推断执行结果，当前 slot 不在时间线重复出现。课程槽位带 `course`，时间线渲染为 `上课：<课程名 地点>`。
- 课程时段：`ActivitySlot.course` 非空时，`ActivityInstance.course` 同步保存课程名，并跳过 purpose/location/companion/transport/detail 的随机解析，避免“在上课却写着在实验室”的冲突。
- 三层结构：基础池（`character_activity_instances.yaml`）→ 稳定挑选（`ActivityInstanceResolver`）→ 统一投影（`activity_presentation.py`）。展示层 `plan_view.build_slot_label/build_slot_detail` 与注入层 `ActivityInstance.prompt_text()`、`character_daily_context.build_character_daily_context()` 都从同一份 `ActivityPresentation` 取标题/细节/注入句子，长时段压缩、睡眠只留地点、三餐标题等口径只有一处实现。
- 基础池文案要求可直接说出口：purpose 不使用「技术/设计」这类斜杠组合或占位式措辞（否则模型会原样复述进主动消息）。存储版本 4 会自动清洗旧实例里的斜杠组合 purpose/label，按粗粒度活动重新投影。

**学期课程表（硬约束）**:

`config/yaml/character_course_timetable.yaml` 定义 `semesters`（第 1 周周一 + 结束日期）、`periods`（节次起止）与角色 `courses`（`weekday` + `periods` + `weeks`，可选 `week_parity`）。`course_timetable/planner.py::build_course_plan_constraints()` 把当天命中的课程转成独立 `PlanWindow` 与 fixed `studying` 候选：

- 课程固定占用自己的起止时间，随机活动池只能排在课程之外；课程之外仍完全沿用 `character_day_types.yaml` 的活动池。
- `DailyPlanGenerator` 只做 windows/candidates 合并，不在日型里写死“每天第一二节有课”。
- 课程周次按学期起始日计算；第 17-18 周等复习周没有课程时自然回落到普通日常。
- 配置文件缺失或解析失败时返回空约束，不影响角色日常。

**Nightly 次日预生成**:

`nightly.py::prepare_activity_instances_for_date(target_date)` 为次日日程角色生成 DailyPlan 并解析落盘 ActivityInstance；由 `memory/nightly/global_tasks.py::_prepare_character_daily` 在夜间调用，单角色失败不阻断整个 Nightly。

**与 Active Care / Character Runtime 的边界**:

- Active Care 不是自主角色资格的 owner：`CheckerStateDetector._get_character_daily_context()` 通过 `get_autonomous_role_ids()` 取角色集合，不再维护私有白名单；`config_accessor.get_active_care_config("active_care_enabled_roles")` 也代理到同一入口。
- Active Care 同时消费两类事实：粗粒度活动（`activity` / `activity_text` / `is_idle`）用于发送决策；当前 slot 已落盘 ActivityInstance 的 `activity_facts` 用于“是否存在值得分享的新内容”与内容生成。
- `CheckerStateDetector._get_character_daily_context(profile_filename)` 把 `build_role_activity_context_text()` 的结果写入 `character_daily[role]["activity_facts"]`；`ContentPlanner._build_dynamic_constraints()` 优先使用 `activity_facts`，`core/services/active_care/core/context_builder.py` 再把同一份投影作为 `role_activity_text` 注入主动消息 Prompt。
- Active Care 只读：不调用 resolver、不在决策链临时生成或改写 `activity_instances.json`；缺失实例时退化为粗粒度 activity。
- SleepManager 主动早安/晚安、Activity Return 的角色资格复用 `is_autonomous_role()`：日程角色（如Ye）可以推进作息与活动，但不触发这些主动消息。

Android 伴侣详情通过 `GET /api/v1/life/status` 获取 `activity`、`reply_policy`、`sleep_summary` 与当前 scope 的 `daily_plan`。`activity_chat_eligible` 仍保留兼容，但只属于角色间 Peer Chat 门控，不能解释为用户消息即时回复；状态页按 Reply Policy 展示 `immediate / delayed / silent`，日程页展示 `DailyPlan.slots` 完整时间线。控制按钮调用既有的 `POST /api/v1/life/sleep/wake`、`POST /api/v1/life/activity/interrupt`、`POST /api/v1/life/activity/skip`，不在 Android 端复制 QQ 命令路由。

伴侣详情的 HorizontalPager 与外层退出面板采用手势分层：外层 `PullableDismissPanel` 只有在 Pager 上一次手势已经稳定停于第 0 页“状态”时才启用拖拽；从其他 Tab 向右切页的同一次手势不能继续穿透并退出详情。打开详情和稳定进入“日程”页时强制刷新生命状态，以补齐旧缓存中缺少的 `daily_plan`。

**活动类型**:

| 类型 | 说明 | 是否忙碌 |
|------|------|----------|
| SLEEPING | 睡觉 | 忙碌 |
| COOKING | 做饭 | 忙碌 |
| STUDYING | 学习/做题 | 忙碌 |
| NAPPING | 午休 | 忙碌 |
| READING | 看书/看番 | 空闲 |
| HOUSEWORK | 做家务 | 空闲 |
| WALKING | 散步 | 空闲 |
| PHONE_SCROLLING | 刷手机 | 空闲 |
| GARDENING | 浇花 | 空闲 |
| EXERCISING | 运动/拉伸 | 忙碌 |
| GAMING | 玩游戏 | 空闲 |
| SELF_CARE | 洗澡/护肤/整理 | 一般 |
| CREATIVE_HOBBY | 手工/写字/画画 | 空闲 |
| SHOPPING | 出门购物/买小东西 | 空闲 |
| IDLE | 发呆/休息 | 空闲 |

**Peer Chat 门控**:

| 层级 | 条件 | 默认值 |
|------|------|--------|
| 1 | 全局最小间隔 | 5400s（1.5小时） |
| 2 | 今日总次数 | 软上限 4，硬上限 6 |
| 3 | 时间范围 | 9:00-22:00 |
| 4 | 双方活动都适合聊天 | CHAT_ELIGIBLE_ACTIVITIES |
| 5 | 概率判定 | 基础 0.04，多因素修正 |

**Peer Chat 紧急打断路径**（异步聊天模式）:

当一方空闲、另一方忙碌（异步聊天）时，按概率（默认 15%）走"紧急打断"路径：
- `should_use_urgent_interrupt()` 决定模式
- `build_situation_context(interrupt_mode=True)` 生成情境：提示 LLM"有急事要找她，会被打断，可能有点不情愿但会放下手头的事回应"
- 非打断路径：异步聊天，忙碌方可能不回/简短回（如"忙着呢等下说"）

**被动回复策略（Reply Policy）**:

用户发消息时，根据角色当前活动 + Active Care 睡眠会话 + 回复窗口期决定回复方式：

| 状态 | 行为 | 配置 |
|------|------|------|
| 回复窗口期内（上次 BUSY 回复后 ≤ 120s） | **正常回复**：趁热打铁延续对话，不走延后处理。仅对"忙碌但非 DND"的活动（studying/cooking）有效 | `reply_policy.reply_window_seconds` (默认 120) |
| 主动回接窗口内（同 persona 最近主动发消息后 ≤ 300s） | **正常回复**：即使当前活动仍投影为 `sleep_recovery`，也直接接话，避免出现“她先来找你，你回她却被静默累积”的割裂体验。按 `profile_filename` 解析 scope，只放行当前 persona | `reply_policy.proactive_reply_window_seconds` (默认 300) |
| 计划即将切换（下一个槽位 ≤ 300s） | **正常回复 + 动态提示**：给当前回复注入“下一个安排快到了”的提示，让模型自然选择是把安排稍微顺延几分钟继续聊，还是礼貌收尾去做下一项；不硬切对话 | `reply_policy.plan_transition_notice_seconds` (默认 300) |
| 轻活动（按类型分档） | **静默后回复**：不再直接吞消息，而是按活动类型延迟不同秒数后再自然回复。`idle/phone_scrolling/reading/gaming` 走 `quick(8~18s)`，`self_care/shopping/walking/creative_hobby` 等走 `normal(18~35s)`，`cooking/housework/exercising/正餐` 走 `slow(28~55s)`，`sleep_recovery` 单独走 `recovery(20~40s)`。**软延迟合并批**：等待期内用户新发的消息并入同一批（`_SOFT_DELAY_BATCHES`，每并入一条顺延 `soft_delay_join_grace_seconds`，总等待封顶 `soft_delay_max_wait_seconds`），截止后合并成一条消息统一回复，不再逐条排队各自延迟 | `reply_policy.soft_delay_*` + `soft_delay_join_grace_seconds` / `soft_delay_max_wait_seconds` |
| 硬忙碌（studying） | **偶尔回一句 + 静默累积**：连发多条先走递增概率强制打断（与 DND 共用概率表）；未打断时按 `busy_casual_reply_probability`（默认 0.2）概率"做事间隙看眼手机"自然回一句（走普通对话管线，累积消息一并交给 LLM 按人设发挥，复用软延迟合并批）；未命中则静默累积 | `HARD_BUSY_ACTIVITIES` + `reply_policy.busy` + `busy_casual_reply_probability` |
| 不可打扰（sleeping/napping/waking_up 或 active_care 睡眠会话） | **延后处理**：第 1 条起即静默累积（不发占位消息），should_reply=False（消息留到起床后处理） | `reply_policy.do_not_disturb` |
| 不可打扰 + 连续消息 | **递增概率强制唤醒**：基础概率仍是第 2 条 8%、第 3 条 25%、第 4 条 55%、第 5 条 85%，达到硬上限（默认 6 条）100% 醒；但如果角色是“刚睡下”的 `sleeping`，会额外叠加 `fresh_sleep_bonus`，让首条消息也可能把她叫醒。唤醒时缩短延迟，把前几条没回的消息一起发给 LLM，persona_hint 说明"被用户连续发了 N 条消息吵醒" | `reply_policy.force_reply_threshold` + `reply_policy_support.resolve_dnd_wake_profile()` |
| 角色起床后下次发消息 | 检查 `_DND_PENDING` 累积消息，注入 `build_morning_after_hint`（提示 LLM"刚才在睡觉，看到用户在你睡觉时发的 N 条消息，要逐条回应"） | — |
| 夜间被叫醒后静默结束 | **主动补发消息**：如果角色决定 `return_to_sleep` 或 `sleep_later`，会主动补一句“我先继续睡会儿/我等会儿再去睡”，避免聊天突然无声消失；同时同步更新 Active Care 的最近主动发消息时间 | `chat_reply_runtime._notify_sleep_resume_message()` |
| 忙碌（studying/cooking）第 1 条 | 未命中偶尔回复概率时**延后处理**：静默累积（不发占位消息，should_reply=False），等用户下次发消息时注入处理 | `reply_policy.busy` + `busy_casual_reply_probability` |
| 忙碌 + 连续消息 | **递增概率强制打断**（与 DND 共用概率表）：唤醒时注入 `build_busy_interrupt_hint`（带活动动词，如"你正在学习，被用户连续发了 N 条消息打断"） | `reply_policy.force_reply_threshold` |
| 角色做完后下次发消息 | 检查累积消息，注入 `build_busy_done_hint`（提示 LLM"刚才在学习，现在做完了，看到用户在你做事时发的消息"） | — |
| 角色做完（忙碌 → 可聊天切换） | **立即补回**：做事期间累积且未被偶尔回复覆盖的消息合并成一条 user_input 走普通对话管线（`stream_conversation`，save_history=False 防重复入档），仅注入情境提示 `build_busy_done_active_situation_hint`（无逐条回应约束），生成文本经 `dispatch_proactive_message` 投递（含 QQ/App 渠道策略）；DND 累积跳过留给 morning_after | `activity_transition.check_and_reply_pending_on_activity_done` |
| 手动打断窗口期内（`/打断` 后） | **正常回复 + 动态提示**：`build_manual_interrupt_window_hint()` 告知 LLM 当前处于临时聊天窗口，还剩多久；窗口快结束时（≤60s）提示 LLM 自然提及要回去继续做事 | `reply_policy.manual_interrupt_window_seconds` |
| 回归消息等待期内 | **正常回复 + 决策提示**：AI 已发送回归消息后 90s 内用户再次回复，`build_activity_return_reply_hint()` 让 LLM 根据回复内容选择继续聊还是真的回去做事/睡回去；work 场景会自动延长窗口并重新调度回归消息 | `activity_return._DEFAULT_GRACE_SECONDS` |
| 空闲 + 启用已读不回的角色（tt，且会话在白名单内） | **已读不回（read_no_reply）**：角色空闲时的主动选择——低信息量消息（应答/收尾/纯表情）silent 略过（**不进 pending**）；轻分享类消息 revisit 入"回头再看"队列，10 分钟~12 小时后可能主动补回（补回时模型输出 `[SKIP]` 可再放弃）。问句/求助/长内容永远正常回。**这是关系层行为**（只对某位对象这样），不是角色通用性格；对外/初识仍走该角色的公共语感 | `character_runtime.yaml#read_no_reply`（概率与延迟按 TT **今年**的真实记录校准：2026-09 响应中位 21 秒、一分钟内没动静约 40-46%；2025-06 早期数据不可混用；`conversation_allowlist` 可按会话收窄，留空 = 全部会话） |
| 空闲 | 正常回复 | — |

设计变更（2026-06-27）：
- 去掉占位消息（zZz.../专注中...），DND/BUSY 第 1 条起即静默累积（`skip_message=""`），更接近"消息没回"的真实体验
- BUSY 不再延迟回复分支（不再 30%/70% 概率分流），统一延后处理
- 新增回复窗口期机制：BUSY 回复后窗口期内继续聊正常回复，DND 强制唤醒后不享受窗口期

**两条链路共用同一套策略**：QQ 走 WS 的 `apply_reply_policy`（`core/interfaces/websocket/adapters/handlers/chat/reply_policy.py`），App/HTTP 走 `routers/v1/chat.py#_apply_reply_policy_for_http`——同一个函数，`websocket=None` 时不会访问 adapter。因此两端行为一致：

- **不回复**（睡眠/忙碌静默累积、已读不回）：SSE 只下发 `[DONE]`，不产生任何消息事件；前端不显示"正在输入/等待回复"占位，用户的消息留在列表里，她稍后回复（含主动消息通道推送）才出现新气泡；
- **软延迟合并**：请求会挂着等 8~55s（Android 流式 OkHttp `readTimeout=120s`），期间用户继续发的消息由 `join_soft_delay_batch` 并入同一批，截止后合并成一条统一回复——这就是"延迟期间可以叠加"；
- **生成中插话**：若上一轮已开始吐字，新请求仍会 cancel 旧一轮（既有行为，相当于打断重答）；延迟等待阶段不会互相 cancel。

设计变更（2026-10-17）：
- App（HTTP SSE）接入被动回复策略：此前 App 端没有睡眠/忙碌累积与延迟合并，每条消息都立即生成（连发多条时后发请求会 cancel 前一条，回复可能闪断）；现在与 QQ 完全一致
- Android 去掉消息列表底部的"正在输入"三点占位（`ChatContentArea` 传 `showTypingIndicator = false`）：消息发出去只留自己的气泡，她的回复到了才出现新气泡；输入栏保持"有字即可发送"，生成中也能继续发

设计变更（2026-10-16）：
- 新增**已读不回**（`core/services/character_daily/read_no_reply/`）：仅对 `character_runtime.yaml#read_no_reply.enabled_roles` 登记的角色生效（当前只有 tt）。位置在 DND/BUSY 之后、软延迟之前——语义是"角色空闲时的主动选择"，不是"没空延后"；命中的消息**不进 `_DND_PENDING`**，silent 只在 store 里保留最近 N 条背景，revisit 由 `revisit.py` 排延迟任务（10 分钟~12 小时，log-uniform 采样让短端密集、长尾稀疏；按 2026-09 晚回区间校准）到点复查后用普通对话管线生成、经 `dispatch_proactive_message` 补回（模型输出 `[SKIP]` 则放弃）
- 用户重新发消息时注入一次"你之前看到但没回的消息"背景（`consume_read_no_reply_context`，提醒后清空、同时取消回头补回），文案约束"不解释延迟、不道歉"
- 两条链路共用同一套判定：QQ 走 WS（`chat/reply_policy.apply_reply_policy` 命中后直接 return，不写 pending），App 走 HTTP SSE（`routers/v1/chat.py#_maybe_read_no_reply` 命中后下发 `read_no_reply` 事件 + 结束流；非流式返回 `read_no_reply: true` 空回复）

设计变更（2026-10-14）：
- 软延迟/忙碌偶尔回复引入**合并批**：等待期内新消息并入同一批统一回复一条（顺延+封顶），不再逐条排队各自延迟
- BUSY 恢复概率性"偶尔回一句"（`busy_casual_reply_probability`，普通对话管线，无逐条回应模板）
- "做事结束主动触发"改为普通对话机制：移除原 active_care 主动管线（`executor.trigger_message` + `_BUSY_DONE_ACTIVE_TEMPLATE` 逐条回应模板），改为 `check_and_reply_pending_on_activity_done` 把累积消息合并成一条 user_input 走 `stream_conversation` 生成（情境提示无模板约束），经 `dispatch_proactive_message` 投递

累积消息状态由 `chat_reply_runtime.py` 的 `_DND_PENDING` 字典管理（per-conversation），含 `messages` + `last_ts` + `activity` 字段（记录累积时的活动类型，用于决定活动结束后注入哪个 hint），超时（默认 10 分钟）自动重置。`build_after_activity_done_hint()` 按累积时的活动类型选择 hint 模板（DND→morning_after / BUSY→busy_done）。软延迟/忙碌偶尔回复的合并批状态由同文件 `_SOFT_DELAY_BATCHES` 管理（per-conversation，截止后移除；取消/断连时整批转存 `_DND_PENDING`）。

回复窗口期状态由 `_LAST_REPLY_STATE` 字典管理（per-conversation），含 `last_reply_ts` + `activity` 字段，`evaluate_reply_state` 接收 `last_reply_ts` / `last_reply_activity` 参数，在 DND/BUSY 判断前先检查窗口期。should_reply=True 时由 `_record_successful_reply()` 记录状态。

**与 Active Care 集成**:

1. **决策上下文注入**: `CheckerStateDetector._get_character_daily_context(profile_filename)` 通过 `get_autonomous_role_ids()` 取自主角色并只保留当前 persona scope，每次 Active Care 决策时注入粗粒度活动状态（`activity` / `activity_text` / `is_idle`）与当前 slot 已落盘 ActivityInstance 的 `activity_facts`
2. **动态约束与内容生成**: `ContentPlanner._build_dynamic_constraints()` 优先使用 `activity_facts` 判断是否存在值得分享的新内容；`core/services/active_care/core/context_builder.py` 把同一份只读投影作为 `role_activity_text` 交给内容生成 Prompt。缺失实例时仅保留基础活动并标记细节未知，已确定安排也不代表活动完成；是否发送仍由新内容与原有打扰、睡眠策略决定。表达规则和当前任务示例由角色的 `active_care.guidelines/examples` 提供，不要求逐项报备日程。`tests/scripts/personas/evaluate_ling_active_care_content.py` 可复用正式 Prompt、内容生成器和 MiniMax 路由验证普通角色的六类虚构场景，默认只预览；`--live` 只生成内容，不运行发送决策或投递。未知事实提示属于生成约束，不构成杜绝模型猜测的保证。
3. **主对话工具调用**: `core/tools/character_daily_plan_tool.py` 注册 `get_character_daily_plan`，主程序 LLM 可查看自己/同伴的当日角色计划
4. **统一回归消息**: `activity_return.send_activity_return_message()` 复用 Active Care executor 发送 `/打断` 后回去做事与半夜睡回去的告别消息；通过 `reply_policy_support.build_activity_return_reply_hint()` 把用户回复时的决策提示注入被动回复 prompt

**配置**:

```yaml
# config/yaml/character_daily.yaml
aveline:
  wake_time: "07:00"
  sleep_time: "23:00"
  time_blocks:
    - period: "morning_routine"
      start: "07:00"
      end: "08:30"
      fixed:
        - { activity: "waking_up", duration: [15, 30] }
      pool:
        - { activity: "cooking",   duration: [20, 35], weight: 3 }
        - { activity: "breakfast", duration: [15, 25], weight: 5 }
```

```yaml
# config/yaml/character_runtime.yaml —— 自主行为（主动消息/日记/peer chat）资格真源
# 角色日程不在这里：由 persona 注册表里可见的客户端角色推导。
autonomous_roles:
  - aveline
```

```yaml
# config/yaml/character_day_types.yaml —— 完整工作日/休息日骨架
roles:
  ling:
    workday:
      wake_time: "07:00"
      sleep_time: "23:30"
      time_blocks: [ ... ]
    rest_day:
      wake_time: "09:00"
      sleep_time: "00:30"
      time_blocks: [ ... ]
```

```yaml
# config/yaml/character_course_timetable.yaml —— 学期课程表（硬约束）
semesters:
  - { id: "2026-2027-fall", start_date: "2026-09-07", end_date: "2027-01-10" }
periods:
  1: { start: "08:00", end: "08:45" }
  2: { start: "08:55", end: "09:40" }
roles:
  tt:
    semester: "2026-2027-fall"
    courses:
      - { name: "高等数学（一）", location: "一教 201", weekday: monday, periods: [1, 2], weeks: "1-16" }
```

```yaml
# config/yaml/character_activity_instances.yaml —— ActivityInstance 细化池
roles:
  ling:
    shopping:
      purpose: [ { value: "补日用品", weight: 3 } ]
      companion_mode: [ { value: "classmates", weight: 2 } ]
      location: [ { value: "附近商场", weight: 2 } ]
      transport: [ { value: "walk", weight: 1 } ]
```

**预期效果**:

| 维度 | 改造前 | 改造后 |
|------|--------|--------|
| 角色生活 | 无，只有生理状态 | 完整的每日活动计划 |
| Peer chat 频率 | 固定 30min 定时器 | 全局 60min + 概率自然波动 |
| 活动感知 | 无 | 知道角色在干嘛，只在空闲时聊 |
| Active Care 联动 | 无 | 角色忙碌时抑制主动消息 |

**详细文档**: `core/services/character_daily/README.md`
