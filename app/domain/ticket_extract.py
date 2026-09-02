from __future__ import annotations

import re
import time
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
from app.domain.station import (
    default_station_context,
    load_station_profile,
    recommend_crew,
    resolve_jobsite,
    resolve_station_name,
)


def _outdoor_weather_risk(question: str, profile: dict[str, Any]) -> bool:
    """雨季/户外关键词触发防护人确层（非气象 API）。"""
    q = question or ""
    tokens = profile.get("outdoor_weather_tokens") or (
        "户外",
        "雨天",
        "雨季",
        "现场淋雨",
        "露天",
        "淋雨作业",
    )
    return any(str(t) in q for t in tokens if t)


def extract_service_ticket(
    question: str,
    *,
    station_override: str | None = None,
    second_visit_override: bool | None = None,
    sla_class_override: str | None = None,
    reporter_role: str | None = None,
) -> dict[str, Any]:
    """规则抽取报修作业单字段（不调用 LLM）。

    SLA：关键词触发 + intake/deadline 时间戳（演示级截止点，非实时计时服务）。
    """
    q = question or ""
    profile = load_station_profile()
    codes = [c.upper() for c in FAULT_CODE_RE.findall(q)]
    models = [m.upper() for m in MODEL_RE.findall(q)]
    jobsite = resolve_jobsite(q)
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
    outdoor_weather_risk = _outdoor_weather_risk(q, profile)
    intake_ts = time.time()
    sla_deadline_ts = intake_ts + hours * 3600.0

    # 站务档案（演示结构）：班组技能匹配 + 覆盖半径 — 非经销商 CRM / 非 ERP 派工
    coverage_km = profile.get("coverage_radius_km")
    crew_info = recommend_crew(
        station=station,
        fault_codes=codes,
        question=q,
        profile=profile,
    )

    return {
        "machine_model": models[0] if models else "",
        "fault_codes": codes,
        "station": station or "",
        "station_known": bool(station),
        "jobsite": jobsite or "",
        "dispatch_status": "not_in_scope",
        "scope": "work_order_copilot",
        "scope_note": "报修开单门禁；不含 ERP 技师派工/排程",
        "second_visit": second_visit,
        "sla_class": sla_class,
        "response_hours": hours,
        "intake_ts": intake_ts,
        "sla_deadline_ts": sla_deadline_ts,
        "sla_clock_note": "演示截止戳=intake+response_hours；非实时 SLA 计时服务",
        "warranty_claim": warranty_claim,
        "urgent": urgent,
        "outdoor_weather_risk": outdoor_weather_risk,
        "raw_excerpt": q[:120],
        "reporter_role": reporter_role or "",
        "recommended_crew": crew_info.get("recommended_crew") or "",
        "crew_id": crew_info.get("crew_id") or "",
        "crew_match": crew_info.get("crew_match") or "none",
        "crew_skills": list(crew_info.get("crew_skills") or []),
        "coverage_radius_km": coverage_km,
        "station_ops_source": "station_profile.json_demo",
        "station_ops_note": "班组建议=演示规则匹配，非排班系统",
    }


def build_sla_flags(ticket: dict[str, Any], hitl: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.policy.hitl_layers import LAYER_SLA, layer_confirmed

    hitl = hitl or {}
    sla_ok = layer_confirmed(hitl, LAYER_SLA)
    now = time.time()
    deadline = ticket.get("sla_deadline_ts")
    overdue = False
    if isinstance(deadline, (int, float)) and deadline > 0:
        overdue = now > float(deadline) and bool(ticket.get("urgent") or ticket.get("second_visit"))
    return {
        "second_visit": bool(ticket.get("second_visit")),
        "second_visit_confirmed": sla_ok if ticket.get("second_visit") else True,
        "sla_class": ticket.get("sla_class") or "normal",
        "response_hours": ticket.get("response_hours"),
        "intake_ts": ticket.get("intake_ts"),
        "sla_deadline_ts": deadline,
        "sla_overdue_demo": overdue,
        "sla_window_ack": sla_ok if ticket.get("urgent") else True,
        "needs_chief_for_sla": bool(ticket.get("second_visit") or ticket.get("urgent")),
        "sla_model": "keyword_trigger_plus_deadline_stamp",
    }


def enrich_station_context(ticket: dict[str, Any] | None = None) -> dict[str, Any]:
    ctx = default_station_context()
    if ticket and ticket.get("station"):
        ctx["active_station"] = ticket["station"]
    else:
        ctx["active_station"] = None
        ctx["station_unknown"] = True
    if ticket and ticket.get("jobsite"):
        ctx["active_jobsite"] = ticket["jobsite"]
    if ticket and ticket.get("recommended_crew"):
        ctx["recommended_crew"] = ticket["recommended_crew"]
    if ticket and ticket.get("coverage_radius_km") is not None:
        ctx["coverage_radius_km"] = ticket["coverage_radius_km"]
    return ctx
