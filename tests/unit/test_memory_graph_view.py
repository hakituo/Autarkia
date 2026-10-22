"""加权记忆关系视图（``memory/core/graph_view.py``）与关系端点回归测试。

背景：加权记忆的呈现要从「时间桶树」转向「种子 + 邻里扩散」。关系图本体
早已存在（``relation_graph.py``），但只在检索 rerank 里用，前端拿不到任何边。
本文件固化对外视图的几条约束：

- 邻域视图不含中心节点本身，按「跳数 → 边强度 → 权重」排序；
- 未知记忆返回 ``None``，由端点翻成 404，不能静默返回空列表；
- ``thinking`` / ``deleted`` / ``superseded`` 默认不进图，避免把隐藏记忆画出来；
- 子图必须「边闭合」：任何边的两端都得在节点集合里，否则前端渲染会丢边。
"""

import threading

import pytest

from memory.core.graph_anchors import build_anchor_view
from memory.core.graph_view import (
    PREVIEW_LIMIT,
    build_graph_view,
    build_neighbor_view,
    relation_label,
)
from routers.v1 import memory_graph as memory_graph_router


class _Manager:
    def __init__(self, memories):
        self.weighted_memories = memories
        self.lock = threading.RLock()
        self._use_rw_lock = False


def _memory(
    memory_id: str,
    content: str,
    *,
    timestamp: float,
    weight: float = 5.0,
    role: str = "user",
    topics=None,
    metadata=None,
    category: str = "daily",
    status: str = "active",
    **extra,
):
    record = {
        "id": memory_id,
        "content": content,
        "timestamp": timestamp,
        "last_access_time": timestamp,
        "weight": weight,
        "topics": list(topics or []),
        "source": role,
        "role": role,
        "category": category,
        "memory_type": "dialogue",
        "status": status,
        "scopes": ["local", "user"],
        "metadata": dict(metadata or {}),
    }
    record.update(extra)
    return record


def _manager_with_neighbors():
    return _Manager(
        {
            "root": _memory(
                "root",
                "用户说想给记忆换一种呈现方式",
                timestamp=100.0,
                weight=6.0,
                topics=["记忆系统"],
                metadata={"turn_id": "turn-1"},
            ),
            "same-turn": _memory(
                "same-turn",
                "助手回答可以先用关系图试水",
                timestamp=101.0,
                weight=4.0,
                role="assistant",
                topics=["记忆系统"],
                metadata={"turn_id": "turn-1"},
            ),
            "parent": _memory(
                "parent",
                "更早一轮在聊安卓端界面",
                timestamp=99.0,
                weight=5.0,
                topics=["记忆系统"],
                metadata={"client_message_id": "android-parent"},
            ),
        }
    )


def test_neighbor_view_excludes_root_and_orders_by_distance():
    manager = _manager_with_neighbors()

    view = build_neighbor_view(manager, "root", limit=5)

    ids = [node["id"] for node in view["nodes"]]
    assert view["root_id"] == "root"
    assert ids and "root" not in ids
    assert view["nodes"][0]["graph_distance"] == 1
    assert view["nodes"][0]["relation_label"] == relation_label(
        view["nodes"][0]["relation"]
    )
    assert view["truncated"] is False
    # 边必须闭合在 root + 邻居上
    allowed = set(ids) | {"root"}
    assert all(edge["source"] in allowed and edge["target"] in allowed for edge in view["edges"])
    assert any(edge["source"] == "root" or edge["target"] == "root" for edge in view["edges"])


def test_neighbor_view_returns_none_for_unknown_memory():
    manager = _manager_with_neighbors()

    assert build_neighbor_view(manager, "missing") is None


