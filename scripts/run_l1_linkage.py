#!/usr/bin/env python3
"""L1 HTTP 契约联调验收（Compose stub 或任意契约兼容 :8001）。

流程：health → contract check → V1 token 门 → P1 draft→HITL→inbox(source=copilot_hitl)

产出：data/eval/l1_linkage_report.json
  evidence_tier=L1 · l1_verified · live_verified=false（永不自称 L2）

用法（服务已起）：
  python scripts/run_l1_linkage.py
  python scripts/run_l1_linkage.py --rag-base http://127.0.0.1:8001 --cop-base http://127.0.0.1:8002

Compose：
  docker compose -f docker-compose.joint.yml up --build -d
  docker compose -f docker-compose.joint.yml exec api python scripts/reset_demo_state.py
  docker compose -f docker-compose.joint.yml exec api python scripts/run_l1_linkage.py
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "eval" / "l1_linkage_report.json"
RAG_DEFAULT = "http://127.0.0.1:8001"
COP_DEFAULT = "http://127.0.0.1:8002"
TECH = {"X-API-Key": "demo-technician", "Content-Type": "application/json"}
CHIEF = {"X-API-Key": "demo-chief", "Content-Type": "application/json"}


def _load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _git_sha() -> str | None:
    from app.eval.ssot import resolve_git_sha

    return resolve_git_sha()


def run(*, rag_base: str, cop_base: str) -> dict[str, Any]:
    import httpx

    from app.eval.evidence_tier import CLAIM_MATRIX, enforce_pack_tier_rules
    from app.policy.hitl_layers import confirmations_covering
    from app.tools.rag_contract import CONTRACT_VERSION

    report: dict[str, Any] = {
        "schema": "l1_linkage_report/v1",
        "evidence_tier": "L1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "hosts": {"rag": rag_base, "copilot": cop_base},
        "contract_version": CONTRACT_VERSION,
        "live_verified": False,  # L1 铁律：永不 true
        "l1_verified": False,
        "checks": {},
        "claim": CLAIM_MATRIX["L1"],
        "forbidden": [
            "称本报告为 live_verified / L2",
            "称契约桩证明了检索质量",
            "用 --from-artifacts 冒充本报告",
        ],
    }

    # --- health ---
    try:
        rh = httpx.get(f"{rag_base.rstrip('/')}/health", timeout=15.0)
        rag_h = rh.json() if rh.status_code == 200 else {}
    except Exception as exc:  # noqa: BLE001
        report["checks"]["rag_health"] = {"ok": False, "error": str(exc)}
        report["error"] = f"RAG unreachable: {exc}"
        return enforce_pack_tier_rules(report)

    tier_ok = (
        rag_h.get("evidence_tier") == "L1"
        or str(rag_h.get("mode") or "").lower() in {"contract_stub", "rag_contract_stub"}
        or rag_h.get("consumer_contract_version_supported") == CONTRACT_VERSION
    )
    ver_ok = rag_h.get("consumer_contract_version_supported") == CONTRACT_VERSION
    gate_on = bool(rag_h.get("submit_require_copilot_token")) and bool(
        rag_h.get("copilot_submit_token_configured")
    )
    report["checks"]["rag_health"] = {
        "ok": rh.status_code == 200 and ver_ok and tier_ok,
        "status": rh.status_code,
        "mode": rag_h.get("mode"),
        "evidence_tier": rag_h.get("evidence_tier"),
        "contract_version_match": ver_ok,
        "submit_gate": gate_on,
    }
    report["rag_health"] = {
        "mode": rag_h.get("mode"),
        "evidence_tier": rag_h.get("evidence_tier"),
        "consumer_contract_version_supported": rag_h.get(
            "consumer_contract_version_supported"
        ),
    }
    print(
        f"[{'PASS' if report['checks']['rag_health']['ok'] else 'FAIL'}] "
        f"RAG health mode={rag_h.get('mode')!r} tier={rag_h.get('evidence_tier')!r}"
    )

    try:
        ch = httpx.get(f"{cop_base.rstrip('/')}/health", headers=TECH, timeout=20.0)
        cop_h = ch.json() if ch.status_code == 200 else {}
    except Exception as exc:  # noqa: BLE001
        report["checks"]["copilot_health"] = {"ok": False, "error": str(exc)}
        report["error"] = f"Copilot unreachable: {exc}"
        return enforce_pack_tier_rules(report)

    # L1 时 Copilot 会把可达 HTTP 标为 rag_mode=live（表示 HTTP 可达，≠ L2）
    report["checks"]["copilot_health"] = {
        "ok": ch.status_code == 200,
        "status": ch.status_code,
        "rag_mode": cop_h.get("rag_mode"),
        "rag_contract_version": cop_h.get("rag_contract_version"),
        "note": "rag_mode=live 仅表示 HTTP 可达；L1 仍不得 live_verified",
    }
    print(
        f"[{'PASS' if ch.status_code == 200 else 'FAIL'}] "
        f"Copilot health rag_mode={cop_h.get('rag_mode')!r}"
    )

    if not report["checks"]["rag_health"]["ok"] or not report["checks"]["copilot_health"]["ok"]:
        report["error"] = "health failed"
        return enforce_pack_tier_rules(report)

    if not gate_on:
        report["checks"]["submit_gate"] = {"ok": False, "reason": "token gate off"}
        report["error"] = "RAG submit gate must be on for L1"
        return enforce_pack_tier_rules(report)
    report["checks"]["submit_gate"] = {"ok": True}

    # --- contract (ask/draft/submit/inbox + probe lane) ---
    contract_mod = _load_script("live_rag_contract_check")
    crep = contract_mod.check(rag_base)
    report["checks"]["contract"] = {
        "ok": bool(crep.get("all_ok")),
        "errors": crep.get("errors"),
        "detail": crep.get("checks"),
    }
    print(f"[{'PASS' if crep.get('all_ok') else 'FAIL'}] consumer contract check")

    # --- V1: no-token business → 403 ---
    red = httpx.post(
        f"{rag_base.rstrip('/')}/work-orders/submit",
        headers={"X-API-Key": "demo-key", "Content-Type": "application/json"},
        json={
            "draft": {
                "ticket_type": "fault",
                "fault_codes": ["H103"],
                "machine_model": "SY215C",
            },
            "note": "l1-red",
            "source": "copilot_hitl",
            "submitted_by": "copilot",
            "run_id": "l1-red",
        },
        timeout=30.0,
    )
    red_ok = red.status_code == 403
    report["checks"]["V1_no_token_reject"] = {
        "ok": red_ok,
        "status_code": red.status_code,
    }
    print(f"[{'PASS' if red_ok else 'FAIL'}] V1 no-token business submit → 403")

    # --- P1 draft → HITL → submit → inbox ---
    p1 = httpx.post(
        f"{cop_base.rstrip('/')}/playbooks/p1_xingsha_h103/run",
        headers=TECH,
        timeout=180.0,
    )
    p1b = p1.json() if p1.status_code == 200 else {}
    run_id = p1b.get("run_id")
    cert = p1b.get("decision_certificate") or {}
    policy_ids = list(cert.get("policy_ids") or [])
    hitl_ok = p1b.get("status") == "waiting_hitl" and "POL-PARTS-01" in policy_ids
    report["checks"]["P1_parts_hitl"] = {
        "ok": hitl_ok,
        "status": p1b.get("status"),
        "run_id": run_id,
        "policy_ids": policy_ids,
        "rag_client_mode": p1b.get("rag_client_mode"),
    }
    print(
        f"[{'PASS' if hitl_ok else 'FAIL'}] P1 waiting_hitl + POL-PARTS-01 "
        f"(status={p1b.get('status')})"
    )

    ownership_ok = False
    after: dict[str, Any] = {}
    if hitl_ok and run_id:
        pending = list((p1b.get("hitl") or {}).get("pending_layers") or [])
        approve = httpx.post(
            f"{cop_base.rstrip('/')}/runs/{run_id}/hitl",
            headers=CHIEF,
            json={
                "decision": "approve",
                "note": "l1_linkage",
                "confirmations": confirmations_covering(pending),
            },
            timeout=180.0,
        )
        ab = approve.json() if approve.status_code == 200 else {}
        submit = ab.get("work_order_submit") or {}
        tid = submit.get("ticket_id") or (ab.get("decision_certificate") or {}).get(
            "ticket_id"
        )
        after = {
            "approve_status": approve.status_code,
            "run_status": ab.get("status"),
            "destination": submit.get("destination"),
            "source": submit.get("source"),
            "submitted_by": submit.get("submitted_by"),
            "ticket_id": tid,
            "run_id": submit.get("run_id") or run_id,
        }
        if tid:
            detail = httpx.get(
                f"{rag_base.rstrip('/')}/work-orders/inbox/{tid}",
                headers={"X-API-Key": "demo-key"},
                timeout=30.0,
            )
            if detail.status_code == 200:
                d = detail.json()
                after["inbox_source"] = d.get("source")
                after["inbox_run_id"] = d.get("run_id")
                # probe 不得进 business：抽一条 business lane 确认 tid 在且 probe 不在
            biz = httpx.get(
                f"{rag_base.rstrip('/')}/work-orders/inbox",
                params={"lane": "business", "limit": 50},
                headers={"X-API-Key": "demo-key"},
                timeout=30.0,
            )
            if biz.status_code == 200:
                bids = {
                    str(i.get("ticket_id") or "")
                    for i in (biz.json().get("items") or [])
                }
                after["in_business_lane"] = tid in bids

        ownership_ok = (
            after.get("run_status") == "succeeded"
            and after.get("destination") == "rag_mock_inbox"
            and after.get("source") == "copilot_hitl"
            and after.get("inbox_source") == "copilot_hitl"
            and bool(after.get("inbox_run_id") or after.get("run_id"))
            and after.get("in_business_lane") is True
        )

    report["checks"]["draft_hitl_inbox"] = {"ok": ownership_ok, "detail": after}
    print(
        f"[{'PASS' if ownership_ok else 'FAIL'}] draft→HITL→inbox "
        f"source={after.get('inbox_source')!r}"
    )

    # probe 不进 business：复用 contract 结果
    probe_ok = bool((crep.get("checks") or {}).get("submit_ownership", {}).get("ok"))
    report["checks"]["V2_probe_not_business"] = {"ok": probe_ok}

    all_checks = [
        report["checks"]["rag_health"]["ok"],
        report["checks"]["copilot_health"]["ok"],
        report["checks"]["submit_gate"]["ok"],
        report["checks"]["contract"]["ok"],
        report["checks"]["V1_no_token_reject"]["ok"],
        report["checks"]["P1_parts_hitl"]["ok"],
        report["checks"]["draft_hitl_inbox"]["ok"],
        report["checks"]["V2_probe_not_business"]["ok"],
    ]
    report["l1_verified"] = all(all_checks)
    report["all_ok"] = report["l1_verified"]
    report["live_verified"] = False
    report["suggested_claim"] = (
        "CI/Compose 可复现 HTTP 契约联调（evidence_tier=L1）；"
        "不宣称检索质量或 live_verified"
        if report["l1_verified"]
        else "L1 未全绿 — 勿宣称契约联调通过"
    )
    return enforce_pack_tier_rules(report)


def main() -> int:
    parser = argparse.ArgumentParser(description="L1 HTTP contract linkage verify")
    parser.add_argument("--rag-base", default=RAG_DEFAULT)
    parser.add_argument("--cop-base", default=COP_DEFAULT)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()

    report = run(rag_base=args.rag_base, cop_base=args.cop_base)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    print(
        f"evidence_tier={report.get('evidence_tier')} "
        f"l1_verified={report.get('l1_verified')} "
        f"live_verified={report.get('live_verified')} "
        f"(must stay false for L1)"
    )
    print(f"建议口径：{report.get('suggested_claim')}")
    return 0 if report.get("l1_verified") else 1


if __name__ == "__main__":
    raise SystemExit(main())
