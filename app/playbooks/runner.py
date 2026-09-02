from __future__ import annotations

from typing import Any

from app.graph.runner import create_initial_state, run_until_pause


def _hints_from_playbook(data: dict[str, Any]) -> list[str]:
    hints = data.get("parts_hints") or data.get("parts_hint") or []
    if isinstance(hints, str):
        return [hints]
    return list(hints)


def run_playbook_from_data(
    data: dict[str, Any],
    *,
    client: Any,
    engine: str = "langgraph",
    persist: bool = False,
) -> dict[str, Any]:
    state = create_initial_state(
        str(data.get("question") or ""),
        api_key=str(data.get("api_key") or "demo-technician"),
        knowledge_base=str(data.get("knowledge_base") or "demo-kb"),
        auto_submit=bool(data.get("auto_submit") or False),
        parts_force_hints=_hints_from_playbook(data),
        station=data.get("station"),
        second_visit=data.get("second_visit"),
        sla_class=data.get("sla_class"),
        engine=engine,
    )
    return run_until_pause(state, client=client, persist=persist)  # type: ignore[arg-type]


def validate_playbook_result(spec: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
    """对比 playbook 规格与实际 run 结果，返回 diff 报告。"""
    diffs: list[dict[str, Any]] = []
    nodes = [e.get("node") for e in (out.get("trace_events") or [])]
    reasons_text = " ".join((out.get("hitl") or {}).get("reasons") or [])

    expect_status = spec.get("expect_status")
    actual_status = out.get("status")
    if expect_status and actual_status != expect_status:
        diffs.append(
            {
                "field": "status",
                "expected": expect_status,
                "actual": actual_status,
            }
        )

    expect_intent = spec.get("expect_intent")
    actual_intent = out.get("intent")
    if expect_intent and actual_intent != expect_intent:
        diffs.append(
            {
                "field": "intent",
                "expected": expect_intent,
                "actual": actual_intent,
            }
        )

    linkage = list(out.get("rag_linkage") or [])
    if actual_intent == "fault_dispatch" and linkage:
        if "ask" not in linkage:
            diffs.append(
                {
                    "field": "rag_linkage",
                    "expected": "contains ask",
                    "actual": linkage,
                }
            )
        if not any(x in linkage for x in ("work_orders.draft", "ask.work_order")):
            diffs.append(
                {
                    "field": "rag_linkage",
                    "expected": "work_orders.draft or ask.work_order",
                    "actual": linkage,
                }
            )

    for node in spec.get("expect_trace_prefix") or []:
        if node == "work_order" and node not in nodes and "ask.work_order" in linkage:
            continue
        if node not in nodes:
            diffs.append(
                {
                    "field": "trace_node",
                    "expected": node,
                    "actual": nodes,
                }
            )

    for policy_id in spec.get("expect_hitl_reasons") or []:
        if policy_id not in reasons_text:
            diffs.append(
                {
                    "field": "hitl_reason",
                    "expected": policy_id,
                    "actual": reasons_text,
                }
            )

    if spec.get("expect_no_work_order_draft") and out.get("work_order_draft"):
        diffs.append(
            {
                "field": "work_order_draft",
                "expected": None,
                "actual": "present",
            }
        )

    expect_hints_source = spec.get("expect_hints_source")
    actual_hints_source = (out.get("parts_check") or {}).get("hints_source")
    if expect_hints_source and actual_hints_source != expect_hints_source:
        diffs.append(
            {
                "field": "hints_source",
                "expected": expect_hints_source,
                "actual": actual_hints_source,
            }
        )

    return {
        "passed": len(diffs) == 0,
        "diffs": diffs,
        "actual": {
            "status": actual_status,
            "intent": actual_intent,
            "trace_nodes": nodes,
            "rag_linkage": linkage,
            "work_order_draft": out.get("work_order_draft"),
            "hitl_reasons": (out.get("hitl") or {}).get("reasons") or [],
        },
        "expected": {
            "status": expect_status,
            "intent": expect_intent,
            "trace_prefix": spec.get("expect_trace_prefix"),
            "hitl_reasons": spec.get("expect_hitl_reasons"),
        },
    }
