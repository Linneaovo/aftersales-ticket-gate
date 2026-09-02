"""Decision Snapshot（schema 字段名仍为 decision_certificate 以兼容旧客户端）。

运行态可追溯快照，非签名审计中台；与 RAG citations 互补。
"""

from __future__ import annotations

from typing import Any

from app.policy.rules_catalog import POLICY_CATALOG_VERSION, extract_policy_ids

REQUIRED_CERTIFICATE_FIELDS: tuple[str, ...] = (
    "schema",
    "assurance",
    "policy_catalog_version",
    "phase",
    "run_id",
    "status",
    "intent",
    "role",
    "policy_ids",
    "is_production_ticket",
    "not_erp_dispatch",
)


def validate_certificate(cert: dict[str, Any] | None) -> list[str]:
    """必选字段 + 口径锁；返回错误列表（空=通过）。"""
    errors: list[str] = []
    if not isinstance(cert, dict) or not cert:
        return ["certificate missing or not object"]
    for field in REQUIRED_CERTIFICATE_FIELDS:
        if field not in cert:
            errors.append(f"missing:{field}")
    if cert.get("schema") != "decision_certificate/v1":
        errors.append(f"schema={cert.get('schema')!r}")
    if cert.get("assurance") != "state_snapshot_not_tamper_proof":
        errors.append("assurance must be state_snapshot_not_tamper_proof")
    if cert.get("is_production_ticket") is not False:
        errors.append("is_production_ticket must be false")
    if cert.get("not_erp_dispatch") is not True:
        errors.append("not_erp_dispatch must be true")
    if cert.get("policy_catalog_version") != POLICY_CATALOG_VERSION:
        errors.append(
            f"policy_catalog_version={cert.get('policy_catalog_version')!r} "
            f"!= {POLICY_CATALOG_VERSION!r}"
        )
    return errors


def _citation_refs(rag_result: dict[str, Any] | None, *, limit: int = 8) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for src in (rag_result or {}).get("sources") or []:
        if not isinstance(src, dict):
            continue
        chunk = src.get("chunk") if isinstance(src.get("chunk"), dict) else {}
        refs.append(
            {
                "source": chunk.get("source") or src.get("source"),
                "score": src.get("score"),
                "doc_id": chunk.get("doc_id") or src.get("doc_id"),
            }
        )
        if len(refs) >= limit:
            break
    return refs


def _parts_summary(parts: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(parts, dict):
        return None
    return {
        "shortage": bool(parts.get("shortage")),
        "shortage_items": list(parts.get("shortage_items") or [])[:8],
        "ledger_degraded": bool(parts.get("ledger_degraded")),
        "unknown_parts": bool(parts.get("unknown_parts")),
        "suggested_action": parts.get("suggested_action"),
        "hints_source": parts.get("hints_source"),
    }


def build_decision_certificate(state: dict[str, Any], *, phase: str | None = None) -> dict[str, Any]:
    """从 CopilotState 生成 Decision Snapshot（兼容名 certificate）。

    phase:
      - pending: 进入 waiting_hitl
      - resolved: 站长已决策（approve/reject/return；edit 为历史别名）
      - auto: 无 HITL 直接结束（少见）
    """
    hitl = dict(state.get("hitl") or {})
    critic = dict(state.get("critic_report") or {})
    submit = state.get("work_order_submit") if isinstance(state.get("work_order_submit"), dict) else {}
    status = str(state.get("status") or "")

    if phase is None:
        if hitl.get("resolved"):
            phase = "resolved"
        elif status == "waiting_hitl" or hitl.get("required"):
            phase = "pending"
        else:
            phase = "auto"

    reason_text = " ".join(str(r) for r in (hitl.get("reasons") or []))
    policy_ids = extract_policy_ids(reason_text)
    for pid in critic.get("policy_ids") or []:
        if pid not in policy_ids:
            policy_ids.append(str(pid))

    return {
        "schema": "decision_certificate/v1",
        "kind": "decision_snapshot",
        "display_name": "Decision Snapshot",
        "assurance": "state_snapshot_not_tamper_proof",
        "assurance_note": "运行态快照，非签名审计中台；仅用于演示可追溯",
        "policy_catalog_version": POLICY_CATALOG_VERSION,
        "phase": phase,
        "run_id": state.get("run_id"),
        "status": status,
        "intent": state.get("intent"),
        "intent_label": "报修开单" if state.get("intent") == "fault_dispatch" else state.get("intent"),
        "intent_confidence": state.get("intent_confidence"),
        "intent_signals": list(state.get("intent_signals") or []),
        "role": state.get("role"),
        "approver_key_role": hitl.get("approver_key_role"),
        "policy_ids": policy_ids,
        "hitl_reasons": list(hitl.get("reasons") or []),
        "pending_layers": list(hitl.get("pending_layers") or []),
        "confirmations": dict(hitl.get("confirmations") or {}),
        "hitl_decision": hitl.get("decision"),
        "hitl_note": hitl.get("note") or "",
        "conflict_present": bool((state.get("conflict_bundle") or {}).get("present")),
        "citation_refs": _citation_refs(
            state.get("rag_result") if isinstance(state.get("rag_result"), dict) else {}
        ),
        "parts": _parts_summary(
            state.get("parts_check") if isinstance(state.get("parts_check"), dict) else None
        ),
        "station_ops": {
            "station": (state.get("service_ticket") or {}).get("station"),
            "jobsite": (state.get("service_ticket") or {}).get("jobsite"),
            "recommended_crew": (state.get("service_ticket") or {}).get("recommended_crew"),
            "crew_match": (state.get("service_ticket") or {}).get("crew_match"),
            "coverage_radius_km": (state.get("service_ticket") or {}).get("coverage_radius_km"),
            "source": (state.get("service_ticket") or {}).get("station_ops_source"),
            "note": "演示站务字段，非 CRM/排班",
        },
        "rag_client_mode": "demo_offline" if state.get("rag_offline_mode") else "live",
        "rag_degraded": bool(state.get("rag_degraded")),
        "destination": submit.get("destination")
        or ("rag_mock_inbox" if status == "succeeded" and submit else None),
        "is_production_ticket": False,
        "not_erp_dispatch": True,
        "ticket_id": submit.get("ticket_id"),
        "parent_run_id": state.get("parent_run_id"),
    }


def build_decision_snapshot(state: dict[str, Any], *, phase: str | None = None) -> dict[str, Any]:
    """推荐对外名；实现同 build_decision_certificate。"""
    return build_decision_certificate(state, phase=phase)
