from __future__ import annotations

import re
from typing import Any

from app.graph.state import CriticReport
from app.policy.rules_catalog import tag

SINGLE_VERDICT_RE = re.compile(
    r"(以.{0,8}为准|应采用|最终结论是|废除旧版|旧版作废|请按新版执行且忽略旧版|建议以新版为准|应以修订稿为准)"
)
RETRIEVE_ONLY_MARKERS = ("仅检索", "检索摘要", "ollama 不可用", "生成降级", "retrieve_only")


def detect_rag_degraded(rag: dict[str, Any]) -> bool:
    answer = str(rag.get("answer") or "")
    debug = rag.get("debug") or {}
    if rag.get("retrieve_only") or debug.get("retrieve_only"):
        return True
    return any(m in answer for m in RETRIEVE_ONLY_MARKERS)


def run_quality_checks(state: dict[str, Any]) -> CriticReport:
    """质检：规则为主，消费 RAG 字段；reasons 带策略 ID。"""
    reasons: list[str] = []
    policy_ids: list[str] = []
    risk: str = "low"
    force_hitl = False

    rag = state.get("rag_result") or {}
    answer = str(rag.get("answer") or "")
    blocked = bool(rag.get("blocked"))
    block_reason = rag.get("block_reason")
    grounded = rag.get("grounded")
    grounding_score = float(rag.get("grounding_score") or 0.0)
    conflicts = list(rag.get("conflicts") or [])
    sources = list(rag.get("sources") or [])
    intent = state.get("intent")
    draft = state.get("work_order_draft")

    if detect_rag_degraded(rag) or state.get("rag_degraded"):
        force_hitl = True
        risk = "high"
        reasons.append(tag("POL-DEGRADE-01"))
        policy_ids.append("POL-DEGRADE-01")

    if blocked or block_reason in {"acl_denied", "chitchat", "prompt_injection"}:
        reasons.append(tag("POL-GROUND-02", str(block_reason or "blocked")))
        policy_ids.append("POL-GROUND-02")
        risk = "high"

    conflict_present = bool(
        conflicts
        or (state.get("conflict_bundle") or {}).get("present")
        or intent == "conflict_review"
    )
    # 冲突题：依据不足仍须站长人确（软门禁），不可硬拒抢走 HITL
    soft_ground_on_conflict = conflict_present

    if intent in {"fault_dispatch", "knowledge_only", "conflict_review"}:
        if not blocked and grounded is False and grounding_score < 0.35:
            reasons.append(tag("POL-GROUND-01", f"grounding_score={grounding_score:.2f}"))
            policy_ids.append("POL-GROUND-01")
            risk = "high"
            if soft_ground_on_conflict:
                force_hitl = True
        if not blocked and not sources and intent != "chitchat":
            reasons.append(tag("POL-GROUND-01", "无引用片段"))
            policy_ids.append("POL-GROUND-01")
            risk = "high"
            if soft_ground_on_conflict:
                force_hitl = True

    if conflict_present:
        force_hitl = True
        risk = "high"
        policy_ids.append("POL-CONFLICT-01")
        reasons.append(tag("POL-CONFLICT-01"))
        if answer and SINGLE_VERDICT_RE.search(answer):
            reasons.append(tag("POL-CONFLICT-02"))
            policy_ids.append("POL-CONFLICT-02")

    if draft is not None:
        fault_codes = draft.get("fault_codes") or []
        if isinstance(draft.get("draft"), dict):
            inner = draft["draft"]
            fault_codes = fault_codes or inner.get("fault_codes") or []
        if intent == "fault_dispatch" and not fault_codes:
            fill = draft.get("fill_fields") or (draft.get("draft") or {}).get("fill_fields") or []
            has_code = any(
                (f.get("field") == "fault_codes" and f.get("value")) for f in fill if isinstance(f, dict)
            )
            ticket_codes = (state.get("service_ticket") or {}).get("fault_codes") or []
            if not has_code and not fault_codes and not ticket_codes:
                reasons.append(tag("POL-DRAFT-02"))
                policy_ids.append("POL-DRAFT-02")
                risk = "medium"

    if draft is not None and intent == "knowledge_only":
        reasons.append(tag("POL-DRAFT-01"))
        policy_ids.append("POL-DRAFT-01")
        risk = "medium"

    parts = state.get("parts_check") or {}
    if parts.get("shortage"):
        force_hitl = True
        if risk == "low":
            risk = "medium"
        policy_ids.append("POL-PARTS-01")

    # POL-CONFLICT-02 / 冲突题 POL-GROUND-01：仅 force_hitl，不作硬拒
    hard = [
        x
        for x in reasons
        if ("POL-GROUND-02" in x or "POL-DRAFT" in x)
        or ("POL-GROUND-01" in x and not soft_ground_on_conflict)
    ]
    # 兼容旧字符串（不含 POL-CONFLICT-02：其标签含「单方裁决」但仅 force_hitl）
    hard += [
        x
        for x in reasons
        if x.startswith("纯查询")
        or x.startswith("工单缺")
        or x.startswith("检索侧已拦截")
        or (
            not soft_ground_on_conflict
            and (x.startswith("依据不足") or x.startswith("无引用"))
        )
    ]
    passed = len(hard) == 0

    return CriticReport(
        passed=passed,
        reasons=reasons,
        risk_level=risk if reasons else "low",  # type: ignore[typeddict-item]
        force_hitl=force_hitl,
        policy_ids=list(dict.fromkeys(policy_ids)),
    )
