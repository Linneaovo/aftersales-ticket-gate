from __future__ import annotations

import time
from typing import Any, Callable

from app.config import get_settings
from app.domain.station import load_station_profile
from app.domain.ticket_extract import MODEL_RE, build_sla_flags, enrich_station_context, extract_service_ticket
from app.logging_config import get_logger, log_node_event
from app.graph.state import (
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
    CopilotState,
    copy_state,
)
from app.graph.trace_labels import TRACE_WORKERS
from app.policy.gates import can_create_draft, evaluate_submit_eligible
from app.policy.role_graph import expected_path_for_role
from app.policy.rules_catalog import tag
from app.quality.rules import detect_rag_degraded, run_quality_checks
from app.tools.context import get_rag_client
from app.tools.parts_ledger import check_parts, hints_from_rag_and_draft
from app.tools.rag_client import RagClient, RagToolError
from app.tools.rag_normalize import normalize_rag_result

_logger = get_logger("nodes")


def _append_trace(state: CopilotState, agent: str, node: str, **payload: Any) -> None:
    worker = TRACE_WORKERS.get(node, agent)
    events = list(state.get("trace_events") or [])
    events.append(
        {
            "ts": time.time(),
            "run_id": state.get("run_id"),
            "iteration": state.get("iteration", 0),
            "agent": worker,
            "node": node,
            "worker_type": "rule" if node in {"supervisor", "quality", "quality_draft", "parts", "hitl"} else "http",
            "submit_eligible_snapshot": state.get("submit_eligible"),
            **payload,
        }
    )
    state["trace_events"] = events
    log_node_event(
        _logger,
        run_id=str(state.get("run_id") or ""),
        node=node,
        ok=payload.get("ok"),
        latency_ms=payload.get("latency_ms"),
        agent=agent,
        tool=payload.get("tool"),
        policy_ids=payload.get("policy_ids"),
    )


def _link(state: CopilotState, api_name: str, *, meta: dict[str, Any] | None = None) -> None:
    links = list(state.get("rag_linkage") or [])
    if api_name not in links:
        links.append(api_name)
    state["rag_linkage"] = links
    if meta:
        detail = dict(state.get("rag_linkage_detail") or {})
        detail[api_name] = meta
        state["rag_linkage_detail"] = detail  # type: ignore[typeddict-item]


def re_sub_ws(text: str) -> str:
    import re

    return re.sub(r"\s+", "", text or "")


def classify_intent(question: str) -> str:
    q = (question or "").strip()
    compact = re_sub_ws(q)
    lower = q.lower()
    if any(t in q for t in INJECTION_TOKENS) or any(t in lower for t in INJECTION_TOKENS):
        return "injection"
    if any(t in q for t in CHAT_TOKENS):
        return "chitchat"
    if any(t in q for t in ACL_PROBE_TOKENS):
        return "acl_probe"
    codes = FAULT_CODE_RE.findall(q)
    has_action = any(t in compact for t in ACTION_TOKENS)
    has_weak_action = any(t in q for t in WEAK_ACTION_TOKENS) or any(t in compact for t in WEAK_ACTION_TOKENS)
    has_dispatch = any(t in q for t in DISPATCH_TOKENS)
    has_symptom = any(t in q for t in FAULT_SYMPTOM_TOKENS)
    has_model = bool(MODEL_RE.search(q))
    has_equipment_ctx = has_model or has_symptom or bool(codes) or any(
        t in q for t in ("泵车", "挖机", "起重机", "履带", "转台", "动臂", "大臂", "液压")
    )
    if (codes and (has_action or has_symptom or has_dispatch or has_weak_action)) or (
        has_model and (has_action or has_symptom or has_dispatch or has_weak_action)
    ):
        return "fault_dispatch"
    if has_action and has_symptom:
        return "fault_dispatch"
    if has_symptom and (has_weak_action or has_dispatch or "你们" in q or "帮忙" in q):
        return "fault_dispatch"
    if has_dispatch and has_equipment_ctx:
        return "fault_dispatch"
    if "师傅" in q and any(t in compact for t in ("过来", "上门", "一趟", "看看")):
        return "fault_dispatch"
    if has_equipment_ctx and any(t in q for t in ("有问题", "出问题了")) and (
        has_weak_action or "你们" in q or "帮忙" in q
    ):
        return "fault_dispatch"
    if any(t in q for t in KNOWLEDGE_QUERY_TOKENS) and not any(
        t in q for t in ("哪个为准", "不一致", "冲突", "新旧制度")
    ):
        return "knowledge_only"
    if any(t in q for t in CONFLICT_TOKENS):
        return "conflict_review"
    return "knowledge_only"


