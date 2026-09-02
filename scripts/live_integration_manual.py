"""Direct live HTTP integration checks (no FakeRag, no pytest skipif).

Portfolio：data/eval/live_integration_manual.json（含 script_version / checklist_hash）。
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
    LIVE_MANUAL_EXPECTED_TOTAL,
    LIVE_MANUAL_SCRIPT_VERSION,
    checklist_hash,
)

COP = "http://127.0.0.1:8002"
RAG = "http://127.0.0.1:8001"
TECH = {"X-API-Key": "demo-technician", "Content-Type": "application/json"}
CHIEF = {"X-API-Key": "demo-chief", "Content-Type": "application/json"}
PARTS = {"X-API-Key": "demo-parts", "Content-Type": "application/json"}
TIMEOUT = 180.0

LIVE_ORAL_QUESTION = ORAL_SMOKE_QUESTIONS[-1]

CHECK_NAMES = [
    "RAG :8001 health",
    "Copilot rag_mode=live",
    "Copilot engine=langgraph",
    "P1 playbook → waiting_hitl (POL-PARTS-01)",
    "P1b 有库存 → succeeded (live)",
    "P2 conflict → waiting_hitl",
    "P4 knowledge_only → succeeded, no draft",
    "POST /runs oral (no parts_hints) → fault_dispatch",
    "P8 parts clerk conflict → waiting_hitl",
    "P1 chief approve → rag_mock_inbox + not production",
    "GET /inbox contains submitted ticket",
]


def check(name: str, cond: bool, detail: str = "") -> bool:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    return cond


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Live integration manual checks")
    parser.add_argument(
        "--require-submit-token",
        action="store_true",
        help="额外要求 RAG 硬门已开，并调用 demo_strict_submit_check（须先重启 :8001）",
    )
    args = parser.parse_args()

    assert len(CHECK_NAMES) == LIVE_MANUAL_EXPECTED_TOTAL, (
        f"CHECK_NAMES={len(CHECK_NAMES)} != EXPECTED={LIVE_MANUAL_EXPECTED_TOTAL}"
    )
    results: list[bool] = []

    try:
        rag = httpx.get(f"{RAG}/health", timeout=10.0)
        results.append(check(CHECK_NAMES[0], rag.status_code == 200))
    except Exception as exc:
        results.append(check(CHECK_NAMES[0], False, str(exc)))
        return 1

    health = httpx.get(f"{COP}/health", headers=TECH, timeout=30.0).json()
    results.append(check(CHECK_NAMES[1], health.get("rag_mode") == "live", str(health.get("rag_mode"))))
    results.append(check(CHECK_NAMES[2], health.get("engine") == "langgraph"))

    p1 = httpx.post(f"{COP}/playbooks/p1_xingsha_h103/run", headers=TECH, timeout=TIMEOUT)
    p1b = p1.json() if p1.status_code == 200 else {}
    p1_reasons = " ".join((p1b.get("hitl") or {}).get("reasons") or [])
    run_id = p1b.get("run_id")
    results.append(
        check(
            CHECK_NAMES[3],
            p1.status_code == 200
            and p1b.get("status") == "waiting_hitl"
            and p1b.get("rag_client_mode") == "live"
            and "POL-PARTS-01" in p1_reasons,
            f"status={p1b.get('status')} reasons={p1_reasons[:80]}",
        )
    )

    low = httpx.post(
        f"{COP}/playbooks/p1b_no_shortage_ready/run",
        headers=TECH,
        timeout=TIMEOUT,
    )
    lb = low.json() if low.status_code == 200 else {}
    results.append(
        check(
            CHECK_NAMES[4],
            low.status_code == 200
            and lb.get("status") == "succeeded"
            and lb.get("work_order_state") == "ready_for_chief",
            f"status={lb.get('status')}",
        )
    )

    p2 = httpx.post(f"{COP}/playbooks/p2_warranty_conflict/run", headers=TECH, timeout=TIMEOUT)
    p2b = p2.json() if p2.status_code == 200 else {}
    p2_reasons = " ".join((p2b.get("hitl") or {}).get("reasons") or [])
    critic = p2b.get("critic_report") or {}
    results.append(
        check(
            CHECK_NAMES[5],
            p2.status_code == 200 and p2b.get("status") == "waiting_hitl" and "POL-CONFLICT-01" in p2_reasons,
            f"status={p2b.get('status')} policy_ids={critic.get('policy_ids')}",
        )
    )

    p4 = httpx.post(f"{COP}/playbooks/p4_manual_only/run", headers=TECH, timeout=TIMEOUT)
    p4b = p4.json() if p4.status_code == 200 else {}
    results.append(
        check(
            CHECK_NAMES[6],
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
    ob = oral.json() if oral.status_code == 200 else {}
    results.append(
        check(
            CHECK_NAMES[7],
            oral.status_code == 200 and ob.get("intent") == "fault_dispatch",
            f"intent={ob.get('intent')} q={LIVE_ORAL_QUESTION[:40]}…",
        )
    )

    p8 = httpx.post(f"{COP}/playbooks/p8_parts_clerk_conflict/run", headers=PARTS, timeout=TIMEOUT)
    p8b = p8.json() if p8.status_code == 200 else {}
    p8_reasons = " ".join((p8b.get("hitl") or {}).get("reasons") or [])
    results.append(
        check(
            CHECK_NAMES[8],
            p8.status_code == 200 and p8b.get("status") == "waiting_hitl" and "POL-CONFLICT-01" in p8_reasons,
            p8b.get("status"),
        )
    )

    ticket_id = None
    if run_id:
        pending = list((p1b.get("hitl") or {}).get("pending_layers") or [])
        conf = {layer: True for layer in pending}
        approve = httpx.post(
            f"{COP}/runs/{run_id}/hitl",
            headers=CHIEF,
            json={"decision": "approve", "note": "站长确认", "confirmations": conf},
            timeout=TIMEOUT,
        )
        ab = approve.json() if approve.status_code == 200 else {}
        submit = ab.get("work_order_submit") or {}
        ticket_id = submit.get("ticket_id") or submit.get("id")
        results.append(
            check(
                CHECK_NAMES[9],
                approve.status_code == 200
                and ab.get("status") == "succeeded"
                and submit.get("destination") == "rag_mock_inbox"
                and submit.get("is_production_ticket") is False
                and submit.get("source") == "copilot_hitl"
                and bool(submit.get("run_id") or run_id),
                f"dest={submit.get('destination')} prod={submit.get('is_production_ticket')} "
                f"source={submit.get('source')} run_id={submit.get('run_id') or run_id}",
            )
        )
    else:
        results.append(check(CHECK_NAMES[9], False, "no run_id"))

    if ticket_id:
        inbox = httpx.get(f"{COP}/inbox?limit=5", headers=CHIEF, timeout=TIMEOUT)
        inbox_ids = [
            str(t.get("ticket_id") or t.get("id") or "")
            for t in (inbox.json().get("items") or inbox.json().get("tickets") or [])
        ]
        # E4 L2：RAG 详情须持久化 source（不读 note）
        rag_detail = httpx.get(
            f"{RAG}/work-orders/inbox/{ticket_id}",
            headers={"X-API-Key": "demo-key"},
            timeout=TIMEOUT,
        )
        rag_src = (rag_detail.json() or {}).get("source") if rag_detail.status_code == 200 else None
        rag_run = (rag_detail.json() or {}).get("run_id") if rag_detail.status_code == 200 else None
        results.append(
            check(
                CHECK_NAMES[10],
                inbox.status_code == 200
                and str(ticket_id) in inbox_ids
                and rag_detail.status_code == 200
                and rag_src == "copilot_hitl"
                and bool(rag_run),
                f"ticket_id={ticket_id} rag_source={rag_src} rag_run_id={rag_run}",
            )
        )
    else:
        results.append(check(CHECK_NAMES[10], False, "no ticket_id"))

    if len(results) != LIVE_MANUAL_EXPECTED_TOTAL:
        print(
            f"\n[FAIL] result count {len(results)} != expected {LIVE_MANUAL_EXPECTED_TOTAL} "
            f"(script_version={LIVE_MANUAL_SCRIPT_VERSION})"
        )
        return 1

    passed = sum(results)
    total = len(results)
    chash = checklist_hash(CHECK_NAMES)
    print(f"\n=== LIVE MANUAL INTEGRATION {passed}/{total} · {LIVE_MANUAL_SCRIPT_VERSION} · {chash} ===")
    report = {
        "script_version": LIVE_MANUAL_SCRIPT_VERSION,
        "checklist_hash": chash,
        "expected_total": LIVE_MANUAL_EXPECTED_TOTAL,
        "passed": passed,
        "total": total,
        "all_ok": passed == total,
        "oral_question": LIVE_ORAL_QUESTION,
        "mock_submit": {
            "destination": "rag_mock_inbox",
            "is_production_ticket": False,
        },
    }
    out = ROOT / "data" / "eval" / "live_integration_manual.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    rc = 0 if passed == total else 1
    if args.require_submit_token:
        import runpy

        print("\n--- --require-submit-token → demo_strict_submit_check ---")
        # 硬门未开时脚本 skip 并 exit 0；此处要求必须 all_ok
        try:
            runpy.run_path(str(ROOT / "scripts" / "demo_strict_submit_check.py"), run_name="__main__")
            strict_rc = 0
        except SystemExit as exc:
            strict_rc = int(exc.code or 0)
        strict_path = ROOT / "data" / "eval" / "demo_strict_submit_check.json"
        strict = json.loads(strict_path.read_text(encoding="utf-8")) if strict_path.exists() else {}
        if strict.get("skipped"):
            print("[FAIL] --require-submit-token 但 RAG 硬门未开；见 demo_strict_submit.env.example")
            return 1
        if strict_rc != 0 or not strict.get("all_ok"):
            return 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
