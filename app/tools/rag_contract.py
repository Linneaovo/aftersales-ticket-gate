"""enterprise-rag ↔ Copilot 可执行响应契约（热路径 SSOT，供 RagClient 使用）。

文档见 docs/RAG_COPILOT_CONTRACT.md。FakeRag / Live 共用同一套校验。
兼容再导出：`app.eval.rag_response_contract`（旧 import 路径）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.tools.work_order_client import extract_draft_body

CONTRACT_VERSION = "2026-08-29.1"

_CONTRACT_CHECK_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "eval" / "live_rag_contract_check.json"
)


def _err(errors: list[str], msg: str) -> None:
    errors.append(msg)


def validate_ask_response(payload: Any) -> list[str]:
    """校验 /ask（或等价 ask 载荷）消费方必填字段。"""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["ask: payload must be object"]
    if "answer" not in payload or not isinstance(payload.get("answer"), str):
        _err(errors, "ask: answer must be string")
    sources = payload.get("sources")
    if sources is None:
        _err(errors, "ask: sources missing (use [] if empty)")
    elif not isinstance(sources, list):
        _err(errors, "ask: sources must be list")
    if "grounded" not in payload:
        _err(errors, "ask: grounded missing (required for gate)")
    elif not isinstance(payload.get("grounded"), bool):
        _err(errors, "ask: grounded must be bool")
    gs = payload.get("grounding_score")
    if gs is not None:
        try:
            float(gs)
        except (TypeError, ValueError):
            _err(errors, "ask: grounding_score must be numeric")
    if "blocked" in payload and not isinstance(payload.get("blocked"), bool):
        _err(errors, "ask: blocked must be bool when present")
    if payload.get("blocked") and not payload.get("block_reason"):
        _err(errors, "ask: blocked=true requires block_reason")
    conflicts = payload.get("conflicts")
    if conflicts is not None and not isinstance(conflicts, (list, dict)):
        _err(errors, "ask: conflicts must be list or object")
    return errors


def validate_draft_response(payload: Any) -> list[str]:
    """校验 /work-orders/draft 响应可被 extract_draft_body 消费。"""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["draft: payload must be object"]
    body = extract_draft_body(payload)
    if not body:
        _err(errors, "draft: missing draft body (ticket_type/fault_codes/fill_fields/machine_model)")
        return errors
    if not (body.get("fault_codes") or body.get("fill_fields") or body.get("ticket_type")):
        _err(errors, "draft: body should carry fault_codes, fill_fields, or ticket_type")
    return errors


def validate_submit_response(payload: Any) -> list[str]:
    """校验 /work-orders/submit 最小字段（Copilot 会再盖 destination 边界）。"""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["submit: payload must be object"]
    if not (payload.get("ticket_id") or payload.get("id") or payload.get("ok") is True):
        _err(errors, "submit: need ticket_id/id or ok=true")
    return errors


def validate_inbox_response(payload: Any) -> list[str]:
    """校验 /work-orders/inbox 列表形。"""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["inbox: payload must be object"]
    items = payload.get("items")
    if items is None:
        _err(errors, "inbox: items missing (use [] if empty)")
    elif not isinstance(items, list):
        _err(errors, "inbox: items must be list")
    return errors


def assert_contract(kind: str, payload: Any) -> None:
    validators = {
        "ask": validate_ask_response,
        "draft": validate_draft_response,
        "submit": validate_submit_response,
        "inbox": validate_inbox_response,
    }
    fn = validators.get(kind)
    if fn is None:
        raise ValueError(f"unknown contract kind: {kind}")
    errors = fn(payload)
    if errors:
        raise AssertionError(f"rag contract/{kind}: " + "; ".join(errors))


def write_contract_check_summary(report: dict[str, Any], path: Path | None = None) -> Path:
    """落盘最近一次 live_rag_contract_check 摘要（供 /health 回读）。"""
    out = path or _CONTRACT_CHECK_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "contract_version": report.get("contract_version") or CONTRACT_VERSION,
        "all_ok": bool(report.get("all_ok")),
        "rag_base": report.get("rag_base"),
        "checks": {
            k: {"ok": bool((v or {}).get("ok"))}
            for k, v in (report.get("checks") or {}).items()
            if isinstance(v, dict)
        },
        "errors": list(report.get("errors") or [])[:20],
    }
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def read_last_contract_check_summary(path: Path | None = None) -> dict[str, Any] | None:
    target = path or _CONTRACT_CHECK_PATH
    if not target.exists():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None