def _record_route(state: CopilotState, action: str) -> None:
    if action in {"supervisor", "end"}:
        return
    history = list(state.get("route_history") or [])
    history.append(str(action))
    state["route_history"] = history[-16:]  # type: ignore[typeddict-item]


def _detect_route_cycle(state: CopilotState, action: str) -> bool:
    """同一 worker（非 supervisor）无状态推进时连续出现 ≥3 次视为空转。"""
    if action in {"supervisor", "end", "hitl"}:
        return False
    history = [h for h in (state.get("route_history") or []) if h not in {"supervisor", "end", "hitl"}]
    if len(history) < 2:
        return False
    tail = history[-2:] + [action]
    if len(set(tail)) == 1:
        return True
    return False


def _ensure_ticket(state: CopilotState) -> CopilotState:
    ticket = extract_service_ticket(
        str(state.get("raw_input") or ""),
        station_override=state.get("station_override") or None,
        second_visit_override=state.get("second_visit_override"),
        sla_class_override=state.get("sla_class_override") or None,
        reporter_role=str(state.get("role") or "technician"),
    )
    state["service_ticket"] = ticket  # type: ignore[typeddict-item]
    state["station_context"] = enrich_station_context(ticket)
    state["sla_flags"] = build_sla_flags(ticket, state.get("hitl"))
    return state


def _policy_ids_from_reasons(reasons: list[str]) -> list[str]:
    import re

    ids: list[str] = []
    for r in reasons:
        for m in re.findall(r"POL-[A-Z0-9-]+", r):
            if m not in ids:
                ids.append(m)
    return ids


def _apply_draft_quality(state: CopilotState) -> CopilotState:
    """draft 就绪后合并工单字段质检（不再触发第二次 quality 节点）。"""
    report = run_quality_checks(state)
    state["critic_report"] = report
    _append_trace(
        state,
        "规则质检",
        "quality_draft",
        ok=report.get("passed", False),
        tool="rules",
        reasons=report.get("reasons"),
        policy_ids=report.get("policy_ids"),
        force_hitl=report.get("force_hitl"),
        routing_reason="draft 字段复检（单次质检路径）",
    )
    return state


def _hitl_prompt_extras(ticket: dict[str, Any], raw_input: str) -> str:
    extras = ""
    profile = load_station_profile()
    rainy = profile.get("rainy_season_note") or ""
    outdoor_markers = ("户外", "雨天", "雨季", "现场淋雨")
    if rainy and (ticket.get("urgent") or any(m in (raw_input or "") for m in outdoor_markers)):
        extras += " 雨季提醒：" + rainy
    return extras


def _route_after_rag(
    state: CopilotState,
    *,
    intent: str,
    rag: dict[str, Any],
    critic: dict[str, Any] | None,
    draft: dict[str, Any] | None,
    parts: dict[str, Any] | None,
) -> CopilotState | None:
    """RAG 返回后决定下一 worker；返回 None 表示继续 HITL/提交评估。"""
    if not rag:
        state["next_action"] = "rag"
        state["plan"] = list(state.get("plan") or []) + ["rag"]
        _append_trace(
            state,
            "supervisor",
            "supervisor",
            ok=True,
            intent=intent,
            next="rag",
            routing_reason="rag_result 为空，先检索",
            service_ticket=state.get("service_ticket") or {},
        )
        return state

    if critic is None:
        state["next_action"] = "quality"
        _append_trace(state, "supervisor", "supervisor", ok=True, intent=intent, next="quality", routing_reason="RAG 已返回，进入质检")
        return state

    if not critic.get("passed"):
        state["status"] = "rejected"
        state["final_summary"] = "质检未通过：" + "; ".join(critic.get("reasons") or [])
        state["next_action"] = "end"
        _append_trace(state, "supervisor", "supervisor", ok=False, next="end", reasons=critic.get("reasons"))
        return state

    if intent == "fault_dispatch" and draft is None:
        if not can_create_draft(str(state.get("role") or "")):
            state["status"] = "rejected"
            state["final_summary"] = tag("POL-ROLE-02")
            state["next_action"] = "end"
            return state
        state["next_action"] = "work_order"
        _append_trace(state, "supervisor", "supervisor", ok=True, next="work_order", routing_reason="fault_dispatch 需出草稿")
        return state

    if intent == "fault_dispatch" and draft is not None and parts is None:
        state["next_action"] = "parts"
        _append_trace(state, "supervisor", "supervisor", ok=True, next="parts", routing_reason="草稿已有，配件预核")
        return state

    return None


