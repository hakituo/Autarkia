"""汇总配对结果，生成每会话覆盖率报告（预览）。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Sequence

from core.utils.time.time_utils import now_iso

from .matcher import match_session
from .model import EventDecision, RoomSession


def _coverage(matched: int, total: int) -> float:
    return round(matched / total, 4) if total else 0.0


def _brief(decision: EventDecision) -> Dict[str, Any]:
    return {
        "event_id": decision.event_id,
        "role": decision.role,
        "event_type": decision.event_type,
        "occurred_at": decision.occurred_at,
        "client_node_id": decision.client_node_id,
        "match_method": decision.match_method,
        "confidence": decision.confidence,
        "reason": decision.reason,
        "duplicate_submission": decision.duplicate_submission,
        "parent_without_event": decision.parent_without_event,
    }


@dataclass
class SessionPlan:
    session: RoomSession
    storage_scope: str
    decisions: List[EventDecision]

    def counts(self) -> Dict[str, Any]:
        window_start = self.session.window_start
        in_window = [d for d in self.decisions if d.occurred_at >= window_start]
        matched = [d for d in self.decisions if d.matched]
        matched_in_window = [d for d in matched if d.occurred_at >= window_start]
        unmatched_in_window = [
            d for d in self.decisions if not d.matched and d.occurred_at >= window_start
        ]
        broken_parents = {d.parent_node_id for d in self.decisions if d.parent_without_event}
        empty_parents = sum(
            1
            for parent_id in broken_parents
            if (node := self.session.nodes.get(parent_id)) is None
            or not node.text.strip()
        )
        return {
            "server_events": len(self.decisions),
            "before_window": len(self.decisions) - len(in_window),
            "in_window": len(in_window),
            "matched": len(matched),
            "matched_in_window": len(matched_in_window),
            "coverage_in_window": _coverage(len(matched_in_window), len(in_window)),
            "coverage_total": _coverage(len(matched), len(self.decisions)),
            "by_role": dict(Counter(d.role for d in matched_in_window)),
            "by_method": dict(Counter(d.match_method for d in matched)),
            "by_confidence": dict(Counter(d.confidence for d in matched)),
            "unmatched": len(unmatched_in_window),
            "unmatched_total": sum(1 for d in self.decisions if not d.matched),
            "reasons": dict(Counter(d.reason for d in unmatched_in_window)),
            "duplicate_submissions": sum(
                1 for d in self.decisions if d.duplicate_submission
            ),
            "parent_without_event": sum(
                1 for d in self.decisions if d.parent_without_event
            ),
            "parent_without_event_nodes": len(broken_parents),
            "empty_structural_parents": empty_parents,
            "roots": sum(1 for d in matched if d.is_root),
        }

    def report(self, *, max_samples: int = 5) -> Dict[str, Any]:
        counts = self.counts()
        window_start = self.session.window_start
        unmatched = [
            d
            for d in self.decisions
            if not d.matched and d.occurred_at >= window_start
        ]
        medium = [
            d for d in self.decisions if d.matched and d.confidence != "high"
        ]
        broken_parent = [d for d in self.decisions if d.parent_without_event]
        return {
            "storage_scope": self.storage_scope,
            "phone": {
                "nodes": len(self.session.nodes),
                "user_nodes": len(self.session.user_nodes),
                "assistant_nodes": len(self.session.assistant_nodes),
                "chains": len(self.session.chains),
                "window_start": window_start,
                "active_path_len": len(self.session.active_path),
                "integrity": dict(self.session.integrity),
            },
            "events": counts,
            "samples": {
                "unmatched": [_brief(d) for d in unmatched[:max_samples]],
                "medium_confidence": [_brief(d) for d in medium[:max_samples]],
                "parent_without_event": [
                    _brief(d) for d in broken_parent[:max_samples]
                ],
            },
        }


@dataclass
class BackfillPlan:
    sessions: Dict[str, SessionPlan] = field(default_factory=dict)
    generated_at: str = field(default_factory=now_iso)

    def iter_decisions(self) -> Iterable[EventDecision]:
        for session_plan in self.sessions.values():
            yield from session_plan.decisions

    def totals(self) -> Dict[str, Any]:
        totals: Dict[str, Any] = {
            "sessions": len(self.sessions),
            "server_events": 0,
            "before_window": 0,
            "in_window": 0,
            "matched": 0,
            "matched_in_window": 0,
            "unmatched": 0,
            "unmatched_total": 0,
            "duplicate_submissions": 0,
            "parent_without_event": 0,
            "parent_without_event_nodes": 0,
            "empty_structural_parents": 0,
            "by_role": Counter(),
            "by_method": Counter(),
        }
        for session_plan in self.sessions.values():
            counts = session_plan.counts()
            for key in (
                "server_events",
                "before_window",
                "in_window",
                "matched",
                "matched_in_window",
                "unmatched",
                "unmatched_total",
                "duplicate_submissions",
                "parent_without_event",
                "parent_without_event_nodes",
                "empty_structural_parents",
            ):
                totals[key] += int(counts[key])
            totals["by_role"].update(counts["by_role"])
            totals["by_method"].update(counts["by_method"])
        totals["by_role"] = dict(totals["by_role"])
        totals["by_method"] = dict(totals["by_method"])
        totals["coverage_in_window"] = _coverage(
            totals["matched_in_window"], totals["in_window"]
        )
        totals["coverage_total"] = _coverage(
            totals["matched"], totals["server_events"]
        )
        return totals

    def report(self, *, max_samples: int = 5) -> Dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "totals": self.totals(),
            "sessions": {
                conversation_id: session_plan.report(max_samples=max_samples)
                for conversation_id, session_plan in sorted(self.sessions.items())
            },
        }


def _majority_scope(scopes: Sequence[str]) -> str:
    values = [scope for scope in scopes if scope]
    return Counter(values).most_common(1)[0][0] if values else ""


def build_plan(
    room_sessions: Dict[str, RoomSession],
    events_by_conversation: Dict[str, List[Dict[str, Any]]],
    scopes_by_conversation: Dict[str, List[str]],
) -> BackfillPlan:
    plan = BackfillPlan()
    for conversation_id, session in sorted(room_sessions.items()):
        events = list(events_by_conversation.get(conversation_id, []))
        plan.sessions[conversation_id] = SessionPlan(
            session=session,
            storage_scope=_majority_scope(
                scopes_by_conversation.get(conversation_id, [])
            ),
            decisions=match_session(session, events),
        )
    return plan


__all__ = ["BackfillPlan", "SessionPlan", "build_plan"]