def test_neighbor_view_preview_falls_back_to_summary_and_truncates():
    long_text = "很长的记忆正文" * 40
    summary_only = _memory("a", "", timestamp=100.0, topics=["记忆系统"], summary="只有摘要")
    long_memory = _memory("b", long_text, timestamp=101.0, topics=["记忆系统"])
    manager = _Manager(
        {
            "root": _memory("root", "中心", timestamp=99.0, topics=["记忆系统"]),
            "a": summary_only,
            "b": long_memory,
        }
    )

    view = build_neighbor_view(manager, "root", limit=5, max_depth=2)
    previews = {node["id"]: node["preview"] for node in view["nodes"]}

    assert previews["a"] == "只有摘要"
    assert previews["b"].endswith("…")
    assert len(previews["b"]) <= PREVIEW_LIMIT + 1


def test_neighbor_view_hides_thinking_and_superseded():
    manager = _Manager(
        {
            "root": _memory("root", "中心", timestamp=100.0, topics=["记忆系统"]),
            "thinking": _memory(
                "thinking",
                "内部推理过程",
                timestamp=101.0,
                topics=["记忆系统"],
                category="thinking",
            ),
            "old": _memory(
                "old",
                "已被替代的旧记录",
                timestamp=102.0,
                topics=["记忆系统"],
                status="superseded",
            ),
        }
    )

    default_view = build_neighbor_view(manager, "root", limit=5, max_depth=2)
    assert default_view["nodes"] == []

    # 放开 thinking 后，「old」会经由 thinking 进入 2 跳邻域，此时仍应被 status 过滤
    with_thinking = build_neighbor_view(
        manager, "root", limit=5, max_depth=2, include_thinking=True
    )
    ids = [node["id"] for node in with_thinking["nodes"]]
    assert "thinking" in ids
    assert "old" not in ids


def test_graph_view_with_seed_keeps_edges_closed():
    manager = _manager_with_neighbors()

    view = build_graph_view(manager, seed_id="root", limit=10, max_depth=2)

    ids = {node["id"] for node in view["nodes"]}
    assert "root" in ids
    assert view["root_id"] == "root"
    assert view["nodes"][0]["id"] == "root"
    assert all(edge["source"] in ids and edge["target"] in ids for edge in view["edges"])
    assert view["edges"]


def test_graph_view_overview_respects_node_cap_and_starts_from_heaviest():
    manager = _Manager(
        {
            "heavy": _memory("heavy", "权重最高", timestamp=100.0, weight=9.0, topics=["记忆系统"]),
            "mid": _memory("mid", "中等权重", timestamp=101.0, weight=4.0, topics=["记忆系统"]),
            "light": _memory("light", "权重最低", timestamp=102.0, weight=1.0, topics=["记忆系统"]),
        }
    )

    view = build_graph_view(manager, limit=2, max_depth=1)

    ids = [node["id"] for node in view["nodes"]]
    assert view["root_id"] == ""
    assert len(ids) <= 2
    assert ids[0] == "heavy"
    assert view["truncated"] is True


def test_graph_view_returns_empty_for_unknown_seed():
    manager = _manager_with_neighbors()

    view = build_graph_view(manager, seed_id="missing", limit=5)

    assert view["nodes"] == []
    assert view["edges"] == []


def test_anchor_view_groups_same_day_and_topic():
    manager = _Manager(
        {
            "a1": _memory("a1", "第一条", timestamp=100.0, weight=2.0, topics=["记忆系统"]),
            "a2": _memory("a2", "第二条", timestamp=101.0, weight=7.0, topics=["记忆系统"]),
            "b1": _memory("b1", "另一天的记录", timestamp=200000.0, weight=1.0, topics=["记忆系统"]),
            "c1": _memory("c1", "别的话题", timestamp=102.0, weight=1.0, topics=["做饭"]),
        }
    )

    anchors = build_anchor_view(manager, limit=8)

    by_id = {anchor["id"]: anchor for anchor in anchors}
    assert by_id["a2"]["member_count"] == 2
    assert by_id["a2"]["weight"] == pytest.approx(9.0)
    assert by_id["a2"]["relation"] == "anchor"
    assert by_id["a2"]["title"].endswith("记忆系统")
    assert {"b1", "c1"} <= set(by_id)