def _evaluate_hitl_gates(
    state: CopilotState,
    *,
    intent: str,
    critic: dict[str, Any],
    parts: dict[str, Any] | None,
    conflict: dict[str, Any],
    ticket: dict[str, Any],
    hitl: dict[str, Any],
    settings: Any,
) -> tuple[bool, list[str]]:
    """评估是否须站长人确及原因列表。"""
    draft = state.get("work_order_draft")
    ready = intent != "fault_dispatch" or (draft is not None and parts is not None)
    need_hitl = False
    reasons = list(hitl.get("reasons") or [])

    if not ready:
        return need_hitl, reasons

    if settings.hitl_required_on_conflict and (
        conflict.get("present") or intent == "conflict_review" or conflict.get("requires_chief")
    ):
        need_hitl = True
        if "POL-CONFLICT-01" not in "".join(reasons):
            reasons.append(tag("POL-CONFLICT-01"))
    if critic.get("force_hitl"):
        need_hitl = True
    if parts and parts.get("shortage"):
        need_hitl = True
        if "POL-PARTS-01" not in "".join(reasons):
            reasons.append(tag("POL-PARTS-01", str(parts.get("suggested_action") or parts.get("note") or "")))
    if ticket.get("second_visit"):
        need_hitl = True
        if "POL-SLA-01" not in "".join(reasons):
            reasons.append(tag("POL-SLA-01"))
    if ticket.get("urgent"):
        need_hitl = True
        if "POL-SLA-02" not in "".join(reasons):
            reasons.append(tag("POL-SLA-02", f"首响{ticket.get('response_hours')}小时内"))
    if state.get("rag_degraded"):
        need_hitl = True
        state["auto_submit"] = False
        if "POL-DEGRADE-01" not in "".join(reasons):
            reasons.append(tag("POL-DEGRADE-01"))
    if intent == "fault_dispatch" and not (ticket.get("station") or "").strip():
        need_hitl = True
        if "POL-STATION-01" not in "".join(reasons):
            reasons.append(tag("POL-STATION-01"))

    return need_hitl, reasons


def _route_submit(state: CopilotState, *, intent: str, draft: dict[str, Any] | None) -> CopilotState:
    """fault_dispatch 完成后决定 submit 或结束。"""
    if intent == "fault_dispatch" and draft is not None:
        eligible, blockers = evaluate_submit_eligible(state)
        state["submit_eligible"] = eligible
        hitl = state.get("hitl") or {}
        chief_approved = bool(hitl.get("resolved") and hitl.get("decision") == "approve")
        may_auto_submit = (
            state.get("auto_submit")
            and eligible
            and not state.get("rag_degraded")
            and not state.get("work_order_submit")
        )
        may_chief_submit = chief_approved and eligible and not state.get("work_order_submit")
        if may_auto_submit or may_chief_submit:
            state["next_action"] = "submit"
            routing_reason = (
                "站长人确后门禁通过，submit"
                if may_chief_submit and not may_auto_submit
                else "门禁通过且 auto_submit"
            )
            _append_trace(
                state,
                "supervisor",
                "supervisor",
                ok=True,
                next="submit",
                routing_reason=routing_reason,
            )
            return state
        state["status"] = "succeeded"
        state["final_summary"] = _summarize(state, blockers)
        state["next_action"] = "end"
        is_chief = state.get("role") == "station_chief"
        chief_note = ""
        if is_chief:
            chief_note = "；站长已免除 POL-ROLE-01（缺料/冲突/SLA 仍须人确，非一键提交）"
        _append_trace(
            state,
            "supervisor",
            "supervisor",
            ok=True,
            next="end",
            blockers=blockers,
            routing_reason="fault_dispatch 完成" + chief_note,
            chief_role_exempts_pol_role_01=is_chief,
        )
        return state

    state["status"] = "succeeded"
    state["final_summary"] = _summarize(state, [])
    state["next_action"] = "end"
    _append_trace(state, "supervisor", "supervisor", ok=True, next="end")
    return state


