"""B6：degraded 路径 submit 后，按 run_id 回读 feedback=down。

默认离线 FakeRag（不挡 claimable）。
可选 --live：P1 approve→submit 后真打 :8001 按 run_id 回读。

输出：data/eval/feedback_roundtrip.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "eval" / "feedback_roundtrip.json"


def _run_offline() -> dict[str, Any]:
    from app.graph.runner import apply_hitl, create_initial_state, run_until_pause
    from app.policy.hitl_layers import compute_pending_layers, confirmations_covering
    from app.tools.eval_stub import EvalRagStub

    payload = {
        "answer": "检索摘要（生成降级）",
        "sources": [{"chunk": {"source": "故障码对照表.txt", "text": "H103"}, "score": 0.8}],
        "grounded": True,
        "grounding_score": 0.7,
        "blocked": False,
        "retrieve_only": True,
        "conflicts": [],
    }
    client = EvalRagStub(
        ask_payload=payload,
        parts=["液压滤芯"],
        ticket_id="T-DEMO-1",
        request_id="fake-req",
    )
    st = create_initial_state(
        "长沙星沙 SY215C H103请报修处理",
        api_key="demo-technician",
        station="长沙星沙服务站",
        parts_force_hints=["液压滤芯"],
        auto_submit=False,
        engine="langgraph",
    )
    paused = run_until_pause(st, client=client, persist=False)
    if paused.get("status") != "waiting_hitl":
        return {
            "mode": "offline_fakerag",
            "ok": False,
            "error": f"expected waiting_hitl got {paused.get('status')}",
        }
    pending = list((paused.get("hitl") or {}).get("pending_layers") or []) or compute_pending_layers(paused)
    done = apply_hitl(
        paused,
        "approve",
        "b6 feedback roundtrip",
        client=client,
        persist=False,
        approver_api_key="demo-chief",
        confirmations=confirmations_covering(pending),
    )
    run_id = str(done.get("run_id") or "")
    fb_ref = done.get("feedback_ref") or {}
    lookup = client.list_feedback_by_run_id(run_id)
    items = list(lookup.get("items") or [])
    ratings = [str(i.get("rating")) for i in items]
    ok = (
        done.get("status") == "succeeded"
        and bool(fb_ref.get("ok"))
        and fb_ref.get("rating") == "down"
        and "down" in ratings
        and bool(done.get("work_order_submit"))
    )
    return {
        "mode": "offline_fakerag",
        "ok": ok,
        "run_id": run_id,
        "feedback_ref": {
            "ok": fb_ref.get("ok"),
            "rating": fb_ref.get("rating"),
            "error": fb_ref.get("error"),
        },
        "lookup": {"count": lookup.get("count"), "ratings": ratings},
        "status": done.get("status"),
        "required_for_claimable": False,
        "note": "advisory：degraded submit → feedback down 可按 run_id 回读；不阻断 scorecard 主路径",
    }


def _run_live() -> dict[str, Any]:
    import httpx

    from app.policy.hitl_layers import confirmations_covering

    tech = {"X-API-Key": "demo-technician", "Content-Type": "application/json"}
    chief = {"X-API-Key": "demo-chief", "Content-Type": "application/json"}
    try:
        # P1 必进 HITL→approve→submit→feedback；P1b 常 succeeded 且不落箱，不能验 B6
        r = httpx.post(
            "http://127.0.0.1:8002/playbooks/p1_xingsha_h103/run",
            headers=tech,
            timeout=180.0,
        )
        body = r.json() if r.status_code == 200 else {}
        run_id = str(body.get("run_id") or "")
        status = body.get("status")
        if status != "waiting_hitl" or not run_id:
            return {
                "mode": "live",
                "ok": False,
                "run_id": run_id,
                "status": status,
                "error": "expected P1 waiting_hitl before approve",
                "required_for_claimable": False,
            }
        pending = list((body.get("hitl") or {}).get("pending_layers") or [])
        hitl = httpx.post(
            f"http://127.0.0.1:8002/runs/{run_id}/hitl",
            headers=chief,
            json={
                "decision": "approve",
                "note": "b6_live_feedback",
                "confirmations": confirmations_covering(pending),
            },
            timeout=180.0,
        )
        body = hitl.json() if hitl.status_code == 200 else {}
        status = body.get("status")
        fb_ref = body.get("feedback_ref") or {}
        if not fb_ref:
            return {
                "mode": "live",
                "ok": False,
                "run_id": run_id,
                "status": status,
                "feedback_ref": fb_ref,
                "lookup": {},
                "required_for_claimable": False,
                "skip_reason": "feedback_ref missing — 请确认 Copilot :8002 已加载 B6 写入补丁",
                "note": "live 探测写入+按 run_id 回读；失败不挡 claimable",
            }
        lookup: dict[str, Any] = {}
        lookup_ok = False
        if run_id and fb_ref.get("ok"):
            lr = httpx.get(
                "http://127.0.0.1:8001/knowledge-bases/demo-kb/feedback",
                headers={"X-API-Key": "demo-key"},
                params={"run_id": run_id},
                timeout=30.0,
            )
            lookup = lr.json() if lr.status_code == 200 else {"http_status": lr.status_code, "text": lr.text[:200]}
            items = lookup.get("items") if isinstance(lookup, dict) else []
            lookup_ok = lr.status_code == 200 and isinstance(items, list) and len(items) >= 1
            if isinstance(lookup, dict) and items:
                lookup["ratings"] = [str(i.get("rating")) for i in items if isinstance(i, dict)]
            if lr.status_code in {404, 405}:
                lookup["skip_reason"] = "RAG 缺 GET /feedback?run_id= — 请重启 enterprise-rag :8001"
        # Live 主路径常为 up；down 由 offline degraded 幕证明。此处只证「写入 + 按 run_id 回读」
        ok = bool(status == "succeeded" and fb_ref.get("ok") and lookup_ok)
        return {
            "mode": "live",
            "ok": ok,
            "run_id": run_id,
            "status": status,
            "feedback_ref": {
                "ok": fb_ref.get("ok"),
                "rating": fb_ref.get("rating"),
                "error": fb_ref.get("error"),
            },
            "lookup": lookup if isinstance(lookup, dict) else {"raw": lookup},
            "required_for_claimable": False,
            "note": "live=P1 approve 后按 run_id 回读；down 见 offline；失败不挡 claimable",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "mode": "live",
            "ok": False,
            "error": str(exc),
            "required_for_claimable": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="B6 feedback roundtrip by run_id")
    parser.add_argument("--live", action="store_true", help="also probe :8001/:8002")
    args = parser.parse_args()
    offline = _run_offline()
    report: dict[str, Any] = {
        "schema": "feedback_roundtrip/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "offline": offline,
        "live": None,
        "all_ok": bool(offline.get("ok")),
        "required_for_claimable": False,
    }
    if args.live:
        live = _run_live()
        report["live"] = live
        report["live_ok"] = bool(live.get("ok"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT} offline_ok={offline.get('ok')} live={report.get('live_ok')}")
    return 0 if offline.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
