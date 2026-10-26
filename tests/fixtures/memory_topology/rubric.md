# 消息树 / 世界线评测 rubric（C5）

配套 fixtures：`synthetic_trees.json`（合成数据，可入库）；真实脱敏标注集放在
运行数据目录（`companion_data/**/evaluation/`），**不进仓库**。

## 评分维度（每项 0/1，全部通过才算该用例通过）

| 维度 | 判定 |
| --- | --- |
| 可见性正确 | anchor 路径上的事件可见；兄弟分支、缺 anchor 的树、namespace/perspective 不符一律不可见 |
| fail-closed | anchor 缺失 / 树 partial 且节点 pending / legacy unknown 在 strict 模式下不可见，且原因码正确 |
| 拓扑确定性 | 事件乱序重放后 `canonical_hash` 不变；child-before-parent 可解析 |
| provenance | note 的 source refs 展开后逐条重走 raw 路径；`namespace_shared` 只豁免 note 本身 |
| 内容门控 | 媒体占位 / debug / 系统 / thought 不进提炼正文，但父链完整 |
| 幂等 | 同 `idempotency_key` 重投不产生第二条；`event_id` 不参与幂等判定 |
| 分段边界 | 只在完整 turn 边界封口；不按 04:00/自然日强断；"parent 跨段"不触发封口 |

## 固定调参集与 held-out

- 调参集：`replay.py` 里的 `COMPARISON_PARAMS`（30/40/8000 等），只用于离线对照。
- held-out：真实标注集按天切片随机留出 ≥20%，不参与任何调参；两集合不许重叠。
- 报告必须带样本量与分母；比率无分母视为无效结果。

## 已覆盖 / 待补用例

- 已覆盖（fixtures）：共享祖先+兄弟隔离、child-before-parent、缺 parent、重复投递、
  媒体占位保链、多平台同 continuity、legacy unknown 的 strict/compat 行为。
- 待补（拓扑层）：切线回退（A→B→A 可见集一致）、多兄弟排序、群聊多 actor、
  知识更新（`superseded_by`/`valid_to`）、未知问题拒答——依赖 E5/F6/G2 落地后补 fixtures。
  其中知识更新与拒答已在 `extraction_e2e_cases.json` 的内容层实验覆盖，
  拓扑层仍待 F6/G2 提供 `superseded_by` 与结构化证据接口。

## C6/C7 离线实验（2026-10-25）

- 数据：`extraction_e2e_cases.json`（10 个合成案例 / 90 条消息 / 20 个问题 / 25 条金标事实），
  覆盖知识更新、时间推理、多会话事实、兄弟分支、拒答、数字时间、长段稀释。
- 实验臂：A 逐消息摘要；B segment 单 episode；C raw turns + segment fact 扩展。
- 控制：同一 provider/model（默认 `minimax-plan` / `MiniMax-M3.1-Flash`）、temperature=0、
  同一 system prompt、同一输入证据与预算；检索统一 BM25 + jieba。
- 预注册决策：先过硬约束（provenance=100%、解析零失败、过滤后跨线=0），
  再比端到端正确率与 Recall@k；候选不得低于 A。样本量与 95% 区间必须一起报告。
- 复算命令：`scripts/experiments/weighted_memory/run_c6.py` → `run_c7.py`（缓存可重跑不计费）。
- 2026-10-25 结果：Flash / M3 均为 C 臂端到端最优（19/20）；F3 候选形态 = C；默认模型 Flash。

