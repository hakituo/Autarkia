# 上下文、调度逻辑、词汇与模式状态

> Active Care 子文档 · 上级入口：[README.md](../README.md)
> 只写当前实现；变更史进 `docs/updates/`。

---

### 5. ActiveCareContext (上下文管理)

**文件**: `core/context.py`（会话解析已拆分到 `core/conversation_resolver.py`，作息配置已拆分到 `scheduling/schedule_config_loader.py`，保留转发方法）

上下文管理，负责聚合决策所需的上下文信息：

```python
class ActiveCareContext:
    async def build_context(self) -> Dict[str, Any]:
        """构建决策上下文"""
```

**上下文信息**:
| 字段 | 说明 |
|------|------|
| elapsed_seconds | 用户静默时间 |
| time_period | 时间段 |
| emotion | 当前情绪 |
| life_status | 生命状态 |
| device_context | 设备上下文 |
| recent_activities | 最近活动 |
| user_preferences | 用户偏好 |

### 6. ActiveCareSchedulerLogic (调度逻辑)

**文件**: `scheduling/scheduler_logic.py`

调度逻辑，负责计算下次关怀时间：

```python
class ActiveCareSchedulerLogic:
    def calculate_next_decision(
        self, context: Dict[str, Any]
    ) -> int:
        """计算下次决策间隔（秒）"""
```

**调度策略**:
- 基础间隔：根据时间段调整
- 静默因子：用户静默时间越长，间隔越短
- 情绪因子：情绪低落时增加关怀频率
- 随机抖动：避免固定模式

### 7. ActiveCareVocabulary (词汇学习)

**文件**: `shared/vocabulary.py`

词汇学习，负责学习用户常用词汇：

```python
class ActiveCareVocabulary:
    async def learn_from_message(self, message: str):
        """从消息中学习词汇"""

    async def get_vocabulary_stats(self) -> Dict[str, Any]:
        """获取词汇统计"""
```

**学习内容**:
- 用户常用词汇
- 表达习惯
- 情感词汇

### 8. ActiveCareModeState (模式状态)

**文件**: `state/mode_state.py`

模式状态管理，支持多种关怀模式：

```python
class ActiveCareModeState:
    def get_current_mode(self) -> str:
        """获取当前模式"""

    def set_mode(self, mode: str):
        """设置模式"""
```

**支持模式**:
| 模式 | 说明 |
|------|------|
| normal | 正常模式 |
| focus | 专注模式（减少打扰） |
| sleep | 睡眠模式（静音） |
| busy | 忙碌模式（仅紧急提醒） |
