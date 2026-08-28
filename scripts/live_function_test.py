"""Live 功能全量冒烟（需 Copilot :8002；RAG :8001 可选）。

用法：
  python scripts/live_function_test.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx

from app.eval.compare import ORAL_SMOKE_QUESTIONS

BASE = "http://127.0.0.1:8002"
RAG = "http://127.0.0.1:8001"
TECH = {"X-API-Key": "demo-technician", "Content-Type": "application/json"}
CHIEF = {"X-API-Key": "demo-chief", "Content-Type": "application/json"}


def ok(name: str, cond: bool, detail: str = "") -> bool:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    return cond


def main() -> int:
    results: list[bool] = []
    with httpx.Client(timeout=180.0) as c:
        # 0. RAG health (optional but recommended for live demo)
        try:
            rh = httpx.get(f"{RAG}/health", timeout=5.0)
            results.append(ok("RAG :8001 health", rh.status_code == 200))
        except Exception as exc:
            results.append(ok("RAG :8001 health", False, str(exc)))

        # 1. Health
        try:
            h = c.get(f"{BASE}/health", headers=TECH)
            results.append(ok("GET /health", h.status_code == 200))
            body = h.json()
            results.append(ok("health.engine=langgraph", body.get("engine") == "langgraph"))
            results.append(
                ok(
                    "health rag_mode live (when required)",
                    not body.get("live_linkage_required") or body.get("rag_mode") == "live",
                    f"rag_mode={body.get('rag_mode')}",
                )
            )
            results.append(
                ok(
                    "demo_mode_warning=false (答辩配置)",
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
            results.append(
                ok("RAG reachable via copilot health", rag_reachable, f"rag.ok={rag_block.get('ok')}")
            )
        except Exception as exc:
            results.append(ok("GET /health", False, str(exc)))
            print("Copilot API 未启动，请先运行 start_copilot.cmd")
            return 1

        # 2. Policies
        p = c.get(f"{BASE}/policies")
        results.append(ok("GET /policies", p.status_code == 200 and len(p.json().get("items") or []) >= 10))

        # 3. Playbooks list
        pb = c.get(f"{BASE}/playbooks", headers=TECH)
        items = pb.json().get("items") or []
        results.append(ok("GET /playbooks", pb.status_code == 200 and len(items) >= 8))

        # 4. Roles
        results.append(ok("GET /roles/matrix", c.get(f"{BASE}/roles/matrix").status_code == 200))

        # 5. P6 chitchat reject
        r6 = c.post(f"{BASE}/playbooks/p6_chitchat/run", headers=TECH)
        results.append(ok("POST playbooks/p6 → rejected", r6.status_code == 200 and r6.json().get("status") == "rejected"))
        meta6 = r6.json().get("playbook_meta") or {}
        results.append(ok("P6 validation_passed", meta6.get("validation_passed") is True))

        # 6. P1 fault dispatch → HITL
        r1 = c.post(f"{BASE}/playbooks/p1_xingsha_h103/run", headers=TECH)
        b1 = r1.json()
        run_id = b1.get("run_id")
        results.append(ok("POST playbooks/p1 → waiting_hitl", r1.status_code == 200 and b1.get("status") == "waiting_hitl"))
        results.append(ok("P1 validation_passed", (b1.get("playbook_meta") or {}).get("validation_passed") is True))

        # 7. Trace
        if run_id:
            tr = c.get(f"{BASE}/runs/{run_id}/trace")
            nodes = [e["node"] for e in tr.json().get("events") or []]
            results.append(ok("GET /runs/{id}/trace", tr.status_code == 200 and "hitl" in nodes))

        # 8. HITL 403 technician
        if run_id:
            bad = c.post(f"{BASE}/runs/{run_id}/hitl", headers=TECH, json={"decision": "approve", "note": "x"})
            results.append(ok("HITL technician → 403", bad.status_code == 403))

        # 9. HITL approve chief → mock inbox submit（即使 playbook auto_submit=false）
        if run_id:
            good = c.post(f"{BASE}/runs/{run_id}/hitl", headers=CHIEF, json={"decision": "approve", "note": "站长确认"})
            gb = good.json() if good.status_code == 200 else {}
            results.append(ok("HITL chief approve → succeeded", good.status_code == 200 and gb.get("status") == "succeeded"))
            submit = gb.get("work_order_submit") or {}
            results.append(
                ok(
                    "HITL approve → work_order_submit.destination",
                    submit.get("destination") == "rag_mock_inbox",
                    f"submit={submit.get('destination')}",
                )
            )

        # 10. Validate endpoint
        v4 = c.post(f"{BASE}/playbooks/p4_manual_only/validate", headers=TECH)
        results.append(ok("POST playbooks/p4/validate", v4.status_code == 200 and v4.json().get("passed") is True))

        # 10b. P2 conflict live
        p2 = c.post(f"{BASE}/playbooks/p2_warranty_conflict/run", headers=TECH)
        p2b = p2.json()
        p2_reasons = " ".join((p2b.get("hitl") or {}).get("reasons") or [])
        results.append(
            ok(
                "POST playbooks/p2 → waiting_hitl",
                p2.status_code == 200 and p2b.get("status") == "waiting_hitl" and "POL-CONFLICT-01" in p2_reasons,
                f"status={p2b.get('status')}",
            )
        )

        # 10c. P4 run live (非仅 validate)
        p4 = c.post(f"{BASE}/playbooks/p4_manual_only/run", headers=TECH)
        p4b = p4.json()
        results.append(
            ok(
                "POST playbooks/p4 → succeeded, no draft",
                p4.status_code == 200
                and p4b.get("status") == "succeeded"
                and p4b.get("intent") == "knowledge_only"
                and not p4b.get("work_order_draft"),
                f"status={p4b.get('status')}",
            )
        )

        # 10d. 剧本外长沙口语
        oral_q = ORAL_SMOKE_QUESTIONS[-1]
        oral = c.post(
            f"{BASE}/runs",
            headers=TECH,
            json={"question": oral_q, "station": "长沙星沙服务站"},
        )
        ob = oral.json()
        results.append(
            ok(
                "POST /runs oral (off-script)",
                oral.status_code == 200 and ob.get("intent") == "fault_dispatch",
                f"intent={ob.get('intent')}",
            )
        )

        # 11. Eval compare
        ev = c.post(f"{BASE}/eval/compare?engine=langgraph", headers=TECH)
        results.append(ok("POST /eval/compare", ev.status_code == 200 and ev.json().get("summary", {}).get("engine") == "langgraph"))

        # 12. Manual run
        mr = c.post(
            f"{BASE}/runs",
            headers=TECH,
            json={
                "question": "长沙星沙 SY215C H103请报修处理",
                "parts_hints": ["液压泵总成"],
                "station": "长沙星沙服务站",
            },
        )
        results.append(ok("POST /runs manual", mr.status_code == 200 and mr.json().get("status") == "waiting_hitl"))

        # 13. Cancel
        cid = mr.json().get("run_id")
        if cid:
            cn = c.post(f"{BASE}/runs/{cid}/cancel", headers=CHIEF)
            results.append(ok("POST /runs/{id}/cancel", cn.status_code == 200 and cn.json().get("status") == "cancelled"))

        # 14. OpenAPI docs
        docs = c.get(f"{BASE}/docs")
        results.append(ok("GET /docs (OpenAPI UI)", docs.status_code == 200))

        # 15. Inbox (RAG)
        try:
            inbox = c.get(f"{BASE}/inbox?limit=3", headers=CHIEF)
            results.append(ok("GET /inbox", inbox.status_code == 200))
        except Exception as exc:
            results.append(ok("GET /inbox", False, str(exc)))

        # 16. RAG direct
        try:
            rh = c.get(f"{RAG}/health", timeout=10.0)
            results.append(ok("RAG :8001 direct health", rh.status_code == 200))
        except Exception as exc:
            results.append(ok("RAG :8001 direct health", False, str(exc)))

    passed = sum(results)
    total = len(results)
    print(f"\n=== {passed}/{total} passed ===")
    report = {
        "passed": passed,
        "total": total,
        "all_ok": passed == total,
        "oral_question": ORAL_SMOKE_QUESTIONS[-1],
    }
    out = ROOT / "data" / "eval" / "live_function_test.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
