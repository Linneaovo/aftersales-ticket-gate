#!/usr/bin/env python3
"""Fixture 响应与 contract_consumer_fields / rag_contract 漂移检查。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CONSUMER = ROOT / "data" / "eval" / "contract_consumer_fields.json"


def _check_ask_fields(payload: dict, spec: dict) -> list[str]:
    errs: list[str] = []
    for key in spec.get("required") or []:
        if key not in payload:
            errs.append(f"ask missing required field: {key}")
    for key in spec.get("breaking_if_removed") or []:
        if key not in payload:
            errs.append(f"ask breaking field removed: {key}")
    return errs


def main() -> int:
    from app.tools.rag_contract import (
        CONTRACT_VERSION,
        validate_ask_response,
        validate_draft_response,
        validate_submit_response,
    )
    from app.tools.demo_rag import DemoRagClient
    from app.tools.rag_stub_base import build_stub_ask_payload, build_stub_draft

    consumer = json.loads(CONSUMER.read_text(encoding="utf-8"))
    if consumer.get("contract_version") != CONTRACT_VERSION:
        print(
            f"[FAIL] contract_consumer_fields version {consumer.get('contract_version')} "
            f"≠ rag_contract {CONTRACT_VERSION}"
        )
        return 1

    client = DemoRagClient()
    ask = client.ask("SY215C H103 报修")
    draft = client.draft_work_order()
    submit = client.submit_work_order(build_stub_draft(), run_id="contract-drift-check")

    errs: list[str] = []
    errs.extend(_check_ask_fields(ask, consumer.get("ask") or {}))
    errs.extend(validate_ask_response(ask))
    errs.extend(validate_draft_response(draft))
    errs.extend(validate_submit_response(submit))

    # stub base 与 DemoRag 默认 ask 也应一致
    stub_ask = build_stub_ask_payload("SY215C H103")
    errs.extend(validate_ask_response(stub_ask))

    if errs:
        for e in errs:
            print(f"[FAIL] {e}")
        return 1
    print(f"[OK] fixture responses match contract {CONTRACT_VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
