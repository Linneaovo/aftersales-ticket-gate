"""对真实 enterprise-rag :8001 做消费方契约抽检。

复用 app.tools.rag_contract；字段漂移非零退出。

用法：
  python scripts/live_rag_contract_check.py
  python scripts/demo_preflight.py --require-rag --contract
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.tools.rag_contract import (  # noqa: E402
    CONTRACT_VERSION,
    validate_ask_response,
    validate_draft_response,
    validate_inbox_response,
    validate_submit_response,
    write_contract_check_summary,
)
from app.tools.rag_normalize import normalize_rag_result  # noqa: E402

DEFAULT_RAG = "http://127.0.0.1:8001"
KB = "demo-kb"
HEADERS = {"X-API-Key": "demo-technician", "Content-Type": "application/json"}


def check(rag_base: str) -> dict:
    base = rag_base.rstrip("/")
    report: dict = {
        "rag_base": base,
        "contract_version": CONTRACT_VERSION,
        "checks": {},
        "all_ok": True,
    }
    errors: list[str] = []

    with httpx.Client(timeout=120.0, headers=HEADERS) as c:
        h = c.get(f"{base}/health")
        if h.status_code != 200:
            report["all_ok"] = False
            report["health_error"] = f"HTTP {h.status_code}"
            return report
        report["checks"]["health"] = {"ok": True}

        ask = c.post(
            f"{base}/knowledge-bases/{KB}/ask",
            json={
                "question": "SY215C 故障码 H103 是什么？",
                "history": [],
                "filters": {},
                "parameters": {},
            },
        )
        ask_body = ask.json() if ask.status_code == 200 else {}
        ask_norm = normalize_rag_result(ask_body if isinstance(ask_body, dict) else {})
        ask_errs = validate_ask_response(ask_norm) if ask.status_code == 200 else [f"HTTP {ask.status_code}"]
        report["checks"]["ask"] = {"ok": not ask_errs, "errors": ask_errs}
        if ask_errs:
            errors.extend(f"ask:{e}" for e in ask_errs)

        draft = c.post(
            f"{base}/work-orders/draft",
            json={
                "question": "长沙星沙 SY215C H103 报修开单",
                "knowledge_base": KB,
                "answer": str(ask_norm.get("answer") or ""),
                "role": "technician",
                # RAG 默认禁止 inline sources（须服务端自检索）；勿回传 ask.sources
            },
        )
        draft_body = draft.json() if draft.status_code == 200 else {}
        draft_errs = (
            validate_draft_response(draft_body)
            if draft.status_code == 200
            else [f"HTTP {draft.status_code}"]
        )
        report["checks"]["draft"] = {"ok": not draft_errs, "errors": draft_errs}
        if draft_errs:
            errors.extend(f"draft:{e}" for e in draft_errs)

        # submit 仅抽检契约形；标记 contract_probe，与业务 copilot_hitl 区分
        from app.tools.work_order_client import extract_draft_body

        body = extract_draft_body(draft_body) if isinstance(draft_body, dict) else {}
        submit = c.post(
            f"{base}/work-orders/submit",
            json={
                "draft": body or {"ticket_type": "fault", "fault_codes": ["H103"]},
                "note": "contract-check",
                "submitted_by": "contract_probe",
                "source": "contract_probe",
                "decision_certificate_phase": "probe",
            },
        )
        submit_body = submit.json() if submit.status_code == 200 else {}
        submit_errs = (
            validate_submit_response(submit_body)
            if submit.status_code == 200
            else [f"HTTP {submit.status_code}"]
        )
        report["checks"]["submit"] = {"ok": not submit_errs, "errors": submit_errs}
        if submit_errs:
            errors.extend(f"submit:{e}" for e in submit_errs)

        ticket_id = str(submit_body.get("ticket_id") or "")
        ownership_errs: list[str] = []
        if submit.status_code == 200 and ticket_id:
            # E4 L2：探针落箱须持久化 source=contract_probe（不依赖 note）
            if submit_body.get("source") != "contract_probe":
                ownership_errs.append(
                    f"submit.source={submit_body.get('source')!r} want contract_probe"
                )
            detail = c.get(f"{base}/work-orders/inbox/{ticket_id}")
            if detail.status_code != 200:
                ownership_errs.append(f"inbox detail HTTP {detail.status_code}")
            else:
                dbody = detail.json()
                if dbody.get("source") != "contract_probe":
                    ownership_errs.append(
                        f"inbox.detail.source={dbody.get('source')!r} want contract_probe"
                    )
            probe_list = c.get(
                f"{base}/work-orders/inbox",
                params={"limit": 20, "lane": "probe"},
            )
            if probe_list.status_code == 200:
                pids = {
                    str(i.get("ticket_id") or "")
                    for i in (probe_list.json().get("items") or [])
                }
                if ticket_id not in pids:
                    ownership_errs.append("probe lane missing contract_probe ticket")
            business_list = c.get(
                f"{base}/work-orders/inbox",
                params={"limit": 20, "lane": "business"},
            )
            if business_list.status_code == 200:
                bids = {
                    str(i.get("ticket_id") or "")
                    for i in (business_list.json().get("items") or [])
                }
                if ticket_id in bids:
                    ownership_errs.append("contract_probe ticket leaked into business lane")
        elif submit.status_code == 200:
            ownership_errs.append("submit ok but missing ticket_id")
        report["checks"]["submit_ownership"] = {
            "ok": not ownership_errs,
            "errors": ownership_errs,
            "ticket_id": ticket_id or None,
        }
        if ownership_errs:
            errors.extend(f"ownership:{e}" for e in ownership_errs)

        inbox = c.get(f"{base}/work-orders/inbox", params={"limit": 5})
        inbox_body = inbox.json() if inbox.status_code == 200 else {}
        # 兼容 items 或 list 根
        if isinstance(inbox_body, list):
            inbox_body = {"items": inbox_body}
        inbox_errs = (
            validate_inbox_response(inbox_body)
            if inbox.status_code == 200
            else [f"HTTP {inbox.status_code}"]
        )
        report["checks"]["inbox"] = {"ok": not inbox_errs, "errors": inbox_errs}
        if inbox_errs:
            errors.extend(f"inbox:{e}" for e in inbox_errs)

    report["all_ok"] = not errors
    report["errors"] = errors
    write_contract_check_summary(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rag-base", default=DEFAULT_RAG)
    parser.add_argument("--out", default="", help="optional JSON path")
    args = parser.parse_args()
    report = check(args.rag_base)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    print(f"contract_version={report.get('contract_version')}")
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    if report.get("all_ok"):
        print("[OK] live RAG consumer contract")
        return 0
    print("[FAIL] live RAG consumer contract")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
