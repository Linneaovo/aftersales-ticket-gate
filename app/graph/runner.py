from __future__ import annotations

import uuid
from typing import Any

from app.config import get_settings
from app.graph.builder import checkpoint_exists
from app.graph.nodes import NODE_FUNCS
from app.graph.state import CopilotState, copy_state, empty_state, merge_state
from app.policy.gates import filter_conflict_for_role, role_from_api_key
from app.tools.context import reset_rag_client, set_rag_client
from app.tools.rag_client import RagClient
from app.tracing.store import append_trace_file, save_run_snapshot

TERMINAL = {"succeeded", "failed", "rejected", "cancelled"}


def _mark_engine_degraded(state: CopilotState, reason: str) -> CopilotState:
    prev = str(state.get("error") or "").strip()
    return merge_state(
        state,
        engine_degraded=True,
        engine_degraded_reason=reason,
        error=f"{prev}; {reason}".strip("; ") if prev else reason,
    )


def _fail_langgraph_strict(state: CopilotState, reason: str) -> CopilotState:
    """ENGINE_STRICT=1 时 LangGraph 失败直接 failed，不降级 fallback。"""
    return merge_state(
        state,
        status="failed",
        engine="langgraph",
        engine_degraded=False,
        error=reason,
        final_summary=reason,
        next_action="end",
    )


def create_initial_state(
    question: str,
    *,
    api_key: str | None = None,
    role: str | None = None,
    knowledge_base: str | None = None,
    history: list[dict] | None = None,
    auto_submit: bool | None = None,
    max_iterations: int | None = None,
    run_id: str | None = None,
    parts_force_hints: list[str] | None = None,
    engine: str | None = None,
    station: str | None = None,
    second_visit: bool | None = None,
    sla_class: str | None = None,
    parent_run_id: str | None = None,
) -> CopilotState:
    settings = get_settings()
    key = api_key or settings.api_key
    from app.tracing.store import fingerprint_api_key

    resolved_role = role or role_from_api_key(key)
    return empty_state(
        run_id=run_id or uuid.uuid4().hex[:12],
        api_key=key,
        api_key_fp=fingerprint_api_key(key),
        role=resolved_role,
        knowledge_base=knowledge_base or settings.default_kb,
        raw_input=question,
        history=history or [],
        auto_submit=settings.auto_submit if auto_submit is None else auto_submit,
        max_iterations=max_iterations or settings.max_iterations,
        parts_force_hints=list(parts_force_hints or []),
        status="running",
        next_action="supervisor",
        engine=engine or "langgraph",
        station_override=station or "",
        second_visit_override=second_visit,
        sla_class_override=sla_class or "",
        parent_run_id=str(parent_run_id or ""),
    )


def _maybe_clear_terminal_checkpoint(state: CopilotState) -> None:
    """终态清理 LangGraph checkpoint，避免 orphan 与 persistence_ok=false。"""
    if state.get("status") not in TERMINAL:
        return
    run_id = str(state.get("run_id") or "").strip()
    if not run_id:
        return
    from app.graph.builder import clear_checkpoint_thread

    try:
        clear_checkpoint_thread(run_id)
    except Exception:
        pass


def _persist(state: CopilotState, persist: bool) -> None:
    if persist:
        append_trace_file(state)
        save_run_snapshot(state)
    _maybe_clear_terminal_checkpoint(state)


def step_fallback(state: CopilotState, client: Any = None) -> CopilotState:
    """无 interrupt 的逐步执行（单测 / LangGraph 不可用时）。"""
    if state.get("status") in TERMINAL:
        return state
    action = state.get("next_action") or "supervisor"
    if action == "end":
        return state

    if action == "supervisor":
        state = NODE_FUNCS["supervisor"](state)
        action = state.get("next_action") or "end"
        if action == "end" or state.get("status") in TERMINAL:
            return state
        if state.get("status") == "waiting_hitl" and action == "hitl":
            # fallback 不支持 LangGraph interrupt/resume，禁止假 waiting_hitl
            return merge_state(
                state,
                engine="fallback",
                engine_degraded=True,
                status="failed",
                error="fallback 引擎不支持 HITL interrupt/resume；请使用 langgraph 重跑",
                final_summary="fallback 引擎不支持 HITL；无 checkpoint 不可 resume",
                next_action="end",
            )

    if action == "end":
        return state

    fn = NODE_FUNCS.get(str(action))
    if fn is None:
        return merge_state(
            state,
            status="failed",
            error=f"未知节点: {action}",
            next_action="end",
        )

    if action in {"rag", "work_order", "submit"}:
        state = fn(state, client=client)  # type: ignore[misc]
    else:
        state = fn(state)

    # fallback 任意节点进入 waiting_hitl 都禁止（含直接 next_action=hitl）
    if state.get("status") == "waiting_hitl":
        return merge_state(
            state,
            engine="fallback",
            engine_degraded=True,
            status="failed",
            error="fallback 引擎不支持 HITL interrupt/resume；请使用 langgraph 重跑",
            final_summary="fallback 引擎不支持 HITL；无 checkpoint 不可 resume",
            next_action="end",
        )
    if state.get("status") in TERMINAL:
        return state
    return merge_state(state, next_action="supervisor")