def test_anchor_view_orders_by_aggregate_weight_and_respects_limit():
    manager = _Manager(
        {
            "big1": _memory("big1", "一", timestamp=100.0, weight=4.0, topics=["记忆系统"]),
            "big2": _memory("big2", "二", timestamp=101.0, weight=4.0, topics=["记忆系统"]),
            "small": _memory("small", "三", timestamp=102.0, weight=1.0, topics=["做饭"]),
        }
    )

    anchors = build_anchor_view(manager, limit=1)

    assert len(anchors) == 1
    # 同权重时取更新的那条当代表，地标名才不会钉在最老的一条上
    assert anchors[0]["id"] == "big2"
    assert anchors[0]["member_count"] == 2


def test_anchor_view_skips_hidden_memories():
    manager = _Manager(
        {
            "keep": _memory("keep", "保留", timestamp=100.0, topics=["记忆系统"]),
            "think": _memory(
                "think", "内部推理", timestamp=101.0, topics=["记忆系统"], category="thinking"
            ),
            "gone": _memory(
                "gone", "已替代", timestamp=102.0, topics=["记忆系统"], status="superseded"
            ),
        }
    )

    anchors = build_anchor_view(manager)

    assert [anchor["id"] for anchor in anchors] == ["keep"]
    assert anchors[0]["member_count"] == 1


def test_anchor_title_skips_uncategorized_topic():
    manager = _Manager(
        {
            "x": _memory(
                "x",
                "没有话题的零散记录",
                timestamp=100.0,
                topics=[],
                category="uncategorized",
            ),
        }
    )

    anchors = build_anchor_view(manager)

    # 「1月1日 · 未分类」这种标题只是噪音，只留日期
    assert anchors[0]["title"] == "1月1日"


def test_anchor_view_returns_empty_for_empty_manager():
    assert build_anchor_view(_Manager({})) == []


@pytest.mark.asyncio
async def test_anchors_endpoint_returns_anchor_list(monkeypatch):
    manager = _Manager(
        {
            "a1": _memory("a1", "第一条", timestamp=100.0, topics=["记忆系统"]),
            "a2": _memory("a2", "第二条", timestamp=101.0, topics=["记忆系统"]),
        }
    )
    monkeypatch.setattr(memory_graph_router, "_wmm", lambda *args, **kwargs: manager)

    result = await memory_graph_router.get_memory_anchors(
        user_id="default",
        persona=None,
        limit=5,
        include_thinking=False,
    )

    assert result["status"] == "success"
    assert len(result["data"]["anchors"]) == 1
    assert result["data"]["anchors"][0]["member_count"] == 2


@pytest.mark.asyncio
async def test_relations_endpoint_reports_missing_memory(monkeypatch):
    manager = _manager_with_neighbors()
    monkeypatch.setattr(memory_graph_router, "_wmm", lambda *args, **kwargs: manager)

    result = await memory_graph_router.get_memory_relations(
        "missing",
        user_id="default",
        persona=None,
        limit=5,
        depth=1,
        include_thinking=False,
    )

    assert result["status"] == "error"
    assert "missing" in result["message"]


@pytest.mark.asyncio
async def test_relations_endpoint_returns_neighbors(monkeypatch):
    manager = _manager_with_neighbors()
    monkeypatch.setattr(memory_graph_router, "_wmm", lambda *args, **kwargs: manager)

    result = await memory_graph_router.get_memory_relations(
        "root",
        user_id="default",
        persona=None,
        limit=5,
        depth=1,
        include_thinking=False,
    )

    assert result["status"] == "success"
    assert result["data"]["root_id"] == "root"
    assert result["data"]["nodes"]
    assert all(node["id"] != "root" for node in result["data"]["nodes"])


@pytest.mark.asyncio
async def test_graph_endpoint_returns_subgraph(monkeypatch):
    manager = _manager_with_neighbors()
    monkeypatch.setattr(memory_graph_router, "_wmm", lambda *args, **kwargs: manager)

    result = await memory_graph_router.get_memory_graph(
        user_id="default",
        persona=None,
        seed_id="root",
        limit=10,
        depth=2,
        include_thinking=False,
    )

    assert result["status"] == "success"
    assert {node["id"] for node in result["data"]["nodes"]} >= {"root"}