def supervisor_node(state: CopilotState) -> CopilotState:
    state = copy_state(state)
    state["iteration"] = int(state.get("iteration") or 0) + 1
    pending_action = str(state.get("next_action") or "supervisor")
    if pending_action not in {"supervisor", "end", "hitl"} and _detect_route_cycle(state, pending_action):
        state["status"] = "failed"
        state["error"] = "路由空转：同一 worker 重复触发且无状态推进"
        state["next_action"] = "end"
        _append_trace(state, "supervisor", "supervisor", ok=False, error=state["error"], routing_reason="cycle_detected")
        return state  # type: ignore[return-value]
    _record_route(state, pending_action)
    if state["iteration"] > int(state.get("max_iterations") or 8):
        state["status"] = "failed"
        state["error"] = "超过最大迭代轮次"
        state["next_action"] = "end"
        _append_trace(state, "supervisor", "supervisor", ok=False, error=state["error"])
        return state  # type: ignore[return-value]

    if state.get("status") == "waiting_hitl":
        hitl = state.get("hitl") or {}
        if hitl.get("resolved"):
            state["status"] = "running"
        else:
            state["next_action"] = "end"
            return state  # type: ignore[return-value]

    if state.get("work_order_submit") and state.get("status") == "running":
        state["status"] = "succeeded"
        state["final_summary"] = _summarize(state, [])
        state["next_action"] = "end"
        _append_trace(state, "supervisor", "supervisor", ok=True, next="end", note="already_submitted")
        return state  # type: ignore[return-value]

    # 1.2 进 RAG 前抽取作业单
    state = _ensure_ticket(state)
    intent = str(state.get("intent") or "").strip()
    if not intent:
        intent = classify_intent(str(state.get("raw_input") or ""))
        state["intent"] = intent  # type: ignore[typeddict-item]
    state["role_path"] = expected_path_for_role(str(state.get("role") or "technician"), intent)

    if intent in {"chitchat", "injection"}:
        state["status"] = "rejected"
        state["final_summary"] = tag("POL-CHAT-01")
        state["next_action"] = "end"
        _append_trace(state, "supervisor", "supervisor", ok=True, intent=intent, next="end", policy="POL-CHAT-01")
        return state  # type: ignore[return-value]

    if intent == "acl_probe":
        state["status"] = "rejected"
        state["final_summary"] = tag("POL-ACL-01")
        state["next_action"] = "end"
        _append_trace(state, "supervisor", "supervisor", ok=True, intent=intent, next="end", policy="POL-ACL-01")
        return state  # type: ignore[return-value]

    rag = state.get("rag_result") or {}
    critic = state.get("critic_report")
    draft = state.get("work_order_draft")
    hitl = dict(state.get("hitl") or {})
    parts = state.get("parts_check")
    settings = get_settings()
    ticket = state.get("service_ticket") or {}

    if hitl.get("resolved") and hitl.get("decision") == "reject":
        state["status"] = "rejected"
        state["submit_eligible"] = False
        state["final_summary"] = tag("POL-HITL-REJECT", str(hitl.get("note") or ""))
        state["next_action"] = "end"
        _append_trace(state, "supervisor", "supervisor", ok=True, next="end")
        return state  # type: ignore[return-value]

    if hitl.get("resolved") and hitl.get("decision") == "edit":
        state["status"] = "succeeded"
        state["submit_eligible"] = False
        note = str(hitl.get("note") or "").strip()
        if not note:
            note = "（未填写改单说明）"
        state["final_summary"] = tag("POL-HITL-EDIT", note)
        state["next_action"] = "end"
        _append_trace(state, "supervisor", "supervisor", ok=True, next="end", edit_note=note)
        return state  # type: ignore[return-value]

    routed = _route_after_rag(
        state,
        intent=intent,
        rag=rag,
        critic=critic,
        draft=draft,
        parts=parts,
    )
    if routed is not None:
        return routed  # type: ignore[return-value]

    conflict = state.get("conflict_bundle") or {}
    need_hitl, reasons = _evaluate_hitl_gates(
        state,
        intent=intent,
        critic=critic or {},
        parts=parts,
        conflict=conflict,
        ticket=ticket,
        hitl=hitl,
        settings=settings,
    )

    if need_hitl and not hitl.get("resolved"):
        prompt = "请站长确认：冲突并列不作裁决；缺料走经开调拨/改约；二次进站/紧急须确认后开单。（须站长角色 API Key）"
        prompt += _hitl_prompt_extras(ticket, str(state.get("raw_input") or ""))
        if parts and parts.get("shortage"):
            prompt += " " + str(parts.get("suggested_action") or parts.get("note") or "")
        hitl.update(
            {
                "required": True,
                "prompt": prompt,
                "reasons": reasons,
                "resolved": False,
            }
        )
        state["hitl"] = hitl  # type: ignore[typeddict-item]
        state["sla_flags"] = build_sla_flags(ticket, hitl)
        state["status"] = "waiting_hitl"
        state["next_action"] = "hitl"
        state["submit_eligible"] = False
        _append_trace(
            state,
            "supervisor",
            "supervisor",
            ok=True,
            next="hitl",
            reasons=reasons,
            routing_reason="触发 HITL 门禁",
            policy_ids=_policy_ids_from_reasons(reasons),
        )
        return state  # type: ignore[return-value]

    state["sla_flags"] = build_sla_flags(ticket, hitl)
    return _route_submit(state, intent=intent, draft=draft)  # type: ignore[return-value]