def run_fallback(
    state: CopilotState,
    *,
    client: RagClient | None = None,
    persist: bool = True,
) -> CopilotState:
    state = merge_state(state, engine="fallback", execution_path="fallback")
    state = _append_engine_selected_trace(state)
    client = client or RagClient(api_key=str(state.get("api_key") or ""))
    token = set_rag_client(client)
    try:
        guard = 0
        max_guard = int(state.get("max_iterations") or 8) * 4 + 5
        while guard < max_guard:
            guard += 1
            if state.get("status") in TERMINAL:
                break
            if state.get("status") == "waiting_hitl" and not (state.get("hitl") or {}).get("resolved"):
                break
            state = step_fallback(state, client=client)
            if state.get("status") == "waiting_hitl":
                break
            if state.get("next_action") == "end" and state.get("status") != "running":
                break
    finally:
        reset_rag_client(token)
    if state.get("status") == "waiting_hitl" and not (state.get("hitl") or {}).get("resolved"):
        state = merge_state(
            state,
            status="failed",
            error="fallback 引擎不支持 HITL interrupt/resume；请使用 langgraph 重跑",
            final_summary="fallback 引擎 HITL 不可恢复",
            next_action="end",
        )
    state = _finalize_run_state(state)
    _persist(state, persist)
    return state


def _derive_work_order_state(state: CopilotState) -> str:
    status = str(state.get("status") or "running")
    if status == "waiting_hitl":
        return "pending_chief"
    if status in {"rejected", "cancelled", "failed"}:
        return status
    if state.get("work_order_submit"):
        return "submitted"
    if state.get("work_order_draft"):
        role = str(state.get("role") or "")
        eligible = state.get("submit_eligible")
        if role != "station_chief" and status == "succeeded" and eligible is False:
            return "ready_for_chief"
        return "drafting"
    return "intake"


def _derive_execution_path(state: CopilotState) -> str:
    if state.get("engine_degraded") or state.get("engine") == "fallback":
        return "fallback"
    return "langgraph"


def _append_engine_selected_trace(state: CopilotState) -> CopilotState:
    events = list(state.get("trace_events") or [])
    if any(e.get("node") == "engine_selected" for e in events):
        return state
    import time

    from app.config import get_settings
    from app.tools.rag_factory import is_rag_reachable

    settings = get_settings()
    if settings.demo_offline:
        rag_mode = "demo_offline"
        kport = "fixture"
    elif is_rag_reachable():
        rag_mode = "live"
        kport = "http"
    elif settings.rag_auto_fallback:
        rag_mode = "demo_offline"
        kport = "fixture"
    else:
        rag_mode = "unreachable"
        kport = "none"
    events.insert(
        0,
        {
            "ts": time.time(),
            "run_id": state.get("run_id"),
            "iteration": 0,
            "agent": "运行时",
            "node": "engine_selected",
            "ok": True,
            "engine": state.get("engine") or "langgraph",
            "execution_path": _derive_execution_path(state),
            "rag_client_mode": rag_mode,
            "knowledge_port": kport,
        },
    )
    return merge_state(state, trace_events=events)


def _finalize_run_state(state: CopilotState) -> CopilotState:
    return merge_state(
        state,
        work_order_state=_derive_work_order_state(state),
        execution_path=_derive_execution_path(state),
    )


def _langgraph_values_to_state(base: CopilotState, values: dict[str, Any]) -> CopilotState:
    """LangGraph snapshot → CopilotState（merge 保留未出现在 snapshot 中的字段）。"""
    cleaned = {k: v for k, v in values.items() if not str(k).startswith("__")}
    return _finalize_run_state(merge_state(base, **cleaned))  # type: ignore[arg-type]


