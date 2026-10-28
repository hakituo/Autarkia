"""WeightedMemoryManager 的历史与权重查询。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class WeightedManagerQueryMixin:
    """只读历史和权重查询职责。"""

    def get_memories_by_topic(self, topic: str, limit: int = 10) -> List[Dict[str, Any]]:
        target = str(topic or "").strip()
        if not target or limit <= 0:
            return []
        candidates: List[Dict[str, Any]] = []
        lock_ctx = self._rw_lock.read_lock() if self._use_rw_lock else self.lock
        with lock_ctx:
            self._perf_stats["rw_lock_reads"] += 1
            for memory in reversed(self.short_term_memory):
                topics = memory.get("topics")
                if isinstance(topics, list) and target in topics:
                    candidates.append(memory.copy())
                    if len(candidates) >= limit:
                        return candidates
            for memory in reversed(list(self.weighted_memories.values())):
                topics = memory.get("topics")
                if isinstance(topics, list) and target in topics:
                    candidates.append(memory.copy())
                    if len(candidates) >= limit:
                        return candidates
        return candidates

    def get_history(
        self,
        scope: Optional[str] = None,
        raw: bool = False,
        exclude_categories: Optional[List[str]] = None,
        exclude_sensitive: bool = False,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        try:
            limit_value = int(limit) if limit is not None else None
        except (TypeError, ValueError):
            limit_value = None
        if limit_value is not None and limit_value <= 0:
            return []

        def apply_limit(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            if limit_value is None or len(items) <= limit_value:
                return items
            return items[-limit_value:]

        lock_ctx = self._rw_lock.read_lock() if self._use_rw_lock else self.lock
        with lock_ctx:
            self._perf_stats["rw_lock_reads"] += 1
            if raw:
                if not scope and not exclude_categories and not exclude_sensitive:
                    return apply_limit(list(self.short_term_memory))
                filtered_raw: List[Dict[str, Any]] = []
                for memory in self.short_term_memory:
                    category = memory.get("category")
                    if exclude_categories and category in exclude_categories:
                        continue
                    if exclude_sensitive and category == "sensitive":
                        continue
                    scopes = memory.get("scopes")
                    if not scope or scopes is None or (
                        isinstance(scopes, list) and scope in scopes
                    ):
                        filtered_raw.append(memory)
                return apply_limit(filtered_raw)

            history: List[Dict[str, Any]] = []
            for memory in self.short_term_memory:
                category = memory.get("category")
                if exclude_categories and category in exclude_categories:
                    continue
                if exclude_sensitive and category == "sensitive":
                    continue
                scopes = memory.get("scopes")
                if scope and scopes and scope not in scopes:
                    continue
                role = memory.get("role", memory.get("source", "user"))
                if role not in ("system", "user", "assistant", "tool"):
                    role = "system"
                entry: Dict[str, Any] = {
                    "role": role,
                    "content": memory.get("content", ""),
                    "timestamp": memory.get("timestamp", 0),
                }
                if category:
                    entry["category"] = category
                metadata = memory.get("metadata")
                if isinstance(metadata, dict) and metadata.get("platform"):
                    entry["platform"] = str(metadata["platform"])
                if role == "assistant":
                    if isinstance(metadata, dict):
                        if metadata.get("reasoning_content"):
                            entry["reasoning_content"] = metadata["reasoning_content"]
                        if metadata.get("is_proactive"):
                            entry["is_proactive"] = True
                        if metadata.get("is_peer_script"):
                            entry["is_peer_script"] = True
                    if memory.get("tool_calls"):
                        entry["tool_calls"] = memory["tool_calls"]
                if role == "tool" and isinstance(metadata, dict) and metadata.get("tool_call_id"):
                    entry["tool_call_id"] = metadata["tool_call_id"]
                history.append(entry)
            return apply_limit(history)

    def get_weighted_memories(
        self,
        min_weight: float = None,
        topics: List[str] = None,
        limit: int = 10,
        category: str = None,
        emotion: str = None,
        exclude_categories: Optional[List[str]] = None,
        exclude_sensitive: bool = False,
        offset: int = 0,
        sort_by: str = "weight",
    ) -> List[Dict[str, Any]]:
        filtered = self._collect_weighted_memories(
            min_weight=min_weight,
            topics=topics,
            category=category,
            emotion=emotion,
            exclude_categories=exclude_categories,
            exclude_sensitive=exclude_sensitive,
            sort_by=sort_by,
        )
        offset_value, limit_value = self._pagination_bounds(offset, limit)
        return filtered[offset_value: offset_value + limit_value]

    def get_weighted_memories_page(
        self,
        min_weight: float = None,
        topics: List[str] = None,
        limit: int = 10,
        category: str = None,
        emotion: str = None,
        exclude_categories: Optional[List[str]] = None,
        exclude_sensitive: bool = False,
        offset: int = 0,
        sort_by: str = "weight",
    ) -> tuple[List[Dict[str, Any]], int]:
        """返回一页记忆与过滤后的总条数，供列表接口做 offset 懒加载。"""
        filtered = self._collect_weighted_memories(
            min_weight=min_weight,
            topics=topics,
            category=category,
            emotion=emotion,
            exclude_categories=exclude_categories,
            exclude_sensitive=exclude_sensitive,
            sort_by=sort_by,
        )
        offset_value, limit_value = self._pagination_bounds(offset, limit)
        return filtered[offset_value: offset_value + limit_value], len(filtered)

    def _collect_weighted_memories(
        self,
        min_weight: float = None,
        topics: List[str] = None,
        category: str = None,
        emotion: str = None,
        exclude_categories: Optional[List[str]] = None,
        exclude_sensitive: bool = False,
        sort_by: str = "weight",
    ) -> List[Dict[str, Any]]:
        lock_ctx = self._rw_lock.read_lock() if self._use_rw_lock else self.lock
        with lock_ctx:
            self._perf_stats["rw_lock_reads"] += 1
            access_counts = (
                dict(getattr(self, "_cache", {}).get("access_count", {}))
                if sort_by == "accessed"
                else {}
            )
            if category:
                memories = [
                    self.weighted_memories[memory_id].copy()
                    for memory_id in self.category_index.get(category, [])
                    if memory_id in self.weighted_memories
                ]
            else:
                memories = [memory.copy() for memory in self.weighted_memories.values()]

        filtered: List[Dict[str, Any]] = []
        for memory in memories:
            if memory.get("content", "").startswith("SYSTEM_COMMAND:"):
                continue
            memory_category = memory.get("category")
            if exclude_categories and memory_category in exclude_categories:
                continue
            if exclude_sensitive and memory_category == "sensitive":
                continue
            decayed_weight = self.weight_calculator.apply_time_decay(
                memory["weight"], memory["timestamp"], category=memory_category
            )
            if min_weight is not None and decayed_weight < min_weight:
                continue
            if topics and not any(topic in memory.get("topics", []) for topic in topics):
                continue
            if category and memory_category != category:
                continue
            updated = memory.copy()
            updated["weight"] = decayed_weight
            if emotion and emotion in memory.get("emotions", []):
                updated["weight"] *= 1.2
            filtered.append(updated)
        filtered.sort(key=lambda item: self._weighted_sort_key(item, sort_by, access_counts))
        return filtered

    @staticmethod
    def _pagination_bounds(offset: Any, limit: Any) -> tuple[int, int]:
        try:
            offset_value = max(0, int(offset))
        except (TypeError, ValueError):
            offset_value = 0
        try:
            limit_value = max(0, int(limit))
        except (TypeError, ValueError):
            limit_value = 0
        return offset_value, limit_value

    @classmethod
    def _weighted_sort_key(
        cls,
        memory: Dict[str, Any],
        sort_by: str,
        access_counts: Dict[str, int],
    ) -> tuple:
        memory_id = str(memory.get("id") or "")
        weight = cls._sort_number(memory.get("weight"))
        if sort_by == "newest":
            return (-cls._sort_number(memory.get("timestamp")), memory_id)
        if sort_by == "oldest":
            return (cls._sort_number(memory.get("timestamp"), float("inf")), memory_id)
        if sort_by == "accessed":
            try:
                access_count = int(access_counts.get(memory_id, 0))
            except (TypeError, ValueError):
                access_count = 0
            return (-access_count, -weight, memory_id)
        if sort_by == "important":
            raw_importance = memory.get("importance")
            importance = (
                weight
                if raw_importance is None
                else cls._sort_number(raw_importance, weight)
            )
            return (-importance, -weight, memory_id)
        return (-weight, memory_id)

    @staticmethod
    def _sort_number(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
