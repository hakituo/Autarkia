"""消息树拓扑层：规范化事件、确定性建树、逐树 anchor 与可见性谓词。

这一层只做纯计算 + 受控持久化，不依赖 WeightedMemoryManager：
- ``events``：原始事件字段规范、内容门控、幂等键；
- ``tree``：同一事件集无论到达顺序都能重建出同一棵树；
- ``anchors``：逐 tree 游标（``anchors_by_tree``）与切线事件；
- ``read_context``：namespace / perspective / continuity / 路径 / as-of 五段硬过滤。
"""
