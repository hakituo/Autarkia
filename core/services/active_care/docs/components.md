# 核心组件（服务 / 检查器 / 决策 / 执行器）

> Active Care 子文档 · 上级入口：[README.md](../README.md)
> 只写当前实现；变更史进 `docs/updates/`。

---

## 核心组件

### 1. ActiveCareService (服务主类)

**文件**: `core/service.py`

主动关怀服务主类，协调各组件工作：

```python
class ActiveCareService:
    def __init__(self):
        # 初始化组件
        self.storage = ActiveCareStorage()
        self.context = ActiveCareContext(self.storage)
        self.scheduler_logic = ActiveCareSchedulerLogic()
        self.decision = ActiveCareDecision(self.storage)
        self.executor = ActiveCareExecutor(self.context, self.storage)
        self.vocab = ActiveCareVocabulary(self.storage)
        self.mode_state = ActiveCareModeState()

        # 初始化检查器
        self.checker = ProactiveChecker(
            storage=self.storage,
            context=self.context,
            scheduler_logic=self.scheduler_logic,
            decision=self.decision,
            executor=self.executor
        )
```

**主要功能**:
- 服务生命周期管理
- 组件协调
- 健康检查注册
- 事件订阅

### 2. ProactiveChecker (主动关怀检查器)

**文件**: `core/proactive_checker.py`

主动关怀检查器，负责定时检查是否需要发起关怀。已将初始化/状态恢复、客户端门控、节流调度拆分到 `checker/` 子目录，本类通过属性委托和转发方法保持向后兼容：

```python
class ProactiveChecker:
    async def check_proactive_care(self) -> Optional[Dict[str, Any]]:
        """检查是否需要主动关怀"""

    async def should_trigger(self, context: Dict) -> bool:
        """判断是否触发"""
```

**检查维度**:
- 用户静默时间
- 时间段（早晨、中午、傍晚、深夜）
- 用户状态（忙碌、空闲）
- 情绪状态
- 设备上下文

**委托子模块**（`checker/` 目录）:

| 子模块 | 文件 | 职责 |
|--------|------|------|
| CheckerInitState | `checker/checker_init_state.py` | 初始化与状态恢复（决策时间戳管理、per-persona 独立决策时间） |
| CheckerClientGate | `checker/checker_client_gate.py` | 客户端门控（活跃客户端、用户进程活动、主人设运行时交互模式、分级模式、客户端类型探测） |
| CheckerThrottle | `checker/checker_throttle.py` | 检查节流与时间调度（间隔抖动计算、非响应退避乘数） |

### 3. ActiveCareDecision (决策引擎)

**文件**: `decision/decision.py`（输出解析已拆分到 `decision/decision_output_parser.py`，指令构建已拆分到 `decision/decision_instruction_builder.py`，保留转发方法）

决策引擎，负责选择关怀动作：

```python
class ActiveCareDecision:
    async def select_action_bandit(
        self, ctx: Dict[str, Any], actions: List[str]
    ) -> str:
        """使用Contextual Bandit选择动作"""

    async def update_policy_reward(self, action: str, reward: float):
        """更新动作奖励值"""
```

**决策算法**:
- **题材感知 MDP（马尔可夫决策过程）**：状态 `S = (tod_slot, last_topic_sub, last_reply)`，Q 表 `active_care_mdp.json`，增量 Q-learning（学习率 0.15 随样本衰减）。题材分类复用 `prompt/topic_diversity.detect_topic_category`（intent 主类 + 题材子类型，如 `share_thought:food`）
- Contextual Bandit（上下文强盗）：保留作 MDP 冷启动/异常兜底
- 增量平均奖励计算
- 探索/利用平衡
- **自发做事排除**：角色日程切换告别消息（`activity_transition` / `activity_return`）传 `self_activity=True`，不记录题材、不进 MDP/bandit 学习闭环

**动作类型**:
| 动作 | 说明 |
|------|------|
| greeting | 问候 |
| reminder | 提醒 |
| weather | 天气提醒 |
| health | 健康关怀 |
| emotion | 情绪关怀 |
| study | 学习提醒 |
| random | 随机闲聊 |

**委托子模块**（`decision/` 目录）:

| 子模块 | 文件 | 职责 |
|--------|------|------|
| 决策输出解析 | `decision/decision_output_parser.py` | `_parse_decision_output`，JSON 修复，regex fallback，peer chat 输出解析 |
| 决策指令构建 | `decision/decision_instruction_builder.py` | `_build_daily_routine_probe_instruction`，`_build_specific_instruction` |

### 4. ActiveCareExecutor (执行器)

**文件**: `core/executor.py`（QQ 连接解析已拆分到 `core/qq_connection_resolver.py`，LLM 生成已拆分到 `core/response_generator.py`，硬件意图已拆分到 `core/hardware_intent.py`，触发链路已拆分为 `trigger_preparer.py` / `generation_pipeline.py` / `post_send_handler.py`，保留转发方法）

执行器，负责执行关怀动作；QQ 连接来源解析已下沉到
`core/qq_connection_resolver.py`，LLM 生成与 fallback 已下沉到
`core/response_generator.py`，硬件震动/灯效策略已下沉到
`core/hardware_intent.py`。执行器只消费标准化后的
`user_id/profile_filename/client_id/role_id/adapter_type` 连接结构和生成后的消息内容。

`trigger_message_with_result` 只保留调度编排，七段职责分别落在不同模块：

| 阶段 | 落点 |
|------|------|
| 重叠保护 | `core/overlap_guard.py` |
| 会话路由 → 早安注入 → 历史/上下文 → Prompt | `core/trigger_preparer.py` |
| 生成 + 后处理 | `core/generation_pipeline.py` |
| 发送前事实纠偏 | `postprocess/send_content_corrector.py` |
| 分发 + 状态持久化 | `core/message_dispatcher.py` |
| 发送后收尾 | `core/post_send_handler.py` |
| 失败回退 | `core/overlap_guard.py`（`rollback_on_failure`） |

验证脚本：`tests/scripts/active_care/verify_executor_trigger_pipeline_decoupled.py`。

```python
class ActiveCareExecutor:
    async def execute_care(
        self, action: str, context: Dict[str, Any]
    ) -> Tuple[bool, Optional[str]]:
        """执行关怀动作"""

    def determine_hardware_intent(
        self, sys_prompt_type: str, device_context: Dict[str, Any]
    ) -> HardwareIntent:
        """决定硬件控制参数"""
```

**执行流程**:
1. 检查提醒
2. 构建提示词
3. 调用LLM生成响应
4. 确定硬件控制参数
5. 发送消息
