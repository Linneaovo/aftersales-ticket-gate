"""真连 enterprise-rag 冒烟（不修改 RAG 代码）。

用法（RAG 已在 :8001）：
  .\\.venv\\Scripts\\python.exe scripts\\smoke_with_rag.py
  .\\.venv\\Scripts\\python.exe scripts\\smoke_with_rag.py --engine langgraph
  .\\.venv\\Scripts\\python.exe scripts\\smoke_with_rag.py --compare-live
  .\\.venv\\Scripts\\python.exe scripts\\smoke_with_rag.py --offline
  .\\.venv\\Scripts\\python.exe scripts\\smoke_with_rag.py --report data/eval/smoke_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.domain.station import load_station_profile
from app.eval.compare import ORAL_SMOKE_QUESTIONS, compare_cases
from app.graph.nodes import classify_intent
from app.graph.runner import apply_hitl
from app.playbooks.runner import run_playbook_from_data, validate_playbook_result
from app.playbooks.validate import load_playbook
from app.tools.demo_rag import DemoRagClient
from app.tools.rag_client import RagClient, RagToolError, summarize_rag_health

DEMO_DOCS = tuple(load_station_profile().get("demo_corpus_hints") or [])

PLAYBOOK_IDS = [
    "p1_xingsha_h103",
    "p2_warranty_conflict",
    "p3_acl_salary",
    "p4_manual_only",
    "p5_parts_shortage",
    "p6_chitchat",
    "p7_second_visit_shortage",
    "p8_parts_clerk_conflict",
]

LIVE_COMPARE_IDS = ["B01", "B02", "B05", "B07", "B10"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Live RAG smoke for P1–P7 playbooks")
    parser.add_argument(
        "--engine",
        choices=("fallback", "langgraph"),
        default="langgraph",
        help="execution engine (default: langgraph, same as POST /runs)",
    )
    parser.add_argument(
        "--report",
        default=str(ROOT / "data" / "eval" / "smoke_report.json"),
        help="structured JSON report path",
    )
    parser.add_argument(
        "--compare-live",
        action="store_true",
        help="append live A-07 compare samples to report appendix",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="offline baseline with DemoRag (no :8001); for committed smoke_report.json",
    )
    args = parser.parse_args()

    if args.offline:
        client = DemoRagClient()
        report: dict = {
            "mode": "offline_baseline",
            "engine": args.engine,
            "health": {"ok": True, "mode": "demo_offline", "note": "DemoRag — regenerate with live RAG for demo"},
            "cases": [],
            "passed": False,
        }
        print("== offline baseline (DemoRag) ==")
        all_pass = _run_playbook_cases(args, client, report)
        oral_results = _run_oral_intent_smoke()
        report["oral_intent"] = oral_results
        if not all(r["passed"] for r in oral_results):
            all_pass = False
        cmp_report = compare_cases(live_rag=False, engine=args.engine)
        appendix = [c for c in cmp_report.get("comparisons") or [] if c.get("id") in LIVE_COMPARE_IDS]
        report["live_compare_appendix"] = {
            "mode": "offline_fake_rag",
            "summary": cmp_report.get("summary"),
            "samples": appendix,
        }
        report["passed"] = all_pass
        _write_report(args.report, report)
        print("OFFLINE BASELINE", "PASS" if all_pass else "FAIL", "— see", args.report)
        return 0 if all_pass else 1

    client = RagClient(api_key="demo-technician")
    report: dict = {
        "mode": "live",
        "engine": args.engine,
        "health": {},
        "cases": [],
        "passed": False,
    }

    print("== copilot health (live gate) ==")
    try:
        import httpx

        ch = httpx.get("http://127.0.0.1:8002/health", timeout=10.0)
        if ch.status_code == 200:
            cb = ch.json()
            print(f"copilot rag_mode={cb.get('rag_mode')} demo_warn={cb.get('demo_mode_warning')}")
            if cb.get("live_linkage_required") and cb.get("rag_mode") != "live":
                print("FAIL: live_linkage_required but rag_mode!=live — copy .env.demo .env")
                report["health"] = {"ok": False, "copilot": cb}
                _write_report(args.report, report)
                return 1
    except Exception as exc:
        print("WARN: copilot health skip:", exc)

    print("== health ==")
    try:
        health = client.health()
    except RagToolError as exc:
        print("FAIL: RAG unreachable:", exc)
        report["health"] = {"ok": False, "error": str(exc)}
        _write_report(args.report, report)
        return 1

    summary = summarize_rag_health(health if isinstance(health, dict) else {})
    report["health"] = summary
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary.get("degraded"):
        print("WARN: RAG degraded — 继续跑剧本，但建议关 auto_submit")

    all_pass = _run_playbook_cases(args, client, report)

    oral_results = _run_oral_intent_smoke()
    report["oral_intent"] = oral_results
    for r in oral_results:
        if not r["passed"]:
            all_pass = False

    if args.compare_live:
        print("== live compare appendix ==")
        try:
            cmp_report = compare_cases(live_rag=True, engine=args.engine)
            appendix = [c for c in cmp_report.get("comparisons") or [] if c.get("id") in LIVE_COMPARE_IDS]
            report["live_compare_appendix"] = {
                "summary": cmp_report.get("summary"),
                "samples": appendix,
            }
            print(f"live compare samples={len(appendix)} delta_miss_hitl=", cmp_report.get("summary", {}).get("delta_miss_hitl"))
        except Exception as exc:  # noqa: BLE001
            report["live_compare_appendix"] = {"error": str(exc)}
            print("live compare skip:", exc)

    report["passed"] = all_pass
    _write_report(args.report, report)
    if all_pass:
        print("SMOKE PASS")
        return 0
    print("SMOKE FAIL — see", args.report)
    return 1


def _run_oral_intent_smoke() -> list[dict]:
    print("== oral intent smoke ==")
    oral_results = []
    for q in ORAL_SMOKE_QUESTIONS:
        intent = classify_intent(q)
        ok = intent == "fault_dispatch"
        oral_results.append({"question": q, "intent": intent, "passed": ok})
        print(f"{'PASS' if ok else 'FAIL'}: {q} -> {intent}")
    return oral_results


def _run_playbook_cases(args: argparse.Namespace, default_client: Any, report: dict) -> bool:
    all_pass = True
    for playbook_id in PLAYBOOK_IDS:
        data = load_playbook(playbook_id)
        print(f"== {playbook_id} engine={args.engine} ==")
        key = str(data.get("api_key") or "demo-technician")
        rag_client = default_client if isinstance(default_client, DemoRagClient) else RagClient(api_key=key)
        case_report: dict = {"playbook_id": playbook_id, "passed": False, "diffs": []}

        try:
            out = run_playbook_from_data(data, client=rag_client, engine=args.engine, persist=not args.offline)
            validation = validate_playbook_result(data, out)
            case_report["validation"] = validation
            case_report["actual"] = validation.get("actual")
            case_report["diffs"] = validation.get("diffs") or []
            case_report["passed"] = validation.get("passed", False)
            case_report["status"] = out.get("status")
            case_report["intent"] = out.get("intent")
            case_report["linkage"] = out.get("rag_linkage")
            case_report["linkage_detail"] = out.get("rag_linkage_detail")
            case_report["trace_nodes"] = [e.get("node") for e in (out.get("trace_events") or [])]
            linkage = list(out.get("rag_linkage") or [])
            if not args.offline and playbook_id in {"p1_xingsha_h103", "p2_warranty_conflict", "p5_parts_shortage"}:
                if len(linkage) < 2:
                    case_report["passed"] = False
                    all_pass = False
                    case_report["diffs"] = (case_report.get("diffs") or []) + [
                        {"field": "rag_linkage", "expect": ">=2 apis", "actual": linkage}
                    ]
                    print("FAIL: rag_linkage too short", linkage)

            print("status=", out.get("status"), "intent=", out.get("intent"))
            print("linkage=", out.get("rag_linkage"))
            if not case_report["passed"]:
                all_pass = False
                print("FAIL diffs:", json.dumps(case_report["diffs"], ensure_ascii=False))
            else:
                print("PASS")

            if playbook_id == "p1_xingsha_h103" and case_report["passed"]:
                sources = (out.get("rag_result") or {}).get("sources") or []
                names = []
                for s in sources:
                    if isinstance(s, dict):
                        names.append(str(((s.get("chunk") or {}).get("source")) or s.get("source") or ""))
                joined = " ".join(names)
                if DEMO_DOCS and any(h in joined for h in DEMO_DOCS):
                    print("citations ok (demo-kb corpus hint matched)")
                elif not args.offline:
                    print("WARN: citations 未命中 profile 提示名:", names[:3])
                out2 = apply_hitl(
                    out,
                    "approve",
                    "星沙站长确认",
                    client=rag_client,
                    persist=not args.offline,
                    approver_api_key="demo-chief",
                )
                case_report["after_chief_approve"] = {
                    "status": out2.get("status"),
                    "submit_eligible": out2.get("submit_eligible"),
                }
                print("after chief approve:", out2.get("status"), "submit_eligible=", out2.get("submit_eligible"))
                if not args.offline:
                    try:
                        inbox = RagClient(api_key="demo-chief").list_inbox(limit=3)
                        case_report["inbox_count"] = inbox.get("count") or len(inbox.get("items") or [])
                        print("inbox count=", case_report["inbox_count"])
                    except RagToolError as exc:
                        case_report["inbox_error"] = str(exc)
                        print("inbox skip:", exc)

        except Exception as exc:  # noqa: BLE001
            all_pass = False
            case_report["error"] = str(exc)
            print("ERROR:", exc)

        report["cases"].append(case_report)
    return all_pass


def _write_report(path: str, report: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