def _ensure_hitl_trace(values: dict[str, Any]) -> None:
    """LangGraph 可能在 human_confirm 执行前 pause，补写 hitl trace 节点。"""
    import time

    events = list(values.get("trace_events") or [])
    if any(e.get("node") == "hitl" for e in events):
        return
    hitl = dict(values.get("hitl") or {})
    events.append(
        {
            "ts": time.time(),
            "run_id": values.get("run_id"),
            "iteration": values.get("iteration", 0),
            "agent": "人确",
            "node": "hitl",
            "ok": True,
            "tool": "interrupt_pending",
            "waiting": True,
            "reasons": hitl.get("reasons") or [],
        }
    )
    values["trace_events"] = events


def _run_langgraph(
    state: CopilotState,
    *,
    client: RagClient | None = None,
    persist: bool = True,
    resume_value: dict[str, Any] | None = None,
) -> CopilotState:
    from app.graph.builder import get_compiled_graph

    graph = get_compiled_graph()
    run_id = str(state.get("run_id") or uuid.uuid4().hex[:12])
    state = merge_state(state, run_id=run_id, engine="langgraph", execution_path="langgraph")
    state = _append_engine_selected_trace(state)
    config = {"configurable": {"thread_id": run_id}}
    client = client or RagClient(api_key=str(state.get("api_key") or ""))
    token = set_rag_client(client)
    try:
        if resume_value is None:
            result = graph.invoke(state, config)
        else:
            from langgraph.types import Command

            result = graph.invoke(Command(resume=resume_value), config)

        # interrupt 时 LangGraph 可能返回带 __interrupt__ 的状态
        out = dict(result or {})
        interrupts = out.get("__interrupt__")
        snap = graph.get_state(config)
        values = dict(snap.values or out)
        if interrupts or (snap.next and "human_confirm" in (snap.next or ())):
            values["status"] = "waiting_hitl"
            values["next_action"] = "hitl"
            hitl = dict(values.get("hitl") or {})
            hitl["required"] = True
            values["hitl"] = hitl
            _ensure_hitl_trace(values)
        values.pop("__interrupt__", None)
        values["engine"] = "langgraph"
        final_state = _langgraph_values_to_state(state, values)
        _persist(final_state, persist)
        return final_state
    except Exception as exc:
        # GraphInterrupt 或其他：尽量从 checkpoint 恢复
        try:
            from langgraph.errors import GraphInterrupt

            if isinstance(exc, GraphInterrupt):
                snap = graph.get_state(config)
                values = dict(snap.values or state)
                values["status"] = "waiting_hitl"
                values["engine"] = "langgraph"
                _ensure_hitl_trace(values)
                final_state = _langgraph_values_to_state(state, values)
                _persist(final_state, persist)
                return final_state
        except Exception:
            pass
        settings = get_settings()
        if settings.engine_strict:
            failed = _fail_langgraph_strict(state, f"langgraph 执行异常（ENGINE_STRICT）: {exc}")
            _persist(failed, persist)
            return failed
        state = _mark_engine_degraded(state, f"langgraph 执行异常，已降级: {exc}")
        return run_fallback(merge_state(state, engine="fallback"), client=client, persist=persist)
    finally:
        reset_rag_client(token)


def run_until_pause(
    state: CopilotState,
    *,
    client: RagClient | None = None,
    persist: bool = True,
) -> CopilotState:
    engine = state.get("engine") or "langgraph"
    if engine == "fallback":
        return run_fallback(state, client=client, persist=persist)
    try:
        return _run_langgraph(state, client=client, persist=persist)
    except Exception as exc:
        settings = get_settings()
        if settings.engine_strict:
            failed = _fail_langgraph_strict(state, f"langgraph 外层异常（ENGINE_STRICT）: {exc}")  # type: ignore[arg-type]
            _persist(failed, persist)
            return failed
        degraded = _mark_engine_degraded(state, f"langgraph 外层异常，已降级: {exc}")  # type: ignore[arg-type]
        return run_fallback(merge_state(degraded, engine="fallback"), client=client, persist=persist)


