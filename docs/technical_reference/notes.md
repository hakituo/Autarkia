# 补充口径（角色上下文 / 即时私聊）

> 本文同步自项目内部技术参考，仅描述公开可见的实现。
> 由 `scripts/doc_records/sync_tech_docs.py` 生成，请勿直接编辑；修改请改真源后重新生成。
> 文档入口：[技术参考目录](README.md)

---

## 通用角色上下文（2026-09-15）

角色资料分层与工作集从 `core/agents/chat_agent_components/persona_system/prompt/layered_context.py`、`context_engine.py` 定位；配置入口 `meta.context_profile`，预算与生命周期在 `config/yaml/persona_context.yaml`。新角色支持单配置内嵌，无需复制角色专用代码；完整契约与实测脚本见 Prompt 目录 README。

## 即时私聊口径的全局落点（2026-10-16）

主对话的「短对话 / 不报备自己 / 不机械反问」三条口径不再依赖各角色人设，统一放在
**全局固定前置层** `core/agents/chat_agent_components/persona_system/prompt/fixed_prefix.txt`
（正文标题「[即时通讯基本法]」）。该层由 `assembler.build_persona_prompt_split` 注入主对话、
`active_care/prompt/sections/composer.py` 注入主动关怀，所有角色与渠道共用，且没有体积门禁；
`conversation_policy.json` 有 `verify_ye_prompt_ttft_optimization.py` 的 `< 1500` 字符门禁
（现 1423），新增长规则不要再往那里塞。

与之配套的两个代码落点：

- **长度上限**：`core/emotion/manager.py::_build_affect_instruction` 真正调用 `_resolve_length`，
  长度句才进 prompt。此前 `_resolve_length` 全仓只有定义、零调用点，`soft_reply_char_limit`
  传到底后被静默丢弃。`_resolve_length` 对 `>= 1000` 的「不限制」档不输出任何内容。
  上游 `stream_utils.StreamContextBuilder.infer_soft_reply_limit` 的 `mode` 判据已补：
  `study` 走不限制档，否则学习讲解会被默认的 50 字掐死。
- **活动背景**：`【角色当前活动背景】`（`dynamic_injections` 的 `character_daily` 项）只给事实、
  不给回复指导；被动回复侧 `character_daily/reply_hints.py` 与 `reply_policy_support.py`
  只提供可选措辞，不再命令角色提及自己在做什么。`activity_return` 的回归消息 instruction
  仍要求明确说出回去做什么——那是主动发出的告别，不在被动回复口径内。
- **活动时间线**：`character_daily/activity_timeline.py` 把 DailyPlan 中已结束与未开始的槽位投影为
  `recent_activities` / `upcoming_activities`（各 2 条，时间正序，当前 slot 不重复），
  由 `build_character_daily_context()` 统一注入，主对话与 Active Care 共用。此前角色只有
  `daily_activity`，看不到上一个与下一个活动。Active Care 的睡觉关键词过滤只扫
  `daily_activity` / `scheduled_activity` / `confirmed_activity` 这些「此刻」键，
  不会被时间线里的睡觉误伤整段活动锚点。
- **临时改活动**：`character_daily/plan_edit/service.py::change_activity()` 是 DailyPlan 槽位的唯一写入入口，
  按 `current` / `next` / `later+start_time` 定位槽位；空档期改当前活动会补一段临时槽位。
  写入后调用 `engine.refresh_current_activity()` 重算 `plan.current_activity` 并落盘，
  工具入口是 `update_character_daily_activity`（`character_daily` 新领域、按需加载）。
  ActivityInstance 以 `activity@planned_start` 为键，换活动即换键，旧实例自然失效。

防回归：`tests/unit/test_im_style_guardrails.py`（9 例）钉住上述判据。
