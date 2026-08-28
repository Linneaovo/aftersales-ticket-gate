from __future__ import annotations

import re
from typing import Any

from app.domain.intent_rules import (
    ACTION_TOKENS,
    FAULT_CODE_RE,
    FAULT_SYMPTOM_TOKENS,
    MODEL_RE,
    SECOND_VISIT_TOKENS,
    URGENT_TOKENS,
    WARRANTY_TOKENS,
)
from app.domain.station import default_station_context, load_station_profile, resolve_station_name


def extract_service_ticket(
    question: str,
    *,
    station_override: str | None = None,
    second_visit_override: bool | None = None,
    sla_class_override: str | None = None,
    reporter_role: str | None = None,
) -> dict[str, Any]:
    """规则抽取报修作业单字段（不调用 LLM）。"""
    q = question or ""
    profile = load_station_profile()
    codes = [c.upper() for c in FAULT_CODE_RE.findall(q)]
    models = [m.upper() for m in MODEL_RE.findall(q)]
    station = station_override
    if not station:
        station = resolve_station_name(q)

    second_visit = (
        bool(second_visit_override)
        if second_visit_override is not None
        else any(t in q for t in SECOND_VISIT_TOKENS)
    )
    compact = re.sub(r"\s+", "", q)
    has_action = any(t in compact for t in ACTION_TOKENS)
    has_symptom = any(t in q for t in FAULT_SYMPTOM_TOKENS)
    has_dispatch_context = bool(codes) or any(t in compact for t in ACTION_TOKENS) or bool(models) or has_symptom
    urgent = (
        sla_class_override == "urgent"
        or (has_dispatch_context and any(t in q for t in URGENT_TOKENS))
    )
    sla_class = sla_class_override or ("urgent" if urgent else "normal")
    hours = (
        int(profile.get("urgent_response_hours") or 4)
        if sla_class == "urgent"
        else int(profile.get("normal_response_hours") or 24)
    )
    warranty_claim = any(t in q for t in WARRANTY_TOKENS)

    return {
        "machine_model": models[0] if models else "",
        "fault_codes": codes,
        "station": station or "",
        "station_known": bool(station),
        "dispatch_status": "not_in_scope",
        "second_visit": second_visit,
        "sla_class": sla_class,
        "response_hours": hours,
        "warranty_claim": warranty_claim,
        "urgent": urgent,
        "raw_excerpt": q[:120],
        "reporter_role": reporter_role or "",
    }


def build_sla_flags(ticket: dict[str, Any], hitl: dict[str, Any] | None = None) -> dict[str, Any]:
    hitl = hitl or {}
    approved = bool(hitl.get("resolved") and hitl.get("decision") == "approve")
    return {
        "second_visit": bool(ticket.get("second_visit")),
        "second_visit_confirmed": approved if ticket.get("second_visit") else True,
        "sla_class": ticket.get("sla_class") or "normal",
        "response_hours": ticket.get("response_hours"),
        "sla_window_ack": approved if ticket.get("urgent") else True,
        "needs_chief_for_sla": bool(ticket.get("second_visit") or ticket.get("urgent")),
    }


def enrich_station_context(ticket: dict[str, Any] | None = None) -> dict[str, Any]:
    ctx = default_station_context()
    if ticket and ticket.get("station"):
        ctx["active_station"] = ticket["station"]
    else:
        ctx["active_station"] = None
        ctx["station_unknown"] = True
    return ctx