def _summarize(state: CopilotState, blockers: list[str]) -> str:
    rag = state.get("rag_result") or {}
    ticket = state.get("service_ticket") or {}
    answer = str(rag.get("answer") or "")[:200]
    parts = [
        f"意图={state.get('intent')}",
        f"站={ticket.get('station') or ''}",
        f"机型={ticket.get('machine_model') or ''}",
        f"码={','.join(ticket.get('fault_codes') or [])}",
    ]
    if (state.get("conflict_bundle") or {}).get("present"):
        parts.append("冲突束(不作裁决)")
    if state.get("work_order_draft"):
        parts.append("已出草稿")
    if blockers:
        parts.append("未提交:" + ";".join(blockers)[:160])
    elif state.get("work_order_submit"):
        tid = (state.get("work_order_submit") or {}).get("ticket_id") or "—"
        dest = (state.get("work_order_submit") or {}).get("destination") or "rag_mock_inbox"
        parts.append(f"已入 {dest}(ticket_id={tid})，非 ERP 工单号")
    elif state.get("work_order_draft") and state.get("role") != "station_chief":
        parts.append("草稿就绪，待站长提交(mock inbox)")
    if answer:
        parts.append("摘要:" + answer)
    return " | ".join(p for p in parts if p and not p.endswith("="))