def apply_hitl(
    state: CopilotState,
    decision: str,
    note: str = "",
    *,
    client: RagClient | None = None,
    persist: bool = True,
    approver_api_key: str | None = None,
    confirmations: dict[str, bool] | None = None,
) -> CopilotState:
    """人确续跑。批准/拒绝/退回补件均须站长 Key（领域层强制，不只依赖 API）。"""
    from app.policy.gates import is_station_chief
    from app.policy.hitl_layers import normalize_confirmations

    if not is_station_chief(api_key=approver_api_key):
        raise PermissionError(
            "人确须站长角色（领域层 POL-ROLE-01）。请传站长 API Key；"
            "生产应接 SSO→role 映射，禁止仅靠网关口头约定。"
        )

    # edit → return：退回补件终止，不改草稿
    if decision == "edit":
        decision = "return"

    conf = normalize_confirmations(confirmations)
    resume_payload: dict[str, Any] = {"decision": decision, "note": note, "confirmations": conf}
    run_id = str(state.get("run_id") or "")
    use_langgraph = (state.get("engine") or "langgraph") == "langgraph"
    if use_langgraph and not checkpoint_exists(run_id):
        settings = get_settings()
        # O5：STRICT 下禁止无 checkpoint 默默 fallback 扮 interrupt 续跑
        if settings.engine_strict:
            failed = _fail_langgraph_strict(
                state,
                "checkpoint_missing: HITL resume 无 LangGraph checkpoint（ENGINE_STRICT=1）；"
                "请重新跑剧本或 ENGINE_STRICT=0 显式允许 fallback",
            )
            _persist(failed, persist)
            return failed
        state = _mark_engine_degraded(
            state,
            "HITL checkpoint 丢失，已切换 fallback 续跑（无 interrupt/resume）",
        )
        use_langgraph = False

    if use_langgraph:
        try:
            # 先写入 hitl，再 Command(resume)
            hitl = dict(state.get("hitl") or {})
            hitl.update(
                {
                    "decision": decision,
                    "note": note,
                    "resolved": True,
                    "required": True,
                    "confirmations": conf,
                }
            )
            if approver_api_key:
                # 仅记录，不改业务角色（业务角色仍是提单人）
                hitl["approver_key_role"] = role_from_api_key(approver_api_key)
            state = merge_state(state, hitl=hitl)
            out = _run_langgraph(state, client=client, persist=persist, resume_value=resume_payload)
            if out.get("engine") == "fallback" or out.get("engine_degraded"):
                return out
            return out
        except Exception as exc:
            state = _mark_engine_degraded(state, f"HITL langgraph resume 失败: {exc}")  # type: ignore[arg-type]

    hitl = dict(state.get("hitl") or {})
    hitl.update(
        {
            "decision": decision,
            "note": note,
            "resolved": True,
            "required": True,
            "confirmations": conf,
        }
    )
    if approver_api_key:
        hitl["approver_key_role"] = role_from_api_key(approver_api_key)
    state = merge_state(
        state,
        hitl=hitl,
        status="running",
        next_action="supervisor",
        engine="fallback",
    )
    from app.policy.decision_certificate import build_decision_certificate

    state = merge_state(state, decision_certificate=build_decision_certificate(state, phase="resolved"))
    return run_fallback(state, client=client, persist=persist)  # type: ignore[arg-type]


def _slim_draft(draft: dict[str, Any] | None) -> dict[str, Any] | None:
    if not draft:
        return draft
    body = draft.get("draft") if isinstance(draft.get("draft"), dict) else draft
    if not isinstance(body, dict):
        return {"ok": draft.get("ok"), "source": draft.get("source")}
    return {
        "ok": draft.get("ok", True),
        "source": draft.get("source"),
        "ticket_type": body.get("ticket_type"),
        "machine_model": body.get("machine_model"),
        "fault_codes": body.get("fault_codes"),
        "recommended_parts_count": len(body.get("recommended_parts") or []),
    }


