#!/usr/bin/env python3
"""L1 契约级 RAG HTTP 桩（非真检索 / 非 Ollama）。

实现 enterprise-rag 消费方最小表面：
  GET  /health
  POST /knowledge-bases/{kb}/ask
  POST /work-orders/draft
  POST /work-orders/submit
  GET  /work-orders/inbox[/{ticket_id}]
  POST /knowledge-bases/{kb}/feedback  （可选，回读友好）

用途：docker-compose.joint / linkage-l1.yml —— 证明 HTTP 契约与 submit 归属。
evidence_tier=L1；不得宣称 live_verified / 检索质量。

用法：
  python scripts/rag_contract_stub.py --host 0.0.0.0 --port 8001
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, Header, HTTPException, Query, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from app.tools.rag_contract import CONTRACT_VERSION  # noqa: E402
from app.tools.rag_stub_base import build_stub_ask_payload, build_stub_draft  # noqa: E402

SUBMIT_TOKEN_HEADER = "X-Copilot-Submit-Token"
SOURCE_PROBE = "contract_probe"
SOURCE_HITL = "copilot_hitl"
LEGACY = "legacy_unspecified"

_INBOX: list[dict[str, Any]] = []
_FEEDBACK: list[dict[str, Any]] = []


def _env_token_required() -> bool:
    return os.getenv("SUBMIT_REQUIRE_COPILOT_TOKEN", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
        "",
    }


def _env_token() -> str:
    return (os.getenv("COPILOT_SUBMIT_TOKEN") or "demo-copilot-submit-shared").strip()


def _normalize_source(raw: Any) -> str:
    s = (str(raw).strip() if raw is not None else "") or LEGACY
    return s


def _match_lane(source: str, lane: str) -> bool:
    lane_norm = (lane or "all").strip().lower() or "all"
    if lane_norm in {"", "all", "*"}:
        return True
    if lane_norm == "business":
        return source == SOURCE_HITL
    if lane_norm == "probe":
        return source == SOURCE_PROBE
    return True


def create_app() -> FastAPI:
    app = FastAPI(
        title="RAG Contract Stub (L1)",
        version="l1-stub",
        description="HTTP 契约桩；不证检索质量。evidence_tier=L1",
    )

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "mode": "contract_stub",
            "provider": "rag_contract_stub",
            "evidence_tier": "L1",
            "consumer_contract_version_supported": CONTRACT_VERSION,
            "submit_require_copilot_token": _env_token_required(),
            "copilot_submit_token_configured": bool(_env_token()),
            "demo_kb": "demo-kb",
            "note": "L1 stub — proves HTTP contract only; not live_verified / not retrieval quality",
        }

    @app.post("/knowledge-bases/{kb}/ask")
    async def ask(kb: str, request: Request) -> dict[str, Any]:
        body = await request.json()
        question = str((body or {}).get("question") or "")
        payload = build_stub_ask_payload(question)
        payload["request_id"] = f"l1-ask-{uuid.uuid4().hex[:10]}"
        payload["kb"] = kb
        return payload

    @app.post("/work-orders/draft")
    async def draft(request: Request) -> dict[str, Any]:
        _ = await request.json()
        # 推荐缺料件 → Copilot POL-PARTS-01
        return build_stub_draft(["液压泵总成"])

    @app.post("/work-orders/submit")
    async def submit(
        request: Request,
        x_copilot_submit_token: str | None = Header(default=None, alias=SUBMIT_TOKEN_HEADER),
    ) -> dict[str, Any]:
        body = await request.json()
        source = _normalize_source((body or {}).get("source"))
        submitted_by = str((body or {}).get("submitted_by") or "")
        run_id = (body or {}).get("run_id")
        phase = (body or {}).get("decision_certificate_phase")
        note = str((body or {}).get("note") or "")

        if _env_token_required() and source != SOURCE_PROBE:
            expected = _env_token()
            if not expected:
                raise HTTPException(
                    status_code=503,
                    detail="SUBMIT_REQUIRE_COPILOT_TOKEN=1 但未配置 COPILOT_SUBMIT_TOKEN",
                )
            if (x_copilot_submit_token or "").strip() != expected:
                raise HTTPException(
                    status_code=403,
                    detail="业务 submit 需要有效 X-Copilot-Submit-Token（探针 contract_probe 除外）",
                )

        ticket_id = f"L1-{uuid.uuid4().hex[:10].upper()}"
        item = {
            "ok": True,
            "ticket_id": ticket_id,
            "id": ticket_id,
            "source": source,
            "submitted_by": submitted_by or ("contract_probe" if source == SOURCE_PROBE else "copilot"),
            "run_id": run_id,
            "decision_certificate_phase": phase,
            "note": note,
            "destination": "rag_mock_inbox",
            "is_production_ticket": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "draft": (body or {}).get("draft") or {},
        }
        _INBOX.insert(0, item)
        return {
            "ok": True,
            "ticket_id": ticket_id,
            "id": ticket_id,
            "source": item["source"],
            "submitted_by": item["submitted_by"],
            "run_id": run_id,
            "destination": "rag_mock_inbox",
            "is_production_ticket": False,
        }

    @app.get("/work-orders/inbox")
    def inbox(
        limit: int = Query(default=20, ge=1, le=200),
        lane: str = Query(default="all"),
        source: str | None = Query(default=None),
    ) -> dict[str, Any]:
        items = list(_INBOX)
        if source:
            items = [i for i in items if i.get("source") == source]
        else:
            items = [i for i in items if _match_lane(str(i.get("source") or ""), lane)]
        items = items[:limit]
        return {"items": items, "count": len(items)}

    @app.get("/work-orders/inbox/{ticket_id}")
    def inbox_detail(ticket_id: str) -> dict[str, Any]:
        for item in _INBOX:
            if str(item.get("ticket_id") or "") == ticket_id:
                return item
        raise HTTPException(status_code=404, detail=f"ticket {ticket_id} not found")

    @app.post("/knowledge-bases/{kb}/feedback")
    async def feedback(kb: str, request: Request) -> dict[str, Any]:
        body = await request.json()
        rid = str((body or {}).get("run_id") or f"fb-{uuid.uuid4().hex[:8]}")
        rec = {
            "ok": True,
            "id": f"fb-{uuid.uuid4().hex[:8]}",
            "kb": kb,
            "run_id": rid,
            "rating": (body or {}).get("rating") or "up",
            "sources": (body or {}).get("sources") or [],
        }
        _FEEDBACK.append(rec)
        return rec

    @app.get("/knowledge-bases/{kb}/feedback")
    def feedback_list(kb: str, run_id: str | None = None) -> dict[str, Any]:
        items = [f for f in _FEEDBACK if f.get("kb") == kb]
        if run_id:
            items = [f for f in items if f.get("run_id") == run_id]
        return {"run_id": run_id, "count": len(items), "items": items}

    @app.post("/__reset")
    def reset() -> dict[str, Any]:
        """测试便利：清空 inbox（仅 stub）。"""
        _INBOX.clear()
        _FEEDBACK.clear()
        return {"ok": True, "cleared": True}

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})

    return app


app = create_app()


def main() -> int:
    parser = argparse.ArgumentParser(description="L1 RAG contract HTTP stub")
    parser.add_argument("--host", default=os.getenv("RAG_STUB_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("RAG_STUB_PORT", "8001")))
    args = parser.parse_args()
    import uvicorn

    print(
        f"[L1 stub] evidence_tier=L1 contract={CONTRACT_VERSION} "
        f"token_required={_env_token_required()} on {args.host}:{args.port}"
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