def rag_node(state: CopilotState, client: RagClient | None = None) -> CopilotState:
    state = copy_state(state)
    client = client or get_rag_client(str(state.get("api_key") or ""))
    t0 = time.time()
    try:
        result = normalize_rag_result(
            client.ask(
                str(state.get("raw_input") or ""),
                knowledge_base=str(state.get("knowledge_base") or "demo-kb"),
                history=list(state.get("history") or []),
                role=str(state.get("role") or "technician"),
            )
        )
        if getattr(client, "offline", False):
            state["rag_offline_mode"] = True  # type: ignore[typeddict-item]
        _link(
            state,
            "ask",
            meta={
                "request_id": result.get("request_id"),
                "grounded": result.get("grounded"),
            },
        )
        if hasattr(client, "retrieve"):
            try:
                retrieved = client.retrieve(
                    str(state.get("raw_input") or ""),
                    knowledge_base=str(state.get("knowledge_base") or "demo-kb"),
                    history=list(state.get("history") or []),
                    role=str(state.get("role") or "technician"),
                )
                _link(state, "retrieve")
                hits = (
                    retrieved.get("results")
                    or retrieved.get("items")
                    or retrieved.get("sources")
                    or []
                )
                if isinstance(hits, list):
                    state["retrieve_hits"] = hits[:10]  # type: ignore[typeddict-item]
            except RagToolError:
                state["retrieve_hits"] = []

        state["rag_result"] = result
        degraded = detect_rag_degraded(result)
        state["rag_degraded"] = bool(degraded)
        if degraded:
            state["auto_submit"] = False

        conflicts = list(result.get("conflicts") or [])
        if conflicts or state.get("intent") == "conflict_review":
            state["conflict_bundle"] = {
                "present": True,
                "items": conflicts,
                "policy": "no_arbitration",
                "reason": "质保/制度口径不一致" if conflicts else "冲突题意图",
                "requires_chief": True,
                "sources_pair": conflicts,
            }
        # ask 已带工单则复用——仅故障开单且角色可 draft；纯查询/冲突题/finance 等忽略
        role = str(state.get("role") or "")
        if (
            result.get("work_order")
            and not state.get("work_order_draft")
            and state.get("intent") == "fault_dispatch"
            and can_create_draft(role)
        ):
            state["work_order_draft"] = {
                "ok": True,
                "draft": result.get("work_order"),
                "source": "rag_ask_inline",
            }
            _link(state, "ask.work_order")
        elif result.get("work_order") and state.get("intent") == "fault_dispatch" and not can_create_draft(role):
            _append_trace(
                state,
                "RAG-HTTP",
                "rag",
                ok=True,
                tool="ask.work_order_skipped",
                routing_reason=tag("POL-ROLE-02"),
                role=role,
            )

        state["critic_report"] = None
        _append_trace(
            state,
            "RAG-HTTP",
            "rag",
            ok=True,
            tool="ask+retrieve",
            latency_ms=int((time.time() - t0) * 1000),
            rag_request_id=result.get("request_id"),
            citations_count=len(result.get("sources") or []),
            blocked=result.get("blocked"),
            grounded=result.get("grounded"),
            grounding_score=result.get("grounding_score"),
            n_conflicts=len(conflicts),
            rag_degraded=degraded,
        )
    except RagToolError as exc:
        partial_hits: list[dict[str, Any]] = []
        if hasattr(client, "retrieve"):
            try:
                retrieved = client.retrieve(
                    str(state.get("raw_input") or ""),
                    knowledge_base=str(state.get("knowledge_base") or "demo-kb"),
                    history=list(state.get("history") or []),
                    role=str(state.get("role") or "technician"),
                )
                _link(state, "retrieve")
                partial_hits = (
                    retrieved.get("results")
                    or retrieved.get("items")
                    or retrieved.get("sources")
                    or []
                )
                if isinstance(partial_hits, list) and partial_hits:
                    state["retrieve_hits"] = partial_hits[:10]  # type: ignore[typeddict-item]
                    state["rag_result"] = {
                        "answer": "",
                        "sources": partial_hits[:10],
                        "grounded": False,
                        "grounding_score": 0.0,
                        "retrieve_only": True,
                        "blocked": False,
                        "conflicts": [],
                        "request_id": None,
                    }
                    state["rag_degraded"] = True
                    state["auto_submit"] = False
                    state["critic_report"] = None
                    state["status"] = "running"
                    state["next_action"] = "supervisor"
                    _append_trace(
                        state,
                        "RAG-HTTP",
                        "rag",
                        ok=True,
                        tool="retrieve_only",
                        partial_degrade=True,
                        ask_error=str(exc),
                        citations_count=len(partial_hits),
                        latency_ms=int((time.time() - t0) * 1000),
                    )
                    return state  # type: ignore[return-value]
            except RagToolError:
                pass
        state["status"] = "failed"
        state["error"] = str(exc)
        state["next_action"] = "end"
        state["rag_degraded"] = True
        _append_trace(
            state,
            "RAG-HTTP",
            "rag",
            ok=False,
            tool="ask",
            error=str(exc),
            status_code=exc.status_code,
            latency_ms=int((time.time() - t0) * 1000),
        )
    return state  # type: ignore[return-value]


def quality_node(state: CopilotState) -> CopilotState:
    state = copy_state(state)
    report = run_quality_checks(state)
    state["critic_report"] = report
    _append_trace(
        state,
        "规则质检",
        "quality",
        ok=report.get("passed", False),
        tool="rules",
        reasons=report.get("reasons"),
        policy_ids=report.get("policy_ids"),
        force_hitl=report.get("force_hitl"),
        risk_level=report.get("risk_level"),
    )
    return state  # type: ignore[return-value]


