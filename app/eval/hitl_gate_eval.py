"""HITL 闭集门禁评测：should_hitl 符合率（非线上 precision）。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT
from app.eval.ssot import resolve_git_sha

EVAL_DIR = PROJECT_ROOT / "data" / "eval"
GOLDSET = EVAL_DIR / "goldsets" / "hitl_gate_cases.jsonl"
PLAYBOOKS = PROJECT_ROOT / "data" / "playbooks"
REPORT_PATH = EVAL_DIR / "hitl_gate_report.json"
SCHEMA = "hitl_gate_report/v1"


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(json.loads(line))
    return rows


def _resolve_case(row: dict[str, Any]) -> dict[str, Any]:
    src = str(row.get("source") or "")
    if src.startswith("playbook:"):
        pid = src.split(":", 1)[1].strip()
        path = PLAYBOOKS / f"{pid}.json"
        pb = json.loads(path.read_text(encoding="utf-8"))
        merged = {
            "id": row.get("id") or pid,
            "question": pb.get("question"),
            "api_key": pb.get("api_key") or "demo-technician",
            "station": pb.get("station"),
            "second_visit": pb.get("second_visit"),
            "sla_class": pb.get("sla_class"),
            "parts_hints": pb.get("parts_hints") or pb.get("parts_hint") or [],
            "knowledge_base": pb.get("knowledge_base") or "demo-kb",
            "auto_submit": bool(pb.get("auto_submit") or False),
            "expect_should_hitl": row.get("expect_should_hitl"),
            "expect_policy_any": list(row.get("expect_policy_any") or []),
            "expect_status_in": list(row.get("expect_status_in") or []),
            "split": row.get("split") or "core",
            "source": src,
        }
        if isinstance(merged["parts_hints"], str):
            merged["parts_hints"] = [merged["parts_hints"]]
        return merged
    out = dict(row)
    hints = out.get("parts_hints") or []
    if isinstance(hints, str):
        out["parts_hints"] = [hints]
    out.setdefault("api_key", "demo-technician")
    out.setdefault("split", "core")
    return out


def _fake_client(question: str, parts: list[str] | None):
    from app.tools.eval_stub import EvalRagStub

    conflicts: list[dict[str, str]] = []
    if any(x in question for x in ("质保", "哪个为准", "新旧", "不一致")):
        conflicts = [{"doc_a": "旧版", "doc_b": "新版", "metric": "质保月数"}]
    payload = {
        "answer": "两版制度数字不一致，并列展示，不作裁决。" if conflicts else "H103 与液压压力相关。",
        "sources": [{"chunk": {"source": "故障码对照表.txt", "text": "H103"}, "score": 0.9}],
        "grounded": True,
        "grounding_score": 0.85,
        "blocked": False,
        "conflicts": conflicts,
    }
    return EvalRagStub(
        ask_payload=payload,
        parts=parts or ["液压泵总成"],
        ticket_id="T-DEMO-1",
        request_id="fake-req",
    )


def _run_case(case: dict[str, Any]) -> dict[str, Any]:
    from app.graph.runner import create_initial_state, run_until_pause

    hints = list(case.get("parts_hints") or [])
    client = _fake_client(str(case.get("question") or ""), hints or None)
    state = create_initial_state(
        str(case.get("question") or ""),
        api_key=str(case.get("api_key") or "demo-technician"),
        knowledge_base=str(case.get("knowledge_base") or "demo-kb"),
        auto_submit=bool(case.get("auto_submit") or False),
        parts_force_hints=hints,
        station=case.get("station"),
        second_visit=case.get("second_visit"),
        sla_class=case.get("sla_class"),
        engine="langgraph",
    )
    out = run_until_pause(state, client=client, persist=False)  # type: ignore[arg-type]
    status = str(out.get("status") or "")
    actual_hitl = status == "waiting_hitl"
    reasons = " ".join((out.get("hitl") or {}).get("reasons") or [])
    policy_ids = list((out.get("decision_certificate") or {}).get("policy_ids") or [])
    from app.policy.hitl_layers import compute_pending_layers

    pending_layers = list((out.get("hitl") or {}).get("pending_layers") or []) or compute_pending_layers(out)
    expect_hitl = bool(case.get("expect_should_hitl"))
    status_ok = True
    expect_statuses = list(case.get("expect_status_in") or [])
    if expect_statuses:
        status_ok = status in expect_statuses
    hitl_ok = actual_hitl is expect_hitl
    policy_ok = True
    want_any = list(case.get("expect_policy_any") or [])
    if want_any and expect_hitl:
        policy_ok = any(pid in reasons or pid in policy_ids for pid in want_any)
    # 未批准不得已业务 submit
    submitted = out.get("work_order_submit")
    leak = bool(submitted) and status != "succeeded" and expect_hitl
    if expect_hitl and actual_hitl and submitted:
        leak = True
    if not expect_hitl and status == "waiting_hitl":
        leak = False
    ok = hitl_ok and status_ok and policy_ok and not leak
    expect_layers = list(case.get("expect_pending_layers") or [])
    layer_diff: dict[str, Any] = {}
    if expect_layers:
        expect_set = set(expect_layers)
        actual_set = set(pending_layers)
        missing = sorted(expect_set - actual_set)
        extra = sorted(actual_set - expect_set)
        layer_diff = {"expect": expect_layers, "actual": pending_layers, "missing": missing, "extra": extra}
        if missing or extra:
            ok = False
    elif not ok and expect_hitl:
        layer_diff = {"actual": pending_layers}
    return {
        "id": case.get("id"),
        "split": case.get("split"),
        "ok": ok,
        "expect_should_hitl": expect_hitl,
        "actual_hitl": actual_hitl,
        "status": status,
        "hitl_ok": hitl_ok,
        "policy_ok": policy_ok,
        "status_ok": status_ok,
        "leak_submit": leak,
        "policy_ids": policy_ids,
        "pending_layers": pending_layers,
        "layer_diff": layer_diff or None,
        "source": case.get("source"),
    }


def build_hitl_gate_report(*, cases_path: Path | None = None) -> dict[str, Any]:
    rows = _load_jsonl(cases_path or GOLDSET)
    results: list[dict[str, Any]] = []
    for row in rows:
        case = _resolve_case(row)
        results.append(_run_case(case))

    should = [r for r in results if r.get("expect_should_hitl")]
    should_not = [r for r in results if not r.get("expect_should_hitl")]
    should_hitl_recall = (
        sum(1 for r in should if r.get("actual_hitl")) / len(should) if should else None
    )
    false_hitl_rate = (
        sum(1 for r in should_not if r.get("actual_hitl")) / len(should_not) if should_not else None
    )
    leak_n = sum(1 for r in results if r.get("leak_submit"))
    # 诚实阈值：闭集允许少量边界误差；仍禁止漏提（leak）与大面积假 HITL
    thr_recall = 0.92
    thr_false = 0.08
    recall_ok = should_hitl_recall is None or float(should_hitl_recall) >= thr_recall
    false_ok = false_hitl_rate is None or float(false_hitl_rate) <= thr_false
    cases_ok = all(bool(r.get("ok")) for r in results)
    # all_ok：无漏提 + 阈值；单案 ok 失败记入 failed_ids 供审阅（不因单案边界一票否决阈值）
    all_ok = leak_n == 0 and recall_ok and false_ok and cases_ok
    failed_ids = [r.get("id") for r in results if not r.get("ok")]
    failed_details = [
        {
            "id": r.get("id"),
            "pending_layers": r.get("pending_layers"),
            "layer_diff": r.get("layer_diff"),
            "status": r.get("status"),
            "leak_submit": r.get("leak_submit"),
        }
        for r in results
        if not r.get("ok")
    ]
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": resolve_git_sha(),
        "mode": "offline_goldset",
        "note": "offline_goldset_not_production_precision；分母见 n_cases；非线上 SLA",
        "n_cases": len(results),
        "all_ok": all_ok,
        "failed_ids": failed_ids,
        "failed_details": failed_details,
        "metrics": {
            "should_hitl_recall": should_hitl_recall,
            "false_hitl_rate": false_hitl_rate,
            "leak_submit_count": leak_n,
            "case_pass_rate": (sum(1 for r in results if r.get("ok")) / len(results)) if results else 0.0,
            "n_should_hitl": len(should),
            "n_should_not_hitl": len(should_not),
        },
        "thresholds": {
            "should_hitl_recall_min": thr_recall,
            "false_hitl_rate_max": thr_false,
            "leak_submit_count_max": 0,
        },
        "results": results,
        "source": str((cases_path or GOLDSET).relative_to(PROJECT_ROOT)),
    }


def write_hitl_gate_report(path: Path | None = None, *, cases_path: Path | None = None) -> dict[str, Any]:
    report = build_hitl_gate_report(cases_path=cases_path)
    out = path or REPORT_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
