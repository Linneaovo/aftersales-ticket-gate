from __future__ import annotations

import re
from typing import Any, Literal, TypedDict

from app.domain.intent_rules import (
    ACL_PROBE_TOKENS,
    ACTION_TOKENS,
    CHAT_TOKENS,
    CONFLICT_TOKENS,
    DISPATCH_TOKENS,
    FAULT_CODE_RE,
    FAULT_SYMPTOM_TOKENS,
    INJECTION_TOKENS,
    KNOWLEDGE_QUERY_TOKENS,
    WEAK_ACTION_TOKENS,
)

Intent = Literal[
    "fault_dispatch",
    "knowledge_only",
    "conflict_review",
    "chitchat",
    "injection",
    "acl_probe",
]

RunStatus = Literal[
    "running",
    "waiting_hitl",
    "succeeded",
    "failed",
    "rejected",
    "cancelled",
]

RoleName = Literal["technician", "parts_clerk", "station_chief", "finance", "general"]

# 兼容旧 import：词表来自 data/intent_rules.json
__all__ = [
    "Intent",
    "RunStatus",
    "RoleName",
    "FAULT_CODE_RE",
    "FAULT_SYMPTOM_TOKENS",
    "ACTION_TOKENS",
    "CHAT_TOKENS",
    "INJECTION_TOKENS",
    "ACL_PROBE_TOKENS",
    "CONFLICT_TOKENS",
    "DISPATCH_TOKENS",
    "WEAK_ACTION_TOKENS",
    "KNOWLEDGE_QUERY_TOKENS",
    "CopilotState",
    "empty_state",
    "copy_state",
    "merge_state",
]


class ConflictBundle(TypedDict, total=False):
    present: bool
    items: list[dict[str, Any]]
    policy: str
    reason: str
    requires_chief: bool
    sources_pair: list[Any]


class CriticReport(TypedDict, total=False):
    passed: bool
    reasons: list[str]
    risk_level: Literal["low", "medium", "high"]
    force_hitl: bool
    policy_ids: list[str]


class PartsCheck(TypedDict, total=False):
    needed: bool
    items: list[dict[str, Any]]
    shortage: bool
    shortage_items: list[str]
    alt_depot: str
    suggested_action: str
    note: str


def copy_state(state: CopilotState) -> CopilotState:
    """深拷贝 state，避免节点间嵌套 dict/list 共享引用。"""
    import copy

    return copy.deepcopy(state)  # type: ignore[return-value]


def merge_state(state: CopilotState, **updates: Any) -> CopilotState:
    """浅拷贝并合并局部字段，供 runner/API/持久化层使用。"""
    out = copy_state(state)
    for key, value in updates.items():
        out[key] = value  # type: ignore[literal-required]
    return out  # type: ignore[return-value]


class HitlState(TypedDict, total=False):
    required: bool
    prompt: str
    reasons: list[str]
    decision: Literal["approve", "reject", "edit"] | None
    note: str
    resolved: bool
    approver_key_role: str


class ServiceTicket(TypedDict, total=False):
    machine_model: str
    fault_codes: list[str]
    station: str
    second_visit: bool
    sla_class: str
    response_hours: int
    warranty_claim: bool
    urgent: bool
    raw_excerpt: str


class CopilotState(TypedDict, total=False):
    run_id: str
    api_key: str
    role: str
    knowledge_base: str
    raw_input: str
    history: list[dict[str, Any]]
    auto_submit: bool
    max_iterations: int
    iteration: int
    intent: Intent
    next_action: str
    plan: list[str]
    rag_result: dict[str, Any]
    retrieve_hits: list[dict[str, Any]]
    conflict_bundle: ConflictBundle | None
    critic_report: CriticReport | None
    parts_check: PartsCheck | None
    work_order_draft: dict[str, Any] | None
    work_order_submit: dict[str, Any] | None
    parts_force_hints: list[str]
    hitl: HitlState
    submit_eligible: bool
    status: RunStatus
    final_summary: str
    error: str
    trace_events: list[dict[str, Any]]
    engine: str
    service_ticket: ServiceTicket
    station_context: dict[str, Any]
    sla_flags: dict[str, Any]
    rag_linkage: list[str]
    rag_linkage_detail: dict[str, Any]
    api_key_fp: str
    rag_degraded: bool
    rag_offline_mode: bool
    engine_degraded: bool
    engine_degraded_reason: str
    execution_path: str
    work_order_state: str
    feedback_ref: dict[str, Any] | None
    role_path: dict[str, Any]
    route_history: list[str]
    station_override: str
    second_visit_override: bool | None
    sla_class_override: str


def empty_state(**kwargs: Any) -> CopilotState:
    from app.domain.station import default_station_context

    base: CopilotState = {
        "run_id": "",
        "api_key": "demo-key",
        "role": "technician",
        "knowledge_base": "demo-kb",
        "raw_input": "",
        "history": [],
        "auto_submit": False,
        "max_iterations": 8,
        "iteration": 0,
        "intent": "",  # 未分类；supervisor 首次进入时 classify_intent 写入
        "next_action": "supervisor",
        "plan": [],
        "rag_result": {},
        "retrieve_hits": [],
        "conflict_bundle": None,
        "critic_report": None,
        "parts_check": None,
        "work_order_draft": None,
        "work_order_submit": None,
        "parts_force_hints": [],
        "hitl": {
            "required": False,
            "prompt": "",
            "reasons": [],
            "decision": None,
            "note": "",
            "resolved": False,
        },
        "submit_eligible": False,
        "status": "running",
        "final_summary": "",
        "error": "",
        "trace_events": [],
        "engine": "langgraph",
        "service_ticket": {},
        "station_context": default_station_context(),
        "sla_flags": {},
        "rag_linkage": [],
        "rag_linkage_detail": {},
        "api_key_fp": "",
        "rag_degraded": False,
        "rag_offline_mode": False,
        "engine_degraded": False,
        "engine_degraded_reason": "",
        "execution_path": "langgraph",
        "work_order_state": "intake",
        "feedback_ref": None,
        "role_path": {},
        "route_history": [],
        "station_override": "",
        "second_visit_override": None,
        "sla_class_override": "",
    }
    base.update(kwargs)  # type: ignore[typeddict-item]
    return base
