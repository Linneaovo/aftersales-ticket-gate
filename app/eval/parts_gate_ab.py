"""缺料门禁 A/B 反证核心逻辑（脚本与 pytest 共用）。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

QUESTION = "长沙星沙服务站：SY215C 报故障码 H103，客户反映动臂液压无力，请安排报修开单"


def _run_case(*, parts: list[str], force_hints: list[str] | None = None) -> dict[str, Any]:
    from app.graph.builder import reset_graph_cache
    from app.graph.runner import create_initial_state, run_until_pause
    from app.tools.rag_stub_base import RagStubClient

    reset_graph_cache()
    client = RagStubClient(parts=list(parts))
    state = create_initial_state(
        QUESTION,
        api_key="demo-technician",
        knowledge_base="demo-kb",
        auto_submit=False,
        parts_force_hints=list(force_hints or []),
        station="长沙星沙服务站",
        engine="langgraph",
    )
    out = run_until_pause(state, client=client, persist=False)
    reasons = " ".join((out.get("hitl") or {}).get("reasons") or [])
    parts_check = out.get("parts_check") or {}
    return {
        "status": out.get("status"),
        "intent": out.get("intent"),
        "shortage": bool(parts_check.get("shortage")),
        "hints_source": parts_check.get("hints_source"),
        "has_pol_parts_01": "POL-PARTS-01" in reasons,
        "hitl_reasons": list((out.get("hitl") or {}).get("reasons") or []),
        "suggested_action": parts_check.get("suggested_action"),
    }


def run_parts_gate_ab() -> dict[str, Any]:
    """A: 液压泵总成 stock=0 → HITL；B: 液压滤芯 stock>0 → 无 POL-PARTS-01。"""
    case_a = _run_case(parts=["液压泵总成"])
    case_b = _run_case(parts=["液压滤芯"], force_hints=["液压滤芯"])

    expect_a_ok = (
        case_a["status"] == "waiting_hitl"
        and case_a["has_pol_parts_01"]
        and case_a["shortage"] is True
    )
    expect_b_ok = (not case_b["has_pol_parts_01"]) and case_b["shortage"] is False
    if case_b["status"] not in {"succeeded", "waiting_hitl"}:
        expect_b_ok = False
    if case_b["status"] == "waiting_hitl" and case_b["has_pol_parts_01"]:
        expect_b_ok = False

    return {
        "schema": "parts_gate_ab/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "question": QUESTION,
        "engine": "langgraph",
        "rag_mode": "fakerag_stub",
        "ledger": "data/parts_ledger.json",
        "cases": {
            "A_shortage_pump": {
                "part": "液压泵总成",
                "stock_expected": 0,
                "result": case_a,
                "expect": "waiting_hitl + POL-PARTS-01",
                "passed": expect_a_ok,
            },
            "B_in_stock_filter": {
                "part": "液压滤芯",
                "stock_expected": ">0",
                "hints_mode": "force_hints",
                "result": case_b,
                "expect": "no POL-PARTS-01 (shortage=false)",
                "passed": expect_b_ok,
            },
        },
        "all_ok": bool(expect_a_ok and expect_b_ok),
        "narrative": "同报修话术；改预核配件/库存则缺料门禁翻转——非写死必进 HITL",
    }


def _playbook_case_summary(body: dict[str, Any]) -> dict[str, Any]:
    cert = body.get("decision_certificate") or {}
    reasons = " ".join((body.get("hitl") or {}).get("reasons") or [])
    policy_ids = list(cert.get("policy_ids") or [])
    parts_check = body.get("parts_check") or {}
    has_01 = "POL-PARTS-01" in reasons or "POL-PARTS-01" in policy_ids
    return {
        "status": body.get("status"),
        "rag_client_mode": body.get("rag_client_mode"),
        "shortage": bool(parts_check.get("shortage")),
        "has_pol_parts_01": has_01,
        "policy_ids": policy_ids,
        "hitl_reasons": list((body.get("hitl") or {}).get("reasons") or []),
    }


def run_parts_gate_ab_live(
    *,
    base_url: str = "http://127.0.0.1:8002",
    timeout_s: float = 180.0,
) -> dict[str, Any]:
    """Live A/B：P1 缺料 → PARTS-01；P1b 有库存 → 无 PARTS-01。不改 Live 语料。"""
    import httpx

    tech = {"X-API-Key": "demo-technician"}
    base = base_url.rstrip("/")
    try:
        with httpx.Client(timeout=timeout_s, headers=tech) as c:
            health = c.get(f"{base}/health")
            if health.status_code != 200:
                return {
                    "schema": "parts_gate_ab_live/v1",
                    "present": False,
                    "all_ok": False,
                    "rag_mode": "live",
                    "skip_reason": f"copilot health HTTP {health.status_code}",
                }
            hbody = health.json() if health.content else {}
            if hbody.get("rag_mode") != "live":
                return {
                    "schema": "parts_gate_ab_live/v1",
                    "present": False,
                    "all_ok": False,
                    "rag_mode": hbody.get("rag_mode") or "unknown",
                    "skip_reason": "copilot rag_mode≠live",
                }

            a_resp = c.post(f"{base}/playbooks/p1_xingsha_h103/run")
            b_resp = c.post(f"{base}/playbooks/p1b_no_shortage_ready/run")
    except Exception as exc:  # noqa: BLE001
        return {
            "schema": "parts_gate_ab_live/v1",
            "present": False,
            "all_ok": False,
            "rag_mode": "live",
            "skip_reason": str(exc),
        }

    case_a = _playbook_case_summary(a_resp.json() if a_resp.status_code == 200 else {})
    case_b = _playbook_case_summary(b_resp.json() if b_resp.status_code == 200 else {})
    if a_resp.status_code != 200:
        case_a["http_error"] = a_resp.status_code
    if b_resp.status_code != 200:
        case_b["http_error"] = b_resp.status_code

    expect_a_ok = (
        a_resp.status_code == 200
        and case_a.get("status") == "waiting_hitl"
        and case_a.get("has_pol_parts_01")
        and case_a.get("shortage") is True
        and case_a.get("rag_client_mode") == "live"
    )
    expect_b_ok = (
        b_resp.status_code == 200
        and not case_b.get("has_pol_parts_01")
        and case_b.get("shortage") is False
        and case_b.get("status") in {"succeeded", "waiting_hitl"}
        and case_b.get("rag_client_mode") == "live"
    )

    return {
        "schema": "parts_gate_ab_live/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "present": True,
        "rag_mode": "live",
        "cases": {
            "A_p1_xingsha_h103": {
                "playbook": "p1_xingsha_h103",
                "result": case_a,
                "expect": "waiting_hitl + POL-PARTS-01 + shortage",
                "passed": expect_a_ok,
            },
            "B_p1b_no_shortage_ready": {
                "playbook": "p1b_no_shortage_ready",
                "result": case_b,
                "expect": "no POL-PARTS-01",
                "passed": expect_b_ok,
            },
        },
        "all_ok": bool(expect_a_ok and expect_b_ok),
        "narrative": "Live 剧本 A/B：同仓门禁；禁止用 fakerag_stub 冒充 Live 反证",
    }


def nest_parts_gate_ab(
    *,
    offline: dict[str, Any] | None = None,
    live: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """联调包分栏：offline（stub）与 live 分开展示。"""
    off = offline or {"present": False, "all_ok": False}
    liv = live or {"present": False, "all_ok": False, "skip_reason": "not_run"}
    return {
        "schema": "parts_gate_ab/v2",
        "offline": {
            "present": bool(off.get("present", True)),
            "all_ok": bool(off.get("all_ok")),
            "rag_mode": off.get("rag_mode") or "fakerag_stub",
            "schema": off.get("schema"),
        },
        "live": {
            "present": bool(liv.get("present")),
            "all_ok": bool(liv.get("all_ok")) if liv.get("present") else False,
            "rag_mode": liv.get("rag_mode") or "live",
            "schema": liv.get("schema"),
            **(
                {"skip_reason": liv.get("skip_reason")}
                if liv.get("skip_reason") and not liv.get("present")
                else {}
            ),
            **({"cases": liv.get("cases")} if liv.get("cases") else {}),
        },
        # 兼容旧读法：all_ok = offline（回归安全网）
        "all_ok": bool(off.get("all_ok")),
        "rag_mode": "nested",
        "present": True,
    }
