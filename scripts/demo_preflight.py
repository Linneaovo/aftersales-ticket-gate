"""答辩/面试前预检：确认 live 联调、持久化卫生。

用法：
  python scripts\\demo_preflight.py
  python scripts\\demo_preflight.py --require-rag
  python scripts\\demo_preflight.py --require-rag --smoke-run
  python scripts\\demo_preflight.py --reset
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8002"
RAG_BASE = "http://127.0.0.1:8001"
TECH_HEADERS = {"X-API-Key": "demo-technician", "Content-Type": "application/json"}


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}")
    sys.exit(1)


def ok(msg: str) -> None:
    print(f"[OK] {msg}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Demo preflight for live RAG linkage")
    parser.add_argument("--reset", action="store_true", help="run reset_demo_state before checks")
    parser.add_argument("--base", default=BASE)
    parser.add_argument("--require-rag", action="store_true", help="also check enterprise-rag :8001")
    parser.add_argument("--rag-base", default=RAG_BASE)
    parser.add_argument(
        "--smoke-run",
        action="store_true",
        help="POST /runs 低危用例，断言 rag_client_mode=live 且 rag_linkage 含 ask",
    )
    args = parser.parse_args()

    if args.reset:
        sys.path.insert(0, str(ROOT))
        from app.tracing.store import repair_persistence, reset_all_persistence

        report = reset_all_persistence()
        repair = repair_persistence(dry_run=False)
        print(json.dumps({"reset": report, "repair": repair}, ensure_ascii=False, indent=2))
        ok("reset_demo_state complete")

    print("== demo preflight ==")
    if args.require_rag:
        try:
            with httpx.Client(timeout=10.0) as rc:
                rh = rc.get(f"{args.rag_base.rstrip('/')}/health")
            if rh.status_code != 200:
                fail(f"RAG 不可达 ({args.rag_base}) HTTP {rh.status_code}")
            ok("RAG :8001 health 200")
        except Exception as exc:
            fail(f"RAG 不可达 ({args.rag_base}): {exc}")

    try:
        with httpx.Client(timeout=30.0) as c:
            h = c.get(f"{args.base.rstrip('/')}/health")
    except Exception as exc:
        fail(f"Copilot 不可达 ({args.base}): {exc}")

    if h.status_code != 200:
        fail(f"/health HTTP {h.status_code}: {h.text[:200]}")

    body = h.json()
    rag_mode = body.get("rag_mode")
    demo_warn = body.get("demo_mode_warning")
    live_req = body.get("live_linkage_required")

    print(f"rag_mode={rag_mode} · demo_mode_warning={demo_warn} · live_linkage_required={live_req}")
    print(f"rag_auto_fallback={body.get('rag_auto_fallback')} · persistence_ok={body.get('persistence_ok')}")

    if live_req and rag_mode != "live":
        fail("live 模式要求 rag_mode=live。请 copy .env.demo .env 并启动 enterprise-rag :8001")
    if demo_warn:
        fail("demo_mode_warning=true — 答辩请 RAG_AUTO_FALLBACK=0")

    persistence = body.get("persistence") or {}
    if not persistence.get("healthy"):
        hint = body.get("persistence_hint") or "POST /persistence/repair"
        fail(f"persistence unhealthy: {hint}")

    if args.smoke_run:
        try:
            with httpx.Client(timeout=120.0) as c:
                resp = c.post(
                    f"{args.base.rstrip('/')}/runs",
                    headers=TECH_HEADERS,
                    json={
                        "question": "长沙星沙 SY215C H103请报修处理",
                        "parts_hints": ["液压滤芯"],
                        "station": "长沙星沙服务站",
                    },
                )
            if resp.status_code != 200:
                fail(f"smoke POST /runs HTTP {resp.status_code}: {resp.text[:300]}")
            run = resp.json()
            if run.get("rag_client_mode") != "live":
                fail(f"smoke run rag_client_mode={run.get('rag_client_mode')}，期望 live")
            if "ask" not in (run.get("rag_linkage") or []):
                fail(f"smoke run rag_linkage 缺少 ask: {run.get('rag_linkage')}")
            ok(f"smoke run status={run.get('status')} rag_linkage={' → '.join(run.get('rag_linkage') or [])}")
        except Exception as exc:
            fail(f"smoke POST /runs 失败: {exc}")

    ok("preflight passed — 可开始演示")
    print("提示: RAG 慢时可预跑 P1 后用 python scripts/replay_trace.py --latest 回放 trace")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
