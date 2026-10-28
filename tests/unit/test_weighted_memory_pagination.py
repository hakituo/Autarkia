"""memory/weighted_manager/queries.py 分页与排序单元测试

覆盖策略：
- 直接实例化查询 mixin，用鸭子类型替身提供锁、权重计算器与记忆字典；
- 权重衰减替身返回原权重，时间戳全部固定，结果确定；
- 不启动真实存储层，不依赖本机数据。
"""

import contextlib

from memory.weighted_manager.queries import WeightedManagerQueryMixin

SORT_COUNT = 13


class _FixedWeightCalculator:
    """时间衰减替身：直接返回原权重，保证排序断言只受测试数据影响"""

    def apply_time_decay(self, weight, timestamp, category=None):
        return float(weight)


class _QueryManager(WeightedManagerQueryMixin):
    """只提供查询 mixin 所需属性的最小管理器"""

    def __init__(self, memories, access_counts=None):
        self.weighted_memories = {memory["id"]: memory for memory in memories}
        self.category_index = {}
        for memory in memories:
            category = memory.get("category")
            self.category_index.setdefault(category, []).append(memory["id"])
        self._rw_lock = None
        self._use_rw_lock = False
        self.lock = contextlib.nullcontext()
        self._perf_stats = {"rw_lock_reads": 0}
        self.weight_calculator = _FixedWeightCalculator()
        self._cache = {"access_count": dict(access_counts or {})}


def _memory(index, category="daily", **overrides):
    memory = {
        "id": f"m{index:02d}",
        "content": f"记忆 {index}",
        "category": category,
        "weight": float(index),
        "timestamp": float(2000 - index),
        "importance": float((index * 7) % SORT_COUNT),
        "topics": ["topic-a" if index % 2 == 0 else "topic-b"],
        "emotions": [],
    }
    memory.update(overrides)
    return memory


def _manager(count=SORT_COUNT):
    memories = [_memory(index) for index in range(count)]
    access_counts = {
        memory["id"]: (index * 3) % SORT_COUNT for index, memory in enumerate(memories)
    }
    return _QueryManager(memories, access_counts)


def _ids(items):
    return [memory["id"] for memory in items]


def test_weighted_page_slices_without_overlap_and_reports_total():
    manager = _QueryManager([_memory(index) for index in range(1200)])

    first, total = manager.get_weighted_memories_page(limit=500)
    second, second_total = manager.get_weighted_memories_page(limit=500, offset=500)
    third, third_total = manager.get_weighted_memories_page(limit=500, offset=1000)

    assert total == second_total == third_total == 1200
    assert (len(first), len(second), len(third)) == (500, 500, 200)
    ids = _ids(first) + _ids(second) + _ids(third)
    assert len(ids) == len(set(ids)) == 1200


def test_offset_beyond_total_returns_empty_but_keeps_total():
    manager = _manager()

    page, total = manager.get_weighted_memories_page(limit=500, offset=500)

    assert page == []
    assert total == SORT_COUNT


def test_sort_modes_are_applied_before_paging():
    manager = _manager()

    assert _ids(manager.get_weighted_memories(limit=3, sort_by="weight")) == [
        "m12",
        "m11",
        "m10",
    ]
    assert _ids(manager.get_weighted_memories(limit=3, sort_by="newest")) == [
        "m00",
        "m01",
        "m02",
    ]
    assert _ids(manager.get_weighted_memories(limit=3, sort_by="oldest")) == [
        "m12",
        "m11",
        "m10",
    ]
    assert _ids(manager.get_weighted_memories(limit=3, sort_by="accessed")) == [
        "m04",
        "m08",
        "m12",
    ]
    assert _ids(manager.get_weighted_memories(limit=3, sort_by="important")) == [
        "m11",
        "m09",
        "m07",
    ]


def test_important_sort_falls_back_to_weight_when_importance_missing():
    memories = [_memory(index) for index in range(3)]
    memories[1].pop("importance")
    manager = _QueryManager(memories)

    assert _ids(manager.get_weighted_memories(limit=3, sort_by="important")) == [
        "m02",
        "m01",
        "m00",
    ]


def test_filters_apply_before_pagination():
    memories = [_memory(index) for index in range(6)]
    memories.extend(_memory(100 + index, category="thinking") for index in range(3))
    manager = _QueryManager(memories)

    page, total = manager.get_weighted_memories_page(
        limit=500, exclude_categories=["thinking"]
    )

    assert total == 6
    assert {memory["category"] for memory in page} == {"daily"}


def test_min_weight_filter_narrows_total():
    manager = _manager(6)

    page, total = manager.get_weighted_memories_page(limit=500, min_weight=3.0)

    assert total == 3
    assert _ids(page) == ["m05", "m04", "m03"]


def test_category_filter_uses_index_and_page_total():
    memories = [_memory(index, category="daily") for index in range(4)]
    memories.extend(_memory(10 + index, category="work") for index in range(3))
    manager = _QueryManager(memories)

    page, total = manager.get_weighted_memories_page(category="work", limit=2)

    assert total == 3
    assert _ids(page) == ["m12", "m11"]


def test_pagination_bounds_clamp_invalid_values():
    manager = _manager()

    empty_page, total = manager.get_weighted_memories_page(limit=0)
    assert empty_page == []
    assert total == SORT_COUNT

    empty_page, total = manager.get_weighted_memories_page(offset=-5, limit=-1)
    assert empty_page == []
    assert total == SORT_COUNT

    empty_page, total = manager.get_weighted_memories_page(offset="bad", limit="bad")
    assert empty_page == []
    assert total == SORT_COUNT


def test_legacy_weighted_query_honours_offset():
    manager = _manager()

    assert _ids(manager.get_weighted_memories(limit=3, offset=3)) == ["m09", "m08", "m07"]
