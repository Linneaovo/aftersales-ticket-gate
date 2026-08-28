"""Direct live HTTP integration checks (no FakeRag, no pytest skipif)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx

from app.eval.compare import ORAL_SMOKE_QUESTIONS

COP = "http://127.0.0.1:8002"
RAG = "http://127.0.0.1:8001"
TECH = {"X-API-Key": "demo-technician", "Content-Type": "application/json"}
CHIEF = {"X-API-Key": "demo-chief", "Content-Type": "application/json"}
PARTS = {"X-API-Key": "demo-parts", "Content-Type": "application/json"}
TIMEOUT = 180.0

# 剧本外答辩口语（清单第 8 条）
LIVE_ORAL_QUESTION = ORAL_SMOKE_QUESTIONS[-1]


def check(name: str, cond: bool, detail: str = "") -> bool:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    return cond


def main() -> int:
    results: list[bool] = []

    rag = httpx.get(f"{RAG}/health", timeout=10.0)
    results.append(check("RAG :8001 health", rag.status_code == 200))

    health = httpx.get(f"{COP}/health", headers=TECH, timeout=30.0).json()
    results.append(check("Copilot rag_mode=live", health.get("rag_mode") == "live", str(health.get("rag_mode"))))
    results.append(check("Copilot engine=langgraph", health.get("engine") == "langgraph"))

    shortage = httpx.post(
        f"{COP}/runs",
        headers=TECH,
        json={
            "question": "长沙星沙 SY215C H103请报修处理",
            "parts_hints": ["液压泵总成"],
            "station": "长沙星沙服务站",
        },
        timeout=TIMEOUT,
    )
    sb = shortage.json()
    results.append(
        check(
            "POST /runs shortage → waiting_hitl (live)",
            shortage.status_code == 200
            and sb.get("status") == "waiting_hitl"
            and sb.get("rag_client_mode") == "live",
            f"status={sb.get('status')}",
        )
    )

    low = httpx.post(
        f"{COP}/runs",
        headers=TECH,
        json={
            "question": "长沙星沙 SY215C H103请报修处理",
            "parts_hints": ["液压滤芯"],
            "station": "长沙星沙服务站",
        },
        timeout=TIMEOUT,
    )
    lb = low.json()
    results.append(
        check(
            "POST /runs low-risk → succeeded (live)",
            low.status_code == 200
            and lb.get("status") == "succeeded"
            and lb.get("work_order_state") == "ready_for_chief",
            f"status={lb.get('status')}",
        )
    )

    p2 = httpx.post(f"{COP}/playbooks/p2_warranty_conflict/run", headers=TECH, timeout=TIMEOUT)
    p2b = p2.json()
    p2_reasons = " ".join((p2b.get("hitl") or {}).get("reasons") or [])
    critic = p2b.get("critic_report") or {}
    results.append(
        check(
            "P2 conflict → waiting_hitl",
            p2.status_code == 200 and p2b.get("status") == "waiting_hitl" and "POL-CONFLICT-01" in p2_reasons,
            f"status={p2b.get('status')} policy_ids={critic.get('policy_ids')}",
        )
    )

    p4 = httpx.post(f"{COP}/playbooks/p4_manual_only/run", headers=TECH, timeout=TIMEOUT)
    p4b = p4.json()
    results.append(
        check(
            "P4 knowledge_only → succeeded, no draft",
            p4.status_code == 200
            and p4b.get("status") == "succeeded"
            and p4b.get("intent") == "knowledge_only"
            and not p4b.get("work_order_draft"),
            f"status={p4b.get('status')} draft={bool(p4b.get('work_order_draft'))}",
        )
    )

    oral = httpx.post(
        f"{COP}/runs",
        headers=TECH,
        json={"question": LIVE_ORAL_QUESTION, "station": "长沙星沙服务站"},
        timeout=TIMEOUT,
    )
    ob = oral.json()
    results.append(
        check(
            "Live oral (off-script) → fault_dispatch",
            oral.status_code == 200 and ob.get("intent") == "fault_dispatch",
            f"intent={ob.get('intent')} q={LIVE_ORAL_QUESTION[:40]}…",
        )
    )

    p8 = httpx.post(f"{COP}/playbooks/p8_parts_clerk_conflict/run", headers=PARTS, timeout=TIMEOUT)
    p8b = p8.json()
    p8_reasons = " ".join((p8b.get("hitl") or {}).get("reasons") or [])
    results.append(
        check(
            "P8 parts clerk conflict → waiting_hitl",
            p8.status_code == 200 and p8b.get("status") == "waiting_hitl" and "POL-CONFLICT-01" in p8_reasons,
            p8b.get("status"),
        )
    )

    p1 = httpx.post(f"{COP}/playbooks/p1_xingsha_h103/run", headers=TECH, timeout=TIMEOUT)
    p1b = p1.json()
    run_id = p1b.get("run_id")
    approve = httpx.post(
        f"{COP}/runs/{run_id}/hitl",
        headers=CHIEF,
        json={"decision": "approve", "note": "站长确认"},
        timeout=TIMEOUT,
    )
    ab = approve.json()
    submit = ab.get("work_order_submit") or {}
    results.append(
        check(
            "P1 chief approve → rag_mock_inbox",
            approve.status_code == 200
            and ab.get("status") == "succeeded"
            and submit.get("destination") == "rag_mock_inbox",
            submit.get("destination"),
        )
    )

    passed = sum(results)
    total = len(results)
    print(f"\n=== LIVE MANUAL INTEGRATION {passed}/{total} ===")
    report = {
        "passed": passed,
        "total": total,
        "all_ok": passed == total,
        "oral_question": LIVE_ORAL_QUESTION,
    }
    out = ROOT / "data" / "eval" / "live_integration_manual.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
