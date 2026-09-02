"""Live 功能全量冒烟（需 Copilot :8002；RAG :8001）。

用法：
  python scripts/live_function_test.py

Portfolio：data/eval/live_function_test.json（含 script_version / checklist_hash）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx

from app.eval.compare import ORAL_SMOKE_QUESTIONS
from app.eval.live_contract import (
    LIVE_FUNCTION_EXPECTED_TOTAL,
    LIVE_FUNCTION_SCRIPT_VERSION,
    checklist_hash,
)

BASE = "http://127.0.0.1:8002"
RAG = "http://127.0.0.1:8001"
TECH = {"X-API-Key": "demo-technician", "Content-Type": "application/json"}
CHIEF = {"X-API-Key": "demo-chief", "Content-Type": "application/json"}

# 顺序固定；增删检查项必须 bump LIVE_FUNCTION_SCRIPT_VERSION + EXPECTED_TOTAL
CHECK_NAMES = [
    "RAG :8001 health",
    "GET /health",
    "health.engine=langgraph",
    "health rag_mode live (when required)",
    "demo_mode_warning=false (live mode)",
    "RAG reachable via copilot health",
    "GET /policies",
    "GET /playbooks",
    "GET /roles/matrix",
    "POST playbooks/p6 → rejected",
    "P6 validation_passed",
    "POST playbooks/p1 → waiting_hitl",
    "P1 validation_passed",
    "GET /runs/{id}/trace",
    "HITL technician → 403",
    "HITL chief approve → succeeded",
    "HITL approve → rag_mock_inbox",
    "HITL approve → is_production_ticket=False",
    "POST playbooks/p4/validate",
    "POST playbooks/p2 → waiting_hitl",
    "POST playbooks/p4 → succeeded, no draft",
    "POST /runs oral (off-script)",
    "POST playbooks/p5b → waiting_hitl (rag_draft)",
    "POST /eval/compare",
    "POST /runs draft-driven (no parts_hints)",
    "POST /runs/{id}/cancel",
    "GET /docs (OpenAPI UI)",
    "GET /inbox",
    "RAG :8001 direct health",
]


def ok(name: str, cond: bool, detail: str = "") -> bool:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    return cond


def main() -> int:
    assert len(CHECK_NAMES) == LIVE_FUNCTION_EXPECTED_TOTAL, (
        f"CHECK_NAMES={len(CHECK_NAMES)} != EXPECTED={LIVE_FUNCTION_EXPECTED_TOTAL}"
    )
    results: list[bool] = []
    with httpx.Client(timeout=180.0) as c:
        try:
            rh = httpx.get(f"{RAG}/health", timeout=5.0)
            results.append(ok(CHECK_NAMES[0], rh.status_code == 200))
        except Exception as exc:
            results.append(ok(CHECK_NAMES[0], False, str(exc)))

        run_id = None
        try:
            h = c.get(f"{BASE}/health", headers=TECH)
            results.append(ok(CHECK_NAMES[1], h.status_code == 200))
            body = h.json() if h.status_code == 200 else {}
            results.append(ok(CHECK_NAMES[2], body.get("engine") == "langgraph"))
            results.append(
                ok(
                    CHECK_NAMES[3],
                    not body.get("live_linkage_required") or body.get("rag_mode") == "live",
                    f"rag_mode={body.get('rag_mode')}",
                )
            )
            results.append(
                ok(
                    CHECK_NAMES[4],
                    not body.get("demo_mode_warning"),
                    f"demo_mode_warning={body.get('demo_mode_warning')}",
                )
            )
            rag_block = body.get("rag") or {}
            rag_payload = rag_block.get("payload") or {}
            rag_reachable = (
                rag_block.get("ok") is True
                or rag_payload.get("status") in ("ok", "degraded")
                or body.get("rag_mode") == "live"
            )
            results.append(ok(CHECK_NAMES[5], rag_reachable, f"rag.ok={rag_block.get('ok')}"))
        except Exception as exc:
            results.extend([ok(CHECK_NAMES[i], False, str(exc)) for i in range(1, 6)])
            print("Copilot API 未启动，请先运行 start_copilot.cmd")
            return 1

        p = c.get(f"{BASE}/policies")
        results.append(ok(CHECK_NAMES[6], p.status_code == 200 and len(p.json().get("items") or []) >= 10))

        pb = c.get(f"{BASE}/playbooks", headers=TECH, params={"lane": "extended"})
        items = pb.json().get("items") or []
        results.append(ok(CHECK_NAMES[7], pb.status_code == 200 and len(items) >= 8))

        results.append(ok(CHECK_NAMES[8], c.get(f"{BASE}/roles/matrix").status_code == 200))

        r6 = c.post(f"{BASE}/playbooks/p6_chitchat/run", headers=TECH)
        results.append(ok(CHECK_NAMES[9], r6.status_code == 200 and r6.json().get("status") == "rejected"))
        meta6 = r6.json().get("playbook_meta") or {}
        results.append(ok(CHECK_NAMES[10], meta6.get("validation_passed") is True))

        r1 = c.post(f"{BASE}/playbooks/p1_xingsha_h103/run", headers=TECH)
        b1 = r1.json() if r1.status_code == 200 else {}
        run_id = b1.get("run_id")
        results.append(ok(CHECK_NAMES[11], r1.status_code == 200 and b1.get("status") == "waiting_hitl"))
        results.append(ok(CHECK_NAMES[12], (b1.get("playbook_meta") or {}).get("validation_passed") is True))

        if run_id:
            tr = c.get(f"{BASE}/runs/{run_id}/trace")
            nodes = [e["node"] for e in tr.json().get("events") or []]
            results.append(ok(CHECK_NAMES[13], tr.status_code == 200 and "hitl" in nodes))
        else:
            results.append(ok(CHECK_NAMES[13], False, "no run_id"))

        if run_id:
            bad = c.post(f"{BASE}/runs/{run_id}/hitl", headers=TECH, json={"decision": "approve", "note": "x"})
            results.append(ok(CHECK_NAMES[14], bad.status_code == 403))
        else:
            results.append(ok(CHECK_NAMES[14], False, "no run_id"))

        if run_id:
            pending = list((b1.get("hitl") or {}).get("pending_layers") or [])
            conf = {layer: True for layer in pending}
            good = c.post(
                f"{BASE}/runs/{run_id}/hitl",
                headers=CHIEF,
                json={"decision": "approve", "note": "站长确认", "confirmations": conf},
            )
            gb = good.json() if good.status_code == 200 else {}
            submit = gb.get("work_order_submit") or {}
            results.append(ok(CHECK_NAMES[15], good.status_code == 200 and gb.get("status") == "succeeded"))
            results.append(
                ok(
                    CHECK_NAMES[16],
                    submit.get("destination") == "rag_mock_inbox",
                    f"submit={submit.get('destination')}",
                )
            )
            results.append(
                ok(
                    CHECK_NAMES[17],
                    submit.get("is_production_ticket") is False,
                    f"is_production_ticket={submit.get('is_production_ticket')}",
                )
            )
        else:
            results.extend([ok(CHECK_NAMES[i], False, "no run_id") for i in (15, 16, 17)])

        v4 = c.post(f"{BASE}/playbooks/p4_manual_only/validate", headers=TECH)
        results.append(ok(CHECK_NAMES[18], v4.status_code == 200 and v4.json().get("passed") is True))

        p2 = c.post(f"{BASE}/playbooks/p2_warranty_conflict/run", headers=TECH)
        p2b = p2.json() if p2.status_code == 200 else {}
        p2_reasons = " ".join((p2b.get("hitl") or {}).get("reasons") or [])
        results.append(
            ok(
                CHECK_NAMES[19],
                p2.status_code == 200 and p2b.get("status") == "waiting_hitl" and "POL-CONFLICT-01" in p2_reasons,
                f"status={p2b.get('status')}",
            )
        )

        p4 = c.post(f"{BASE}/playbooks/p4_manual_only/run", headers=TECH)
        p4b = p4.json() if p4.status_code == 200 else {}
        results.append(
            ok(
                CHECK_NAMES[20],
                p4.status_code == 200
                and p4b.get("status") == "succeeded"
                and p4b.get("intent") == "knowledge_only"
                and not p4b.get("work_order_draft"),
                f"status={p4b.get('status')}",
            )
        )

        oral_q = ORAL_SMOKE_QUESTIONS[-1]
        oral = c.post(
            f"{BASE}/runs",
            headers=TECH,
            json={"question": oral_q, "station": "长沙星沙服务站"},
        )
        ob = oral.json() if oral.status_code == 200 else {}
        results.append(
            ok(
                CHECK_NAMES[21],
                oral.status_code == 200 and ob.get("intent") == "fault_dispatch",
                f"intent={ob.get('intent')}",
            )
        )

        p5b = c.post(f"{BASE}/playbooks/p5b_parts_from_draft/run", headers=TECH)
        p5bb = p5b.json() if p5b.status_code == 200 else {}
        p5b_parts = p5bb.get("parts_check") or {}
        results.append(
            ok(
                CHECK_NAMES[22],
                p5b.status_code == 200
                and p5bb.get("status") == "waiting_hitl"
                and p5b_parts.get("hints_source") == "rag_draft",
                f"status={p5bb.get('status')} hints_source={p5b_parts.get('hints_source')}",
            )
        )

        ev = c.post(f"{BASE}/eval/compare?engine=langgraph", headers=TECH)
        results.append(
            ok(
                CHECK_NAMES[23],
                ev.status_code == 200 and ev.json().get("summary", {}).get("engine") == "langgraph",
            )
        )

        mr = c.post(
            f"{BASE}/runs",
            headers=TECH,
            json={
                "question": "长沙星沙 SY215C H103请报修处理",
                "station": "长沙星沙服务站",
            },
        )
        mrb = mr.json() if mr.status_code == 200 else {}
        linkage = mrb.get("rag_linkage") or []
        results.append(
            ok(
                CHECK_NAMES[24],
                mr.status_code == 200
                and mrb.get("status") in {"waiting_hitl", "succeeded"}
                and "ask" in linkage
                and (mrb.get("parts_check") or {}).get("needed") is not False,
                f"status={mrb.get('status')} linkage={'→'.join(linkage)}",
            )
        )

        cid = mrb.get("run_id")
        if cid:
            cn = c.post(f"{BASE}/runs/{cid}/cancel", headers=CHIEF)
            results.append(ok(CHECK_NAMES[25], cn.status_code == 200 and cn.json().get("status") == "cancelled"))
        else:
            results.append(ok(CHECK_NAMES[25], False, "no run_id"))

        docs = c.get(f"{BASE}/docs")
        results.append(ok(CHECK_NAMES[26], docs.status_code == 200))

        try:
            inbox = c.get(f"{BASE}/inbox?limit=3", headers=CHIEF)
            results.append(ok(CHECK_NAMES[27], inbox.status_code == 200))
        except Exception as exc:
            results.append(ok(CHECK_NAMES[27], False, str(exc)))

        try:
            rh2 = c.get(f"{RAG}/health", timeout=10.0)
            results.append(ok(CHECK_NAMES[28], rh2.status_code == 200))
        except Exception as exc:
            results.append(ok(CHECK_NAMES[28], False, str(exc)))

    if len(results) != LIVE_FUNCTION_EXPECTED_TOTAL:
        print(
            f"\n[FAIL] result count {len(results)} != expected {LIVE_FUNCTION_EXPECTED_TOTAL} "
            f"(script_version={LIVE_FUNCTION_SCRIPT_VERSION})"
        )
        return 1

    passed = sum(results)
    total = len(results)
    chash = checklist_hash(CHECK_NAMES)
    print(f"\n=== {passed}/{total} passed · script_version={LIVE_FUNCTION_SCRIPT_VERSION} · hash={chash} ===")
    report = {
        "script_version": LIVE_FUNCTION_SCRIPT_VERSION,
        "checklist_hash": chash,
        "expected_total": LIVE_FUNCTION_EXPECTED_TOTAL,
        "passed": passed,
        "total": total,
        "all_ok": passed == total,
        "oral_question": ORAL_SMOKE_QUESTIONS[-1],
        "mock_submit": {
            "destination": "rag_mock_inbox",
            "is_production_ticket": False,
        },
    }
    out = ROOT / "data" / "eval" / "live_function_test.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
