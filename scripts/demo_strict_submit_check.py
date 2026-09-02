# -*- coding: utf-8 -*-
"""E4 L3 演示档验收：硬门开启时一红一绿。

红：直打 RAG 业务 submit 无 token → 403
绿：Copilot 站长批准路径（带 token）→ rag_mock_inbox + source=copilot_hitl

若 RAG /health.submit_require_copilot_token=false：跳过并打印开启步骤（exit 0）。
改 RAG env 后必须重启 :8001。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx

COP = "http://127.0.0.1:8002"
RAG = "http://127.0.0.1:8001"
TECH = {"X-API-Key": "demo-technician", "Content-Type": "application/json"}
CHIEF = {"X-API-Key": "demo-chief", "Content-Type": "application/json"}
RAG_KEY = {"X-API-Key": "demo-key", "Content-Type": "application/json"}
TIMEOUT = 180.0
OUT = ROOT / "data" / "eval" / "demo_strict_submit_check.json"


def main() -> int:
    report: dict = {
        "schema": "demo_strict_submit_check/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "skipped": False,
        "all_ok": False,
        "checks": {},
    }
    try:
        rag_h = httpx.get(f"{RAG}/health", timeout=10.0)
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] RAG unreachable: {exc}")
        # 不可达时标记 skipped，避免污染 synergy_checks 回退到 live_rag_contract_check
        report["skipped"] = True
        report["skip_reason"] = "rag_unreachable"
        report["error"] = str(exc)
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1

    body = rag_h.json() if rag_h.status_code == 200 else {}
    required = bool(body.get("submit_require_copilot_token"))
    token_cfg = bool(body.get("copilot_submit_token_configured"))
    report["rag_submit_require_copilot_token"] = required
    report["rag_copilot_submit_token_configured"] = token_cfg
    print(f"RAG submit_require_copilot_token={required} token_configured={token_cfg}")

    if not required:
        report["skipped"] = True
        report["skip_reason"] = "hard_gate_off"
        report["how_to_enable"] = [
            "1. 将 enterprise-rag/demo_strict_submit.env.example 并入 RAG .env",
            "2. 重启 :8001（必须）",
            "3. 确认 Copilot COPILOT_SUBMIT_TOKEN 同值后重跑本脚本",
            "4. 演示结束设 SUBMIT_REQUIRE_COPILOT_TOKEN=0 并再重启",
        ]
        print("[SKIP] 硬门未开（日常默认）。开启步骤见 report.how_to_enable")
        for line in report["how_to_enable"]:
            print(f"  {line}")
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {OUT}")
        return 0

    if not token_cfg:
        print("[FAIL] 硬门已开但 RAG 未配置 COPILOT_SUBMIT_TOKEN")
        report["checks"]["token_configured"] = False
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1

    draft = {
        "ticket_type": "fault_repair",
        "machine_model": "SY215C",
        "fault_codes": ["H103"],
        "fill_fields": [],
    }
    # 红：无 token 业务 submit
    red = httpx.post(
        f"{RAG}/work-orders/submit",
        headers=RAG_KEY,
        json={
            "draft": draft,
            "note": "strict_submit_red",
            "source": "copilot_hitl",
            "submitted_by": "copilot",
            "run_id": "strict-red",
        },
        timeout=30.0,
    )
    red_ok = red.status_code == 403
    report["checks"]["red_no_token_403"] = {
        "ok": red_ok,
        "status_code": red.status_code,
        "body": (red.text or "")[:200],
    }
    print(f"[{'PASS' if red_ok else 'FAIL'}] red: no-token business submit → 403 (got {red.status_code})")

    # 探针仍应可无 token（对照）
    probe = httpx.post(
        f"{RAG}/work-orders/submit",
        headers=RAG_KEY,
        json={
            "draft": draft,
            "note": "strict_submit_probe",
            "source": "contract_probe",
            "submitted_by": "contract_probe",
            "run_id": "strict-probe",
        },
        timeout=30.0,
    )
    probe_ok = probe.status_code == 200
    report["checks"]["probe_without_token_200"] = {
        "ok": probe_ok,
        "status_code": probe.status_code,
    }
    print(f"[{'PASS' if probe_ok else 'FAIL'}] probe: contract_probe without token → 200 (got {probe.status_code})")

    # 绿：Copilot 批准路径
    p1 = httpx.post(f"{COP}/playbooks/p1_xingsha_h103/run", headers=TECH, timeout=TIMEOUT)
    p1b = p1.json() if p1.status_code == 200 else {}
    run_id = p1b.get("run_id")
    green_ok = False
    detail = f"p1_status={p1.status_code} run={run_id}"
    if run_id and p1b.get("status") == "waiting_hitl":
        pending = list((p1b.get("hitl") or {}).get("pending_layers") or [])
        conf = {layer: True for layer in pending}
        approve = httpx.post(
            f"{COP}/runs/{run_id}/hitl",
            headers=CHIEF,
            json={"decision": "approve", "note": "strict_submit_green", "confirmations": conf},
            timeout=TIMEOUT,
        )
        ab = approve.json() if approve.status_code == 200 else {}
        submit = ab.get("work_order_submit") or {}
        green_ok = (
            approve.status_code == 200
            and ab.get("status") == "succeeded"
            and submit.get("destination") == "rag_mock_inbox"
            and submit.get("source") == "copilot_hitl"
        )
        detail = (
            f"approve={approve.status_code} status={ab.get('status')} "
            f"dest={submit.get('destination')} source={submit.get('source')}"
        )
    report["checks"]["green_copilot_approve"] = {"ok": green_ok, "detail": detail}
    print(f"[{'PASS' if green_ok else 'FAIL'}] green: Copilot approve+token → inbox ({detail})")

    report["all_ok"] = bool(red_ok and probe_ok and green_ok)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT}")
    print(f"=== STRICT SUBMIT {'OK' if report['all_ok'] else 'FAIL'} ===")
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