def work_order_node(state: CopilotState, client: RagClient | None = None) -> CopilotState:
    state = copy_state(state)
    # 优先复用 ask 内联工单
    existing = state.get("work_order_draft")
    if existing and (existing.get("source") == "rag_ask_inline" or existing.get("draft")):
        state = _apply_draft_quality(state)
        _append_trace(state, "开单-HTTP", "work_order", ok=True, tool="reuse_ask_work_order")
        return state  # type: ignore[return-value]

    client = client or get_rag_client(str(state.get("api_key") or ""))
    rag = state.get("rag_result") or {}
    sources = [s for s in (rag.get("sources") or []) if isinstance(s, dict)]
    t0 = time.time()
    try:
        draft = client.draft_work_order(
            str(state.get("raw_input") or ""),
            knowledge_base=str(state.get("knowledge_base") or "demo-kb"),
            answer=str(rag.get("answer") or ""),
            role=str(state.get("role") or "technician"),
            sources=sources,
        )
        _link(state, "work_orders.draft", meta={"source": "draft_api"})
        state["work_order_draft"] = draft
        state = _apply_draft_quality(state)
        _append_trace(
            state,
            "开单-HTTP",
            "work_order",
            ok=True,
            tool="draft",
            latency_ms=int((time.time() - t0) * 1000),
        )
    except RagToolError as exc:
        state["status"] = "failed"
        state["error"] = str(exc)
        state["next_action"] = "end"
        _append_trace(state, "开单-HTTP", "work_order", ok=False, tool="draft", error=str(exc))
    return state  # type: ignore[return-value]


def parts_node(state: CopilotState) -> CopilotState:
    state = copy_state(state)
    hints = list(state.get("parts_force_hints") or [])
    if not hints:
        hints = hints_from_rag_and_draft(state.get("rag_result") or {}, state.get("work_order_draft"))
    from app.domain.parts_master import normalize_part_hints

    canonical_hints, hint_mapping = normalize_part_hints(hints)
    result = check_parts(canonical_hints)
    result["hint_mapping"] = hint_mapping
    result["master_data_authority"] = "parts_ledger.json"
    state["parts_check"] = result  # type: ignore[typeddict-item]
    _append_trace(
        state,
        "配件预核",
        "parts",
        ok=True,
        tool="parts_ledger",
        shortage=result.get("shortage"),
        items=result.get("items"),
        note=result.get("note"),
        hints=canonical_hints,
        hint_mapping=hint_mapping,
        master_data_authority=result.get("master_data_authority"),
    )
    return state  # type: ignore[return-value]


def hitl_node(state: CopilotState) -> CopilotState:
    state = copy_state(state)
    hitl = dict(state.get("hitl") or {})
    if hitl.get("resolved"):
        state["status"] = "running"
        state["next_action"] = "supervisor"
        state["sla_flags"] = build_sla_flags(state.get("service_ticket") or {}, hitl)
        _append_trace(
            state,
            "站长人确",
            "hitl",
            ok=True,
            tool="chief_gate",
            decision=hitl.get("decision"),
            note=hitl.get("note"),
        )
        return state  # type: ignore[return-value]

    if state.get("engine") == "langgraph":
        try:
            from langgraph.types import interrupt

            events = list(state.get("trace_events") or [])
            has_hitl_trace = any(e.get("node") == "hitl" for e in events)
            if not hitl.get("resolved") and not has_hitl_trace:
                state["status"] = "waiting_hitl"
                state["next_action"] = "end"
                _append_trace(
                    state,
                    "人确",
                    "hitl",
                    ok=True,
                    tool="interrupt",
                    waiting=True,
                    reasons=hitl.get("reasons"),
                )

            resumed = interrupt(
                {
                    "prompt": hitl.get("prompt"),
                    "reasons": hitl.get("reasons") or [],
                    "run_id": state.get("run_id"),
                }
            )
            if isinstance(resumed, dict):
                hitl.update(
                    {
                        "decision": resumed.get("decision"),
                        "note": resumed.get("note") or "",
                        "resolved": True,
                        "required": True,
                    }
                )
            else:
                hitl.update({"decision": str(resumed), "resolved": True, "required": True})
            state["hitl"] = hitl  # type: ignore[typeddict-item]
            state["status"] = "running"
            state["next_action"] = "supervisor"
            state["sla_flags"] = build_sla_flags(state.get("service_ticket") or {}, hitl)
            _append_trace(state, "站长人确", "hitl", ok=True, tool="interrupt", decision=hitl.get("decision"))
            return state  # type: ignore[return-value]
        except ImportError:
            pass

    state["status"] = "waiting_hitl"
    state["next_action"] = "end"
    _append_trace(state, "站长人确", "hitl", ok=True, tool="pause", waiting=True, reasons=hitl.get("reasons"))
    return state  # type: ignore[return-value]


