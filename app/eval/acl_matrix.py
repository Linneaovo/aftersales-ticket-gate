"""B7：ACL 双层矩阵（L1 Copilot / L2 RAG）离线可跑。

| 配置 | 期望 |
|------|------|
| 仅 L1 | intent=acl_probe → rejected，未调 RAG |
| 仅 L2 | RAG acl_denied → POL-GROUND-02 → rejected，经 RAG |
| 双层短路 | L1 先拦，不双写/不矛盾 |
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.config import PROJECT_ROOT

EVAL_DIR = PROJECT_ROOT / "data" / "eval"
REPORT_PATH = EVAL_DIR / "acl_matrix.json"
SCHEMA = "acl_matrix/v1"


def _trace_nodes(out: dict[str, Any]) -> list[str]:
    return [str(e.get("node") or "") for e in (out.get("trace_events") or []) if isinstance(e, dict)]


def _policy_ids(out: dict[str, Any]) -> list[str]:
    cert = out.get("decision_certificate") or {}
    critic = out.get("critic_report") or {}
    ids = list(cert.get("policy_ids") or []) + list(critic.get("policy_ids") or [])
    for e in out.get("trace_events") or []:
        if isinstance(e, dict) and e.get("policy"):
            ids.append(str(e["policy"]))
        if isinstance(e, dict):
            ids.extend(str(x) for x in (e.get("policy_ids") or []))
    # final_summary 常带 POL-ACL-01
    summary = str(out.get("final_summary") or "")
    if "POL-ACL-01" in summary:
        ids.append("POL-ACL-01")
    return list(dict.fromkeys(ids))


def _run_case(
    *,
    case_id: str,
    title: str,
    question: str,
    api_key: str,
    client: Any,
    expect: dict[str, Any],
) -> dict[str, Any]:
    from app.graph.runner import create_initial_state, run_until_pause

    state = create_initial_state(
        question,
        api_key=api_key,
        knowledge_base="demo-kb",
        auto_submit=False,
        engine="langgraph",
    )
    out = run_until_pause(state, client=client, persist=False)
    nodes = _trace_nodes(out)
    policies = _policy_ids(out)
    status = out.get("status")
    intent = out.get("intent")
    has_rag = "rag" in nodes
    submit = out.get("work_order_submit")
    errors: list[str] = []

    if expect.get("status") and status != expect["status"]:
        errors.append(f"status={status!r} expect={expect['status']!r}")
    if expect.get("intent") and intent != expect["intent"]:
        errors.append(f"intent={intent!r} expect={expect['intent']!r}")
    if "rag_called" in expect and has_rag != bool(expect["rag_called"]):
        errors.append(f"rag_called={has_rag} expect={expect['rag_called']}")
    for pid in expect.get("policy_any") or []:
        if pid not in policies and pid not in str(out.get("final_summary") or ""):
            errors.append(f"missing policy {pid}")
    if expect.get("no_submit") and submit:
        errors.append("unexpected work_order_submit")

    return {
        "id": case_id,
        "title": title,
        "question": question,
        "status": status,
        "intent": intent,
        "rag_called": has_rag,
        "policy_ids": policies,
        "submit_present": bool(submit),
        "expect": expect,
        "ok": not errors,
        "errors": errors,
    }


def run_acl_matrix(
    *,
    client_factory: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """跑 L1 / L2 / 短路三格；默认 EvalRagStub（离线，不依赖 tests）。"""
    from app.tools.eval_stub import EvalRagStub

    def _default_client(spec: dict[str, Any]) -> Any:
        payload = spec.get("ask_payload")
        if payload is not None:
            return EvalRagStub(ask_payload=payload, ticket_id="T-DEMO-1", request_id="fake-req")
        return EvalRagStub(ticket_id="T-DEMO-1", request_id="fake-req")

    factory = client_factory or _default_client

    l1_q = "星沙站技师绩效薪酬保密制度工资系数是多少？"
    l2_q = "供应商内部评级标准文档里的A级门槛是什么？"  # 无 L1 acl_probe 词表
    l2_payload = {
        "answer": "当前账号无权查看受限文档。",
        "sources": [],
        "grounded": False,
        "grounding_score": 0.0,
        "blocked": True,
        "block_reason": "acl_denied",
        "conflicts": [],
    }

    cases = [
        _run_case(
            case_id="l1_only",
            title="仅 L1 Copilot 调度拦截",
            question=l1_q,
            api_key="demo-technician",
            client=factory({}),
            expect={
                "status": "rejected",
                "intent": "acl_probe",
                "rag_called": False,
                "policy_any": ["POL-ACL-01"],
                "no_submit": True,
            },
        ),
        _run_case(
            case_id="l2_only",
            title="仅 L2 RAG acl_denied → POL-GROUND-02",
            question=l2_q,
            api_key="demo-technician",
            client=factory({"ask_payload": l2_payload}),
            expect={
                "status": "rejected",
                "rag_called": True,
                "policy_any": ["POL-GROUND-02"],
                "no_submit": True,
            },
        ),
        _run_case(
            case_id="dual_l1_short_circuit",
            title="双层能力下 L1 短路：不调 RAG、不落箱",
            question=l1_q,
            api_key="demo-technician",
            client=factory({"ask_payload": l2_payload}),  # 即使 RAG 会拦，也不得走到 RAG
            expect={
                "status": "rejected",
                "intent": "acl_probe",
                "rag_called": False,
                "policy_any": ["POL-ACL-01"],
                "no_submit": True,
            },
        ),
    ]

    all_ok = all(bool(c.get("ok")) for c in cases)
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "offline_fakerag",
        "acl_l2_source": "fake_rag_stub",
        "all_ok": all_ok,
        "passed": sum(1 for c in cases if c.get("ok")),
        "total": len(cases),
        "cases": cases,
        "matrix": {
            "l1_only": next(c["ok"] for c in cases if c["id"] == "l1_only"),
            "l2_only": next(c["ok"] for c in cases if c["id"] == "l2_only"),
            "dual_short_circuit": next(c["ok"] for c in cases if c["id"] == "dual_l1_short_circuit"),
        },
        "note": (
            "L1=Copilot acl_probe；L2=RAG acl_denied→POL-GROUND-02（本报告 L2 为 FakeRag stub，非 live ACL）；"
            "短路证明不双写混乱"
        ),
    }


def write_acl_matrix(report: dict[str, Any] | None = None, path: Path = REPORT_PATH) -> dict[str, Any]:
    report = report if report is not None else run_acl_matrix()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