def public_view(state: CopilotState, *, view: str = "default") -> dict[str, Any]:
    role = str(state.get("role") or "technician")
    conflict = filter_conflict_for_role(state.get("conflict_bundle"), role)
    strict_public = view == "public"
    draft = state.get("work_order_draft")
    if strict_public:
        draft = _slim_draft(draft if isinstance(draft, dict) else None)
    parts = state.get("parts_check")
    if strict_public and isinstance(parts, dict):
        parts = {
            "needed": parts.get("needed"),
            "shortage": parts.get("shortage"),
            "shortage_items": parts.get("shortage_items"),
            "alt_depot": parts.get("alt_depot"),
            "suggested_action": parts.get("suggested_action"),
            "note": parts.get("note"),
            "hints_source": parts.get("hints_source"),
            "master_data_authority": parts.get("master_data_authority"),
        }
    rag_mode = "demo_offline" if state.get("rag_offline_mode") else "live"
    submit = state.get("work_order_submit")
    if strict_public and submit:
        submit = {
            "ok": submit.get("ok"),
            "ticket_id": submit.get("ticket_id"),
            "destination": submit.get("destination") or "rag_mock_inbox",
            "is_production_ticket": submit.get("is_production_ticket", False),
        }
    elif isinstance(submit, dict):
        submit = {
            **submit,
            "destination": submit.get("destination") or "rag_mock_inbox",
            "is_production_ticket": submit.get("is_production_ticket", False),
        }
    return {
        "run_id": state.get("run_id"),
        "status": state.get("status"),
        "role": role,
        "intent": state.get("intent"),
        "intent_label": "报修开单" if state.get("intent") == "fault_dispatch" else state.get("intent"),
        "intent_confidence": state.get("intent_confidence"),
        "intent_signals": state.get("intent_signals") or [],
        "iteration": state.get("iteration"),
        "engine": state.get("engine"),
        "engine_degraded": bool(state.get("engine_degraded")),
        "engine_degraded_reason": state.get("engine_degraded_reason"),
        "execution_path": state.get("execution_path") or _derive_execution_path(state),
        "work_order_state": state.get("work_order_state") or _derive_work_order_state(state),
        "rag_offline_mode": bool(state.get("rag_offline_mode")),
        "rag_client_mode": rag_mode,
        "knowledge_port": "fixture" if rag_mode == "demo_offline" or state.get("rag_offline_mode") else "http",
        "final_summary": state.get("final_summary"),
        "scope_note": "报修开单门禁；提交为 file_outbox 或 rag_mock_inbox；非 ERP 派工/非生产开单系统",
        "not_erp_dispatch": True,
        "error": state.get("error"),
        "submit_eligible": state.get("submit_eligible"),
        "service_ticket": state.get("service_ticket"),
        "station_context": state.get("station_context"),
        "sla_flags": state.get("sla_flags"),
        "rag_linkage": state.get("rag_linkage") or [],
        "rag_linkage_detail": state.get("rag_linkage_detail") or {},
        "rag_degraded": state.get("rag_degraded"),
        "feedback_ref": state.get("feedback_ref"),
        "role_path": state.get("role_path"),
        "conflict_bundle": conflict,
        "critic_report": state.get("critic_report"),
        "parts_check": parts,
        "decision_certificate": state.get("decision_certificate"),
        "parent_run_id": state.get("parent_run_id") or None,
        "return_for_rework": bool(state.get("return_for_rework")),
        "return_note": (
            str((state.get("hitl") or {}).get("note") or "")
            if state.get("return_for_rework")
            or (state.get("hitl") or {}).get("decision") in {"return", "edit"}
            else None
        ),
        "reopen_hint": (
            "使用 parent_run_id 调用 POST /runs 基于退回说明重新开跑（不改原 draft）"
            if state.get("return_for_rework")
            or (state.get("hitl") or {}).get("decision") in {"return", "edit"}
            else None
        ),
        "hitl": state.get("hitl") if not strict_public else {
            "required": (state.get("hitl") or {}).get("required"),
            "resolved": (state.get("hitl") or {}).get("resolved"),
            "decision": (state.get("hitl") or {}).get("decision"),
            "reasons": (state.get("hitl") or {}).get("reasons"),
            "prompt": (state.get("hitl") or {}).get("prompt"),
            "pending_layers": (state.get("hitl") or {}).get("pending_layers") or [],
            "confirmations": (state.get("hitl") or {}).get("confirmations") or {},
        },
        "work_order_draft": draft,
        "work_order_submit": submit,
        "retrieve_hits_count": len(state.get("retrieve_hits") or []),
        "rag": {
            "answer": (state.get("rag_result") or {}).get("answer"),
            "grounded": (state.get("rag_result") or {}).get("grounded"),
            "grounding_score": (state.get("rag_result") or {}).get("grounding_score"),
            "blocked": (state.get("rag_result") or {}).get("blocked"),
            "block_reason": (state.get("rag_result") or {}).get("block_reason"),
            "conflicts": (state.get("rag_result") or {}).get("conflicts"),
            "request_id": (state.get("rag_result") or {}).get("request_id"),
            "sources": [
                {
                    "source": ((s.get("chunk") or {}).get("source") if isinstance(s, dict) else None),
                    "score": s.get("score") if isinstance(s, dict) else None,
                }
                for s in ((state.get("rag_result") or {}).get("sources") or [])[:5]
            ],
        },
        "trace_events": state.get("trace_events") or [] if not strict_public else [],
        "trace_preview": [] if strict_public else (state.get("trace_events") or [])[-20:],
        "trace_policy_summary": _trace_policy_summary(state.get("trace_events") or []),
        "view_mode": view,
    }


def _trace_policy_summary(events: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for ev in events:
        for pid in ev.get("policy_ids") or []:
            if pid not in seen:
                seen.append(str(pid))
        reason = str(ev.get("routing_reason") or "")
        for token in reason.split():
            if token.startswith("POL-"):
                if token not in seen:
                    seen.append(token)
    return seen