def submit_node(state: CopilotState, client: RagClient | None = None) -> CopilotState:
    state = copy_state(state)
    if state.get("work_order_submit"):
        state["status"] = "succeeded"
        state["final_summary"] = _summarize(state, [])
        state["next_action"] = "end"
        _append_trace(state, "提交-HTTP", "submit", ok=True, tool="submit", note="already_submitted")
        return state  # type: ignore[return-value]
    eligible, blockers = evaluate_submit_eligible(state)
    state["submit_eligible"] = eligible
    if not eligible:
        state["status"] = "failed"
        state["error"] = "提交门禁未通过: " + "; ".join(blockers)
        state["next_action"] = "end"
        _append_trace(state, "提交-HTTP", "submit", ok=False, tool="submit", blockers=blockers)
        return state  # type: ignore[return-value]
    client = client or get_rag_client(str(state.get("api_key") or ""))
    try:
        submitted = client.submit_work_order(
            state.get("work_order_draft") or {},
            note="copilot:" + str(state.get("run_id") or ""),
        )
        if isinstance(submitted, dict):
            submitted = {
                **submitted,
                "destination": "rag_mock_inbox",
                "is_production_ticket": False,
            }
        _link(state, "work_orders.submit")
        state["work_order_submit"] = submitted
        # 4.2 回写反馈（失败不阻断；降级/质检 force_hitl 记 down）
        critic = state.get("critic_report") or {}
        feedback_rating = "up"
        if state.get("rag_degraded") or critic.get("force_hitl") or not critic.get("passed", True):
            feedback_rating = "down"
        feedback_comment = (
            "copilot_submit_closed_loop"
            if feedback_rating == "up"
            else "copilot_submit_degraded_or_quality_flags"
        )
        try:
            fb = client.submit_feedback(
                knowledge_base=str(state.get("knowledge_base") or "demo-kb"),
                rating=feedback_rating,
                query=str(state.get("raw_input") or ""),
                result={
                    "answer": (state.get("rag_result") or {}).get("answer"),
                    "run_id": state.get("run_id"),
                    "ticket": submitted,
                    "rag_degraded": state.get("rag_degraded"),
                    "quality_passed": critic.get("passed", True),
                },
                comment=feedback_comment,
            )
            _link(state, "feedback")
            state["feedback_ref"] = {"ok": True, "payload": fb, "rating": feedback_rating}
        except Exception as exc:  # noqa: BLE001
            state["feedback_ref"] = {"ok": False, "error": str(exc)}
            _append_trace(state, "反馈-HTTP", "feedback", ok=False, tool="feedback", error=str(exc))

        state["status"] = "succeeded"
        state["final_summary"] = _summarize(state, [])
        state["next_action"] = "end"
        _append_trace(
            state,
            "提交-HTTP",
            "submit",
            ok=True,
            tool="submit",
            ticket=submitted.get("ticket_id") or submitted,
            feedback_ok=(state.get("feedback_ref") or {}).get("ok"),
            feedback_rating=(state.get("feedback_ref") or {}).get("rating"),
        )
    except RagToolError as exc:
        state["status"] = "failed"
        state["error"] = str(exc)
        state["next_action"] = "end"
        _append_trace(state, "提交-HTTP", "submit", ok=False, tool="submit", error=str(exc))
    return state  # type: ignore[return-value]


NODE_FUNCS: dict[str, Callable[..., CopilotState]] = {
    "supervisor": supervisor_node,
    "rag": rag_node,
    "quality": quality_node,
    "work_order": work_order_node,
    "parts": parts_node,
    "hitl": hitl_node,
    "submit": submit_node,
}
